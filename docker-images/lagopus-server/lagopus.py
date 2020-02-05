#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

# Global settings ------------------------
DIR_LAGOPUS = "/lagopus"  # state directory
SUBDIR_LAGOPUS_JOBS = "jobs"
DIR_LAGOPUS_JOBS = DIR_LAGOPUS + "/" + SUBDIR_LAGOPUS_JOBS  # state directory for jobs
lagoconfig = {"defaults": {"cores": 2, "memory": 200, "deadline": 240,}}
# ----------------------------------------
import os

from flask import Flask
from flask import render_template
from flask import send_from_directory
from flask import request
from flask import flash
from flask import redirect, url_for
from flask import jsonify
from werkzeug.utils import secure_filename

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError


app = Flask(__name__)

# ---
# k8s
# ---
import stat
import pathlib
import shutil
import datetime
import yaml
import jinja2

from kubernetes import client, config
from kubernetes.client.rest import ApiException


def lagopus_sanitycheck():
    """
    Check that:
    - all necessary directories exist
    """
    dirs = [DIR_LAGOPUS, DIR_LAGOPUS_JOBS]

    for d in dirs:
        if not os.path.exists(d):
            app.logger.error("Creating '{}'".format(d))
            pathlib.Path(d).mkdir(parents=True, exist_ok=True)


def lagopus_jobid(name, driver, time):
    """
    Generate a unique job ID based on the job name.

    ID conforms to DNS-1123 restrictions so it can be used as the name for k8s
    resources without modification.
    :name: job name as provided by user
    :driver: fuzzing driver
    :time: arbitrary time value; should be the creation time, to provide
           uniqueness when the user provides multiple jobs with the same name
    :rtype: str
    :return: job ID
    """
    return "{}.{}.{}".format(name, driver, time.strftime("%Y-%m-%d-%H-%M-%S"))


def lagopus_get_kubeapis():
    # load api
    config.load_incluster_config()
    corev1 = client.CoreV1Api()
    batchv1 = client.BatchV1Api()
    return {"corev1": corev1, "batchv1": batchv1}


apis = lagopus_get_kubeapis()


def lagopus_k8s_create_job(
    jobid, driver, target, cores=2, memory=200, deadline=240, namespace="default"
):
    """
    Add a new job.
    """
    lagopus_sanitycheck()

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("./k8s/"))

    # create job
    job = env.get_template("job.yaml")
    jobdir = DIR_LAGOPUS_JOBS + "/" + jobid
    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)
    st = os.stat(jobdir)
    os.chmod(jobdir, st.st_mode | stat.S_IWOTH | stat.S_IXOTH | stat.S_IROTH)
    app.logger.error("Job directory: {}".format(jobdir))
    jobconf = {}
    jobconf["jobname"] = jobid
    jobconf["jobid"] = jobid
    jobconf["cpu"] = str(cores)
    jobconf["memory"] = "{}Mi".format(memory)
    jobconf["deadline"] = deadline
    jobconf["driver"] = driver
    jobconf["namespace"] = namespace
    jobconf["jobpath"] = SUBDIR_LAGOPUS_JOBS + "/" + jobid
    with open(jobdir + "/job.yaml", "w") as genjob:
        rj = job.render(**jobconf)
        jobyaml = yaml.safe_load(rj)
        genjob.write(rj)
    shutil.copy(target, jobdir + "/" + "target.zip")

    response = ""
    try:
        response = apis["batchv1"].create_namespaced_job(
            jobyaml["metadata"]["namespace"], jobyaml, pretty=True
        )
    except ApiException as e:
        app.logger.error("API exception: {}".format(e))
    finally:
        app.logger.error("API response:\n{}".format(response))

    return response


def lagopus_k8s_get_jobs(namespace="default"):
    jobs = []
    for job in apis["batchv1"].list_namespaced_job(namespace).items:
        onejob = {}
        fzctr = job.spec.template.spec.containers[0]
        onejob["name"] = job.metadata.name
        onejob["cores"] = fzctr.resources.requests["cpu"]
        onejob["memory"] = fzctr.resources.requests["memory"]
        onejob["deadline"] = job.spec.active_deadline_seconds
        onejob["driver"] = "Unknown"
        for ev in fzctr.env:
            if ev.name == "DRIVER":
                onejob["driver"] = ev.value
        is_complete = False
        if job.status.conditions:
            is_complete = all(
                map(lambda c: c.type == "Complete", job.status.conditions)
            )
        onejob["status"] = "Complete" if is_complete else "Incomplete"
        jobpods = apis["corev1"].list_namespaced_pod(
            namespace, label_selector="job-name = {}".format(job.metadata.name)
        )
        if jobpods is not None and jobpods.items is not None:
            podnames = list(map(lambda x: x.metadata.name, jobpods.items))
        onejob["activepods"] = job.status.active
        onejob["pods"] = podnames
        onejob["starttime"] = str(job.status.start_time)
        onejob["jobdir"] = DIR_LAGOPUS_JOBS + "/" + job.metadata.name
        # app.logger.error("\tPods:")
        #     app.logger.error("\t- {}\t[{}]".format(pod.metadata.name, pod.status.phase))
        jobs.append(onejob)
    return jobs


# ---
# Backend
# ---
import mysql.connector
from mysql.connector import errorcode

DBCONF = {
    "user": "root",
    "password": "lagopus",
    "host": "localhost",
    "database": "lagopus",
    "raise_on_warnings": True,
    "buffered": True,
    "autocommit": True,
    "tables": ["jobs", "crashes"],
}


def lagopus_connect_db():
    """
    Connect to MySQL database and return result.

    :return: database connection
    """
    cnx = None

    try:
        connection_config = {
            k: DBCONF[k]
            for k in [
                "user",
                "password",
                "host",
                "database",
                "raise_on_warnings",
                "buffered",
                "autocommit",
            ]
        }
        cnx = mysql.connector.connect(**connection_config)
        app.logger.error("Initialized database.")
    except mysql.connector.Error as err:
        app.logger.error("Couldn't connect to MySQL: {}".format(err))

    return cnx


cnx = lagopus_connect_db()

if not cnx:
    # gunicorn will restart us until we successfully connect to the database
    exit(1)


def lagopus_create_job(name, driver, target, cores=2, memory=200, deadline=240):
    # generate unique job id
    now = datetime.datetime.now()
    jobid = lagopus_jobid(name, driver, now)

    create_timestamp = now.strftime("%Y-%m-%d %H-%M-%S")

    # insert new job into db
    cursor = cnx.cursor()
    cursor.execute(
        "INSERT INTO jobs (job_id, driver, target, cores, memory, deadline, create_time) VALUES ('{}', '{}', '{}', {}, {}, {}, '{}')".format(
            jobid, driver, target, cores, memory, deadline, create_timestamp
        )
    )
    cursor.close()

    # create in k8s
    lagopus_k8s_create_job(jobid, driver, target, cores, memory, deadline)


def lagopus_get_job(jobid=None):
    # update db from k8s
    # ...job status, etc

    # fetch from db
    cursor = cnx.cursor(dictionary=True)
    if jobid:
        cursor.execute(
            "SELECT * FROM jobs WHERE job_id = %(job_id)s", {"job_id": jobid}
        )
    else:
        cursor.execute("SELECT * FROM jobs")
    result = cursor.fetchall()
    app.logger.error("Result: {}".format(result))
    return result


def lagopus_get_job_eps(jobid):
    ic = InfluxDBClient(database=jobid)
    query = "select time, execs_per_sec from jobs;"
    try:
        data = ic.query(query)
        app.logger.warning("InfluxDB result: {}".format(data))
        results = list(data)[0]
    except InfluxDBClientError as e:
        app.logger.error("InfluxDB error: {}".format(e))
        return []

    return results


def lagopus_get_crash():
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT * FROM crashes")
    result = cursor.fetchall()
    app.logger.error("Result: {}".format(result))
    return result


# ---
# Web
# ---


# --------
# JSON API
# --------
@app.route("/api/createjob")
def lagopus_api_create_job():
    pass


@app.route("/api/jobs/eps")
def lagopus_api_get_jobs_eps():
    try:
        jobid = request.args.get("job")
        results = lagopus_get_job_eps(jobid)
        app.logger.error("backend result: {}".format(results))
        return jsonify(results)
    except:
        app.logger.warning("Couldn't get EPS for job")
        return {}


@app.route("/api/jobs")
def lagopus_api_get_jobs():
    jobs = lagopus_get_job()
    jobs = jobs if jobs else []
    return {"data": jobs}


@app.route("/api/crashes")
def lagopus_api_get_crashes():
    crashes = lagopus_get_crash()
    crashes = crashes if crashes else []
    return {"data": crashes}


# -------------
# Web interface
# -------------
app.config["UPLOAD_FOLDER"] = "/tmp/"
app.config["SECRET_KEY"] = "389afsd89j34fasd"


@app.route("/")
@app.route("/index.html")
def index():
    pagename = "Home"
    jobs = lagopus_api_get_jobs()
    jc = len(jobs["data"]) if jobs is not None else 0
    return render_template("index.html", pagename=pagename, jobcount=jc)


@app.route("/upload", methods=["POST"])
def upload():
    # check if the post request has the file part
    if "file" not in request.files:
        return "No file part"
    file = request.files["file"]
    # if user does not select file, browser also
    # submit an empty part without filename
    if not file or file.filename == "":
        flash("No selected file")
        return redirect(request.url)

    jobname = request.form.get("jobname", "")
    if jobname == "":
        flash("No job name")
        return redirect(request.url)

    driver = request.form.get("driver", "")
    if driver == "":
        flash("No driver specified")
        return redirect(request.url)

    cores = int(request.form.get("cores", lagoconfig["defaults"]["cores"]))
    memory = int(request.form.get("memory", lagoconfig["defaults"]["memory"]))
    deadline = int(request.form.get("deadline", lagoconfig["defaults"]["deadline"]))

    filename = secure_filename(file.filename)
    savepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(savepath)
    lagopus_create_job(
        jobname, driver, savepath, cores=cores, memory=memory, deadline=deadline
    )
    return redirect(url_for("jobs", filename=filename))


@app.route("/jobs.html")
def jobs():
    pagename = "Jobs"
    try:
        jobid = request.args.get("job")
    except:
        app.logger.info("No job specified")

    return render_template(
        "jobs.html",
        pagename=pagename,
        defaultdeadline=lagoconfig["defaults"]["deadline"],
        defaultmemory=lagoconfig["defaults"]["memory"],
        defaultcores=lagoconfig["defaults"]["cores"],
        jobid=jobid,
    )


@app.route("/crashes.html")
def crashes():
    pagename = "Crashes"
    return render_template("crashes.html", pagename=pagename)


@app.route("/targets.html")
def targets():
    pagename = "Targets"
    return render_template("targets.html", pagename=pagename)


@app.route("/404.html")
def fourohfour():
    pagename = "404"
    return render_template("404.html", pagename=pagename)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return send_from_directory("templates/", path)
