#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

import os
import base64
import tempfile

from flask import Flask, Blueprint
from flask import render_template
from flask import send_from_directory
from flask import send_file
from flask import request
from flask import flash
from flask import redirect, url_for
from flask import jsonify
from flask_restx import Resource, Api, Model, reqparse, fields, errors
from werkzeug.utils import secure_filename
from requests.exceptions import ConnectionError

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
    "jobs": {"cpus": 2, "memory": 200, "deadline": 240,},
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
            app.logger.info("Creating directory '{}'".format(v))
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
    app.logger.info("Lagopus job directory: {}".format(jobdir))
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
        app.logger.error("k8s API exception: {}".format(e))
    finally:
        app.logger.error("k8s API response:\n{}".format(response))

    return response


def lagopus_k8s_get_jobs(job_id=None, namespace="default"):
    jobs = []
    for job in apis["batchv1"].list_namespaced_job(namespace).items:
        onejob = {}
        fzctr = job.spec.template.spec.containers[0]
        onejob["name"] = job.metadata.name
        onejob["cpus"] = fzctr.resources.requests["cpu"]
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

    app.logger.info("k8s Nodes: {}".format(nodes))
    return nodes


def lagopus_k8s_kill_job(job_id, namespace="default"):
    # FIXME: should wrap this away from k8s
    # delete job and all related resources (propagation_policy="Background")
    try:
        response = apis["batchv1"].delete_namespaced_job(
            job_id, namespace, propagation_policy="Background"
        )
        app.logger.warning(response)
    except ApiException as e:
        app.logger.error("k8s API exception:")
        app.logger.exception(e)
        return False

    return True


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
        app.logger.info("Initialized database.")
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
        app.logger.error("Querying for crashes with job_id = '{}'".format(job_id))
        query = "SELECT * FROM crashes WHERE job_id LIKE %(job_id)s"
        job_id = job_id if job_id else "%"
        cursor.execute(query, {"job_id": job_id})
        result = cursor.fetchall()
        return result

    def get_sample(self, job_id, sample_name):
        jobdir = CONFIG["dirs"]["jobs"] + "/" + job_id
        jobresult_file = jobdir + "/jobresults.zip"
        if not os.path.exists(jobresult_file):
            app.logger.warning(
                "Job '{}': No job results file '{}'".format(job_id, jobresult_file)
            )
            return None

        zf = ZipFile(jobresult_file)
        samples = list(filter(lambda x: sample_name in x, zf.namelist()))
        if not samples:
            app.logger.warning(
                "Job '{}': Sample '{}' not found".format(job_id, sample_name)
            )
            return None

        # FIXME: this is crap
        extractpath = "/tmp/" + sample_name
        extractpath = zf.extract(samples[0], extractpath)

        return extractpath


class LagopusJob(object):
    """
    Singleton class that provides getters and setters for jobs.

    This is not a model for a job itself.
    """

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

        if job_id and result:
            return result[0]
        else:
            return result

    def create(self, job_name, driver, target, deadline, cpus, memory):
        # generate unique job id
        now = datetime.datetime.now()
        job_id = lagopus_job_id(job_name, driver, now)

        status = "Created"
        create_timestamp = now.strftime("%Y-%m-%d %H-%M-%S")

        filename = secure_filename(job_id + ".zip")
        savepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        with open(savepath, "wb") as tgt:
            tgt.write(base64.b64decode(target))

        # insert new job into db
        cursor = lagopus_db_cursor()
        cursor.execute(
            "INSERT INTO jobs (job_id, status, driver, target, cpus, memory, deadline, create_time) VALUES ('{}', '{}', '{}', '{}', {}, {}, {}, '{}')".format(
                job_id,
                status,
                driver,
                savepath,
                cpus,
                memory,
                deadline,
                create_timestamp,
            )
        )
        cursor.close()

        # create in k8s
        lagopus_k8s_create_job(job_id, driver, savepath, cpus, memory, deadline)

        return self.get(job_id)

    def kill(self, job_id):
        job = lagopus_k8s_get_jobs(job_id)
        if not job:
            app.logger.warning("Job not found ({})".format(job_id))
            raise Exception("Job not found")
        return lagopus_k8s_kill_job(job_id)

    def delete(self, job_id):
        response = self.kill(job_id)
        # TODO: delete job from db
        return response

    # --

    def get_stats(self, job_id, since):
        ic = InfluxDBClient(database="lagopus")

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

        app.logger.info("Executing InfluxDB query: {}".format(query))

        try:
            data = ic.query(query)
            app.logger.info("InfluxDB result: {}".format(data))
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

app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
app.config["SECRET_KEY"] = "389afsd89j34fasd"


@api.route("/nodes")
class Node(Resource):
    def get(self):
        return LagopusNode.get()


job_base_model = Model(
    "Job",
    {
        "driver": fields.String(
            description="The fuzzing driver", enum=["afl", "libFuzzer"], required=True
        ),
        "cpus": fields.Integer(
            description="Number of CPUs the job should use", required=True
        ),
        "memory": fields.Integer(
            description="Memory limit for the job, in Mi", required=True
        ),
        "deadline": fields.Integer(
            description="Maximum runtime of fuzzing step", required=True
        ),
    },
)

job_request_model = api.clone(
    "JobRequest",
    job_base_model,
    {
        "job_name": fields.String(description="Name for job", required=True),
        "target": fields.String(
            description="Base64 encoded zip archive containing target binary and corpus",
            required=True,
        ),
    },
)
job_response_model = api.clone(
    "JobResponse",
    job_base_model,
    {
        "job_id": fields.String(description="Unique ID for job", required=True),
        "create_time": fields.DateTime(
            description="Internal job creation timestamp", required=True
        ),
        "status": fields.String(
            description="Current status of job",
            enum=["Complete", "Incomplete", "Unknown"],
            required=True,
        ),
    },
)


@api.route("/jobs")
class JobList(Resource):
    @api.marshal_list_with(job_response_model)
    def get(self):
        jobs = LagopusJob.get()
        return jobs if jobs else []

    @api.expect(job_request_model, validate=True)
    @api.marshal_with(job_response_model, code=201)
    def post(self):
        job = LagopusJob.create(**api.payload)
        app.logger.info("Created job {}".format(job))
        return job


@api.route("/jobs/<string:job_id>")
@api.doc(params={"job_id": "Job to retrieve"})
class Job(Resource):
    @api.marshal_with(job_response_model)
    def get(self, job_id):
        return LagopusJob.get(job_id)


job_control_request_model = api.model(
    "JobControlRequest",
    {
        "action": fields.String(
            description="Action to perform", enum=["kill"], required=True
        ),
    },
)
job_control_response_model = api.model(
    "JobControlResponse",
    {
        "job_id": fields.String(description="Unique ID for job", required=True),
        "status": fields.String(
            description="Operation status", enum=["error", "success"], required=True
        ),
        "info": fields.String(description="Extra information about the operation"),
    },
)


@api.route("/jobs/<string:job_id>/control")
@api.doc(params={"job_id": "Job to effect action on"})
class JobControl(Resource):
    @api.expect(job_control_request_model, validate=True)
    @api.marshal_with(job_control_response_model)
    @api.doc(
        responses={
            404: "No such job",
            500: "Failed to complete action",
            400: "Unknown action",
        }
    )
    def post(self, job_id):
        job = LagopusJob.get(job_id)

        response = {
            "job_id": job_id,
            "status": "",
        }
        if not job:
            errors.abort(code=404, message="No such job {}".format(job_id))

        if api.payload["action"] == "kill":
            try:
                lr = LagopusJob.kill(job_id)
            except Exception as e:
                app.logger.exception(e)
                app.logger.warning("k8s kill failed for job {}".format(job_id))
                errors.abort(code=500, message="Failed to kill job {}".format(job_id))

            if lr:
                response["status"] = "success"
                response["info"] = "killed job"
                return response, 200
            else:
                app.logger.warning("k8s kill failed for job {}".format(job_id))
                errors.abort(code=500, message="Failed to kill job {}".format(job_id))

        errors.abort(code=400, message="Unknown action")


stats_response_model = api.model(
    "JobStatsResponse",
    {
        "alive": fields.Integer(
            description="Number of fuzzing processes running",
            required=True,
            attribute="mean_alive",
        ),
        "cpu_hours": fields.Float(
            description="Number of CPU hours consumed",
            required=True,
            attribute="mean_cpu_hours",
        ),
        "crashes": fields.Integer(
            description="Number of crashes triggered",
            required=True,
            attribute="mean_crashes",
        ),
        "current_path": fields.Integer(
            description="For AFL, the current path depth",
            required=True,
            attribute="mean_current_path",
        ),
        "execs": fields.Integer(
            description="Total execution count of target",
            required=True,
            attribute="mean_execs",
        ),
        "execs_per_sec": fields.Float(
            description="Number of target executions per second",
            required=True,
            attribute="mean_execs_per_sec",
        ),
        "hangs": fields.Integer(
            description="Number of hangs triggered",
            required=True,
            attribute="mean_hangs",
        ),
        "memory": fields.Float(
            description="Memory usage, in Mi", required=True, attribute="mean_memory"
        ),
        "pending": fields.Integer(
            description="For AFL, number of unexplored paths",
            required=True,
            attribute="mean_pending",
        ),
        "pending_fav": fields.Integer(
            description="For AFL, number of favored unexplored paths",
            required=True,
            attribute="mean_pending_fav",
        ),
        "total_paths": fields.Integer(
            description="Number of execution paths discovered",
            required=True,
            attribute="mean_total_paths",
        ),
        "time": fields.DateTime(description="Timestamp", required=True),
    },
)

parser_stats = reqparse.RequestParser()
parser_stats.add_argument(
    "since",
    type=str,
    help="Time to fetch stats since, as ISO 8601 timestamp",
    default=None,
)


@api.route("/jobs/<string:job_id>/stats")
@api.doc(params={"job_id": "Job to retrieve stats for"})
class JobStats(Resource):
    @api.expect(parser_stats, validate=True)
    @api.marshal_with(stats_response_model)
    @api.doc(responses={503: "Could not collect to stats database"})
    def get(self, job_id):
        try:
            args = parser_stats.parse_args()
            since = args["since"] if "since" in args else None
            app.logger.warning("Requesting since: {}".format(since))
            results = LagopusJob.get_stats(job_id, since)
        except ConnectionError as e:
            app.logger.warning("Could not connect to InfluxDB")
            errors.abort(code=503, message="Could not connect to InfluxDB")

        return results


crash_model = api.model(
    "Crash",
    {
        "job_id": fields.String(
            description="Job that this crash was found in", required=True
        ),
        "type": fields.String(
            description="Crash type; buffer overflow, use after free, etc.",
            required=True,
        ),
        "is_security_issue": fields.Boolean(
            description="Heuristic on whether this is likely to be a security issue"
        ),
        "is_crash": fields.Boolean(
            description="Whether this is a hard crash, versus a memory leak or hang"
        ),
        "sample_path": fields.String(
            description="Name of sample that triggers the crash", required=True
        ),
        "backtrace": fields.String(
            description="Program output upon crash", required=True
        ),
        "backtrace_hash": fields.String(
            description="Backtrace hash; used for deduplicating crashes"
        ),
        "return_code": fields.Integer(description="Program return code upon crash"),
        "create_time": fields.DateTime(description="Timestamp"),
    },
)

parser_crashes = reqparse.RequestParser()
parser_crashes.add_argument(
    "job_id",
    type=str,
    help="Return crashes found by a specific job",
    default=None,
    required=False,
)


@api.route("/crashes")
class CrashList(Resource):
    @api.expect(parser_crashes, validate=True)
    @api.marshal_list_with(crash_model)
    def get(self):
        args = parser_crashes.parse_args()
        crashes = LagopusCrash.get(**args)
        crashes = crashes if crashes else []
        return crashes


@api.route("/crashes/<string:job_id>/samples/<string:sample_name>")
@api.doc(
    params={"job_id": "Job to select sample from", "sample_name": "Name of sample"}
)
class CrashSample(Resource):
    @api.doc(responses={404: "Sample not found"})
    def get(self, job_id, sample_name):
        sample = LagopusCrash.get_sample(job_id, sample_name)
        if sample:
            return send_file(sample, as_attachment=True)
        else:
            errors.abort(code=404, message="Sample not found")


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
        defaultcpus=CONFIG["jobs"]["cpus"],
        jobcount=jc,
        nodecount=nc,
    )


@app.route("/jobs.html")
def jobs():
    pagename = "Jobs"
    job_id = request.args.get("job_id", default=None)
    job = LagopusJob.get(job_id) if job_id else None
    return render_template("jobs.html", pagename=pagename, job=job)


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
