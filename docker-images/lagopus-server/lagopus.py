#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

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

# Global settings ------------------------
CONFIG = {
    "dirs": {"base": "/lagopus", "jobs": "/lagopus/jobs",},
    "database": {
        "connection": {
            "user": "root",
            "password": "lagopus",
            "host": "localhost",
            "database": "lagopus",
            "raise_on_warnings": True,
            "buffered": True,
            "autocommit": True,
        },
        "tables": ["jobs", "crashes"],
    },
    "jobs": {"cores": 2, "memory": 200, "deadline": 240,},
}

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
    for k, v in CONFIG["dirs"].items():
        if not os.path.exists(v):
            app.logger.error("Creating '{}'".format(v))
            pathlib.Path(v).mkdir(parents=True, exist_ok=True)


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
    jobdir = CONFIG["dirs"]["jobs"] + "/" + jobid
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
    jobconf["jobpath"] = "jobs/" + jobid
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


def lagopus_k8s_get_jobs(jobid=None, namespace="default"):
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
        onejob["jobdir"] = "jobs/" + job.metadata.name
        # app.logger.error("\tPods:")
        #     app.logger.error("\t- {}\t[{}]".format(pod.metadata.name, pod.status.phase))
        jobs.append(onejob)
    return jobs


# ---
# Backend
# ---
import mysql.connector
from mysql.connector import errorcode

cnx = None


def lagopus_db_connect():
    """
    Connect to MySQL database and return result.

    :return: database connection
    """
    cnx = None

    try:
        cnx = mysql.connector.connect(**CONFIG["database"]["connection"])
        app.logger.error("Initialized database.")
    except mysql.connector.Error as err:
        app.logger.error("Couldn't connect to MySQL: {}".format(err))

    return cnx


def lagopus_db_cursor(**kwargs):
    """
    Get cursor for database

    :return: database cursor
    """
    global cnx

    if not cnx:
        cnx = lagopus_db_connect()

    try:
        cnx.ping(reconnect=True, attempts=3, delay=5)
    except mysql.connector.Error as err:
        cnx = lagopus_db_connect()

    return cnx.cursor(**kwargs)


cnx = lagopus_db_connect()

if not cnx:
    # gunicorn will restart us until we successfully connect to the database
    exit(1)


def lagopus_create_job(name, driver, target, cores=2, memory=200, deadline=240):
    # generate unique job id
    now = datetime.datetime.now()
    jobid = lagopus_jobid(name, driver, now)

    status = "Created"
    create_timestamp = now.strftime("%Y-%m-%d %H-%M-%S")

    # insert new job into db
    cursor = lagopus_db_cursor()
    cursor.execute(
        "INSERT INTO jobs (job_id, status, driver, target, cores, memory, deadline, create_time) VALUES ('{}', '{}', '{}', '{}', {}, {}, {}, '{}')".format(
            jobid, status, driver, target, cores, memory, deadline, create_timestamp
        )
    )
    cursor.close()

    # create in k8s
    lagopus_k8s_create_job(jobid, driver, target, cores, memory, deadline)

    return jobid


def lagopus_get_job(jobid=None):
    cursor = lagopus_db_cursor(dictionary=True)

    # update db from k8s
    # ...job status, etc
    k8s_jobs = lagopus_k8s_get_jobs(jobid)
    # Set all incomplete job statuses to "Unknown"
    cursor.execute("UPDATE jobs SET status = %(status)s WHERE status <> 'Complete'", {"status": "Unknown"})
    # Update with statuses from k8s
    for job in k8s_jobs:
        app.logger.warning(job)
        cursor.execute(
            "UPDATE jobs SET status = %(status)s WHERE job_id = %(job_id)s",
            {"status": job["status"], "job_id": job["name"]},
        )

    # fetch from db
    cursor = lagopus_db_cursor(dictionary=True)
    if jobid:
        cursor.execute(
            "SELECT * FROM jobs WHERE job_id = %(job_id)s", {"job_id": jobid}
        )
    else:
        cursor.execute("SELECT * FROM jobs")
    result = cursor.fetchall()
    app.logger.error("Result: {}".format(result))

    return result


def lagopus_get_job_stats(jobid, since=None, summary=False):
    ic = InfluxDBClient(database="lagopus")
    app.logger.error(">>> Since: {}".format(since))

    query = "select MEAN(*) from jobs"
    query += " where job_id = '{}'".format(jobid) if jobid else ""
    query += " AND time > '{}'".format(since) if since else ""
    # TODO: revisit this; this is a bit of a hack. Without downsampling like
    # this, 10 hours or so the amount of metrics data will be in the mb range.
    # The web UI especially doesn't like this, and it gets extremely slow when
    # we plot several mb of data in the monitoring graphs. 1 minute seems like
    # a happy medium; still decent resolution, but low enough that the data
    # size isn't huge after a few days. Should be revisited as I'm sure someone
    # will eventually have a use case for higher res data.
    #
    # Also because of the MEAN(), Influx changes all the field names to prefix
    # with 'mean_', bit annoying -.-
    query += " GROUP BY time(1m)"

    app.logger.warning("influx query: {}".format(query))

    try:
        data = ic.query(query)
        app.logger.warning("InfluxDB result: {}".format(data))
        results = list(data)[0]
    except InfluxDBClientError as e:
        app.logger.error("InfluxDB error: {}".format(e))
        return []

    return results


def lagopus_get_crash():
    cursor = lagopus_db_cursor(dictionary=True)
    cursor.execute("SELECT * FROM crashes")
    result = cursor.fetchall()
    app.logger.error("Result: {}".format(result))
    return result


# ---
# Web
# ---


@app.after_request
def apply_caching(response):
    """
    Sometimes firefox doesn't allow inline scripts? What's up with that?
    """
    response.headers["Content-Security-Policy"] = "script-src 'unsafe-inline' 'self'"
    return response


# --------
# JSON API
# --------
@app.route("/api/createjob")
def lagopus_api_create_job():
    pass


@app.route("/api/jobs/stats")
def lagopus_api_get_jobs_stats():
    jobid = None
    since = None
    try:
        jobid = request.args.get("job")
    except:
        app.logger.warning("No job id provided for stats call")

    try:
        since = request.args.get("since")
    except:
        app.logger.warning("No time limit provided for stats call")


    try:
        results = lagopus_get_job_stats(jobid, since)
        app.logger.warning("backend result: {}".format(results))
        return jsonify(results)
    except:
        app.logger.warning("Couldn't get stats for job {}".format(jobid))
        return jsonify([])


@app.route("/api/jobs")
def lagopus_api_get_jobs():
    jobid = None
    try:
        jobid = request.args.get("job")
    except:
        app.logger.info("No job specified")
    jobs = lagopus_get_job(jobid)
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
    pagename = "Dashboard"
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

    cores = int(request.form.get("cores", CONFIG["jobs"]["cores"]))
    memory = int(request.form.get("memory", CONFIG["jobs"]["memory"]))
    deadline = int(request.form.get("deadline", CONFIG["jobs"]["deadline"]))

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
    jobid = None
    try:
        jobid = request.args.get("job")
    except:
        app.logger.info("No job specified")
    return render_template(
        "jobs.html",
        pagename=pagename,
        defaultdeadline=CONFIG["jobs"]["deadline"],
        defaultmemory=CONFIG["jobs"]["memory"],
        defaultcores=CONFIG["jobs"]["cores"],
        jobid=jobid,
    )


@app.route("/crashes.html")
def crashes():
    pagename = "Crashes"
    return render_template("crashes.html", pagename=pagename)


@app.route("/corpuses.html")
def corpuses():
    pagename = "Corpuses"
    return render_template("corpuses.html", pagename=pagename)


@app.route("/404.html")
def fourohfour():
    pagename = "404"
    return render_template("404.html", pagename=pagename)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return send_from_directory("templates/", path)
