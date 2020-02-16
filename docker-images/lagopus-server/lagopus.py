#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

import os

from flask import Flask, Blueprint
from flask import render_template
from flask import send_from_directory
from flask import send_file
from flask import request
from flask import flash
from flask import redirect, url_for
from flask import jsonify
from flask_restx import Resource, Api, reqparse
from werkzeug import FileStorage
from werkzeug.utils import secure_filename

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError

app = Flask(__name__)
blueprint = Blueprint("api", __name__, url_prefix="/api")
api = Api(blueprint)
app.register_blueprint(blueprint)

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
    for v in CONFIG["dirs"].values():
        if not os.path.exists(v):
            app.logger.error("Creating '{}'".format(v))
            pathlib.Path(v).mkdir(parents=True, exist_ok=True)


def lagopus_job_id(name, driver, time):
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
    return "{}.{}.{}".format(name, driver.lower(), time.strftime("%Y-%m-%d-%H-%M-%S"))


def lagopus_get_kubeapis():
    # load api
    config.load_incluster_config()
    corev1 = client.CoreV1Api()
    batchv1 = client.BatchV1Api()
    return {"corev1": corev1, "batchv1": batchv1}


apis = lagopus_get_kubeapis()


def lagopus_k8s_create_job(
    job_id, driver, target, cpus, memory, deadline, namespace="default"
):
    """
    Add a new job.
    """
    lagopus_sanitycheck()

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("./k8s/"))

    # create job
    job = env.get_template("job.yaml")
    jobdir = CONFIG["dirs"]["jobs"] + "/" + job_id
    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)
    st = os.stat(jobdir)
    os.chmod(jobdir, st.st_mode | stat.S_IWOTH | stat.S_IXOTH | stat.S_IROTH)
    app.logger.error("Job directory: {}".format(jobdir))
    jobconf = {}
    jobconf["jobname"] = job_id
    jobconf["jobid"] = job_id
    jobconf["cpu"] = str(cpus)
    jobconf["memory"] = "{}Mi".format(memory)
    jobconf["deadline"] = deadline
    jobconf["driver"] = driver
    jobconf["namespace"] = namespace
    jobconf["jobpath"] = "jobs/" + job_id
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


def lagopus_k8s_get_jobs(job_id=None, namespace="default"):
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


def lagopus_k8s_get_nodes():
    nodes = []
    for node in apis["corev1"].list_node().items:
        onenode = {
            "name": node.metadata.name,
            "phase": node.status.phase,
            "allocatable": node.status.allocatable,
            # FIXME: should be mapped to native python types
            "conditions": node.status.conditions,
        }
        nodes.append(onenode)

    app.logger.warning("Nodes: {}".format(nodes))
    return nodes


# ---
# Backend
# ---
import mysql.connector
from zipfile import ZipFile

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
    except mysql.connector.Error:
        cnx = lagopus_db_connect()

    return cnx.cursor(**kwargs)


cnx = lagopus_db_connect()

if not cnx:
    # gunicorn will restart us until we successfully connect to the database
    exit(1)


class LagopusNode(object):
    def get(self):
        return lagopus_k8s_get_nodes()


class LagopusCrash(object):
    def get(self, job_id=None):
        cursor = lagopus_db_cursor(dictionary=True)

        query = "SELECT * FROM crashes"
        # FIXME: sqli
        query += " WHERE job_id = {}".format(job_id) if job_id else ""

        cursor.execute(query)

        result = cursor.fetchall()
        app.logger.error("Result: {}".format(result))
        return result

    def get_sample(self, job_id, sample_name):
        jobdir = CONFIG["dirs"]["jobs"] + "/" + job_id
        jobresult_file = jobdir + "/jobresults.zip"
        if not os.path.exists(jobresult_file):
            app.logger.warning("No file '{}'".format(jobresult_file))
            return None

        zf = ZipFile(jobresult_file)
        app.logger.warning(
            "Looking for '{}' in '{}'".format(sample_name, jobresult_file)
        )
        samples = list(filter(lambda x: sample_name in x, zf.namelist()))
        if not samples:
            app.logger.warning("Sample '{}' not found")
            return None

        # FIXME: this is crap
        extractpath = "/tmp/" + sample_name
        extractpath = zf.extract(samples[0], extractpath)

        return extractpath


class LagopusJob(object):
    def __init__(self):
        pass

    def get(self, job_id=None):
        cursor = lagopus_db_cursor(dictionary=True)

        # update db from k8s
        # ...job status, etc
        k8s_jobs = lagopus_k8s_get_jobs(job_id)

        # Set all incomplete job statuses to "Unknown"
        cursor.execute(
            "UPDATE jobs SET status = %(status)s WHERE status <> 'Complete'",
            {"status": "Unknown"},
        )
        # Update with statuses from k8s
        for job in k8s_jobs:
            app.logger.warning(job)
            cursor.execute(
                "UPDATE jobs SET status = %(status)s WHERE job_id = %(job_id)s",
                {"status": job["status"], "job_id": job["name"]},
            )

        # fetch from db
        cursor = lagopus_db_cursor(dictionary=True)
        if job_id:
            cursor.execute(
                "SELECT * FROM jobs WHERE job_id = %(job_id)s", {"job_id": job_id}
            )
        else:
            cursor.execute("SELECT * FROM jobs")
        result = cursor.fetchall()
        app.logger.error("Result: {}".format(result))

        return result

    def create(self, job_id, name, driver, file, deadline, cpus, memory):
        # generate unique job id
        now = datetime.datetime.now()
        job_id = lagopus_job_id(name, driver, now)

        status = "Created"
        create_timestamp = now.strftime("%Y-%m-%d %H-%M-%S")

        # insert new job into db
        cursor = lagopus_db_cursor()
        cursor.execute(
            "INSERT INTO jobs (job_id, status, driver, target, cores, memory, deadline, create_time) VALUES ('{}', '{}', '{}', '{}', {}, {}, {}, '{}')".format(
                job_id, status, driver, file, cpus, memory, deadline, create_timestamp
            )
        )
        cursor.close()

        # create in k8s
        lagopus_k8s_create_job(job_id, driver, file, cpus, memory, deadline)

    def delete(self, job_id):
        pass

    # --

    def get_stats(self, job_id, since):
        ic = InfluxDBClient(database="lagopus")
        app.logger.error(">>> Since: {}".format(since))

        query = "select MEAN(*) from jobs"
        query += " where job_id = '{}'".format(job_id) if job_id else ""
        query += " AND time > '{}'".format(since) if since else ""
        # TODO: revisit this; this is a bit of a hack. Without downsampling
        # like this, 10 hours or so the amount of metrics data will be in the
        # mb range.  The web UI especially doesn't like this, and it gets
        # extremely slow when we plot several mb of data in the monitoring
        # graphs. 1 minute seems like a happy medium; still decent resolution,
        # but low enough that the data size isn't huge after a few days. Should
        # be revisited as I'm sure someone will eventually have a use case for
        # higher res data.
        #
        # Also because of the MEAN(), Influx changes all the field names to
        # prefix with 'mean_', bit annoying -.-
        query += " GROUP BY time(1m) fill(none)"

        app.logger.warning("influx query: {}".format(query))

        try:
            data = ic.query(query)
            app.logger.warning("InfluxDB result: {}".format(data))
            results = list(data)[0] if list(data) else []
        except InfluxDBClientError as e:
            app.logger.error("InfluxDB error: {}".format(e))
            return []

        return results


LagopusJob = LagopusJob()
LagopusCrash = LagopusCrash()
LagopusNode = LagopusNode()

# Web


@app.after_request
def apply_caching(response):
    """
    Sometimes firefox doesn't allow inline scripts? What's up with that?
    """
    response.headers["Content-Security-Policy"] = "script-src 'unsafe-inline' 'self'"
    return response


## API

app.config["UPLOAD_FOLDER"] = "/tmp/"
app.config["SECRET_KEY"] = "389afsd89j34fasd"


@api.route("/nodes")
class Node(Resource):
    def get(self):
        return LagopusNode.get()


@api.route("/jobs")
class JobList(Resource):
    def get(self):
        jobs = LagopusJob.get()
        jobs = jobs if jobs else []
        return jsonify(jobs)

    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "file",
            type=FileStorage,
            location=app.config["UPLOAD_FOLDER"],
            help="Job zip file",
            required=True,
        )
        parser.add_argument("name", type=str, help="Job name", required=True)
        parser.add_argument("driver", type=str, help="Fuzzing driver", required=True)
        parser.add_argument(
            "cpus", type=int, help="Number of CPUs", default=CONFIG["jobs"]["cores"]
        )
        parser.add_argument(
            "memory",
            type=int,
            help="Memory requirement, in Mi",
            default=CONFIG["jobs"]["memory"],
        )
        parser.add_argument(
            "deadline",
            type=int,
            help="Fuzzing runtime, in s",
            default=CONFIG["jobs"]["deadline"],
        )
        args = parser.parse_args()
        return LagopusJob.create(**args), 201


@api.route("/jobs/<string:job_id>")
class Job(Resource):
    def get(self, job_id):
        job = LagopusJob.get(job_id)
        return jsonify(job) if job else 404


@api.route("/jobs/<string:job_id>/stats")
class JobStats(Resource):
    def get(self, job_id):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "since",
            type=str,
            help="Time to fetch stats since, as ISO 8601 timestamp",
            default=None,
        )
        args = parser.parse_args()
        results = LagopusJob.get_stats(job_id, args["since"])
        app.logger.warning("backend result: {}".format(results))
        return jsonify(results)


@api.route("/crashes")
class CrashList(Resource):
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "job_id",
            type=str,
            help="Return crashes found by a specific job",
            default=None,
        )
        args = parser.parse_args()
        crashes = LagopusCrash.get(*args)
        crashes = crashes if crashes else []
        return jsonify(crashes)


@api.route("/crash_sample/<string:job_id>/<string:sample_name>")
class CrashSample(Resource):
    def get(self, job_id, sample_name):
        return send_file(
            LagopusCrash.get_sample(job_id, sample_name), as_attachment=True
        )


# -------------
# Web interface
# -------------


@app.route("/")
@app.route("/index.html")
def index():
    pagename = "Dashboard"
    jobs = LagopusJob.get()
    jc = len(jobs) if jobs is not None else 0
    nodes = LagopusNode.get()
    nc = len(nodes) if nodes is not None else 0
    return render_template(
        "index.html",
        pagename=pagename,
        defaultdeadline=CONFIG["jobs"]["deadline"],
        defaultmemory=CONFIG["jobs"]["memory"],
        defaultcores=CONFIG["jobs"]["cores"],
        jobcount=jc,
        nodecount=nc,
    )


# @app.route("/upload", methods=["POST"])
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
    LagopusJob.create(
        jobname,
        driver,
        savepath,
        "nofile",
        cpus=cores,
        memory=memory,
        deadline=deadline,
    )
    return redirect(url_for("index"))


@app.route("/jobs.html")
def jobs():
    pagename = "Jobs"
    job_id = None
    try:
        job_id = request.args.get("job_id")
    except:
        app.logger.info("No job specified")
    return render_template("jobs.html", pagename=pagename, job_id=job_id)


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
