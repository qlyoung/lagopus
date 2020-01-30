#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

# ----
# Kubernetes stuff
# ----

#!/usr/bin/env python3
import os
import stat
import pathlib
import shutil
import subprocess
import datetime
import yaml
import jinja2

from kubernetes import client, config

# Global settings ------------------------
DIR_LAGOPUS = "/lagopus"  # state directory
SUBDIR_LAGOPUS_JOBS = "jobs"
DIR_LAGOPUS_JOBS = DIR_LAGOPUS + "/" + SUBDIR_LAGOPUS_JOBS  # state directory for jobs
lagoconfig = {"defaults": {"cores": 2, "memory": 200, "deadline": 240,}}
# ----------------------------------------


def lagopus_sanitycheck():
    """
    Check that:
    - all necessary directories exist
    """
    dirs = [DIR_LAGOPUS, DIR_LAGOPUS_JOBS]

    for d in dirs:
        if not os.path.exists(d):
            print("Creating '{}'".format(d))
            pathlib.Path(d).mkdir(parents=True, exist_ok=True)


def lagopus_jobid(name, driver):
    """
    Generate a unique job ID based on the job name.
    """
    now = datetime.datetime.now()
    return "{}-{}.{}".format(name, driver, now.strftime("%Y_%m_%d_%H_%M_%S"))


def lagopus_get_kubeapis():
    # load api
    config.load_incluster_config()
    corev1 = client.CoreV1Api()
    batchv1 = client.BatchV1Api()
    return {"corev1": corev1, "batchv1": batchv1}


apis = lagopus_get_kubeapis()


def lagopus_k8s_create_job(
    name, driver, target, cores=2, memory=200, deadline=240, namespace="default"
):
    """
    Add a new job.
    """
    lagopus_sanitycheck()

    jobid = lagopus_jobid(name, driver)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("./k8s/"))

    # create job
    job = env.get_template("job.yaml")
    jobdir = DIR_LAGOPUS_JOBS + "/" + jobid
    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)
    st = os.stat(jobdir)
    os.chmod(jobdir, st.st_mode | stat.S_IWOTH | stat.S_IXOTH | stat.S_IROTH)
    print("Job directory: {}".format(jobdir))
    jobconf = {}
    jobconf["jobname"] = name
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

    try:
        response = apis["batchv1"].create_namespaced_job(
            jobyaml["metadata"]["namespace"], jobyaml, pretty=True
        )
    except ApiException as e:
        print("API exception: {}".format(e))
    finally:
        print("API response:\n{}".format(response))


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
        # print("\tPods:")
        #     print("\t- {}\t[{}]".format(pod.metadata.name, pod.status.phase))
        jobs.append(onejob)
    return {"data": jobs}


# ---
# Web
# ---
from flask import Flask
from flask import render_template
from flask import send_from_directory
from flask import request
from flask import flash
from flask import redirect, url_for
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)

# --------
# JSON API
# --------
@app.route("/api/createjob")
def lagopus_api_create_job():
    return lagopus_k8s_create_job()


@app.route("/api/jobs")
def lagopus_api_get_jobs():
    return lagopus_k8s_get_jobs()


# -------------
# Web interface
# -------------
app.config["UPLOAD_FOLDER"] = "/tmp/"
app.config["SECRET_KEY"] = "389afsd89j34fasd"


@app.route("/")
@app.route("/index.html")
def index():
    pagename = "Home"
    return render_template(
        "index.html", pagename=pagename, jobcount=len(lagopus_api_get_jobs())
    )


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
    lagopus_k8s_create_job(
        jobname,
        driver,
        savepath,
        cores=cores,
        memory=memory,
        deadline=deadline,
        namespace="default",
    )
    return redirect(url_for("jobs", filename=filename))


@app.route("/jobs.html")
def jobs():
    pagename = "Jobs"
    return render_template(
        "jobs.html",
        pagename=pagename,
        defaultdeadline=lagoconfig["defaults"]["deadline"],
        defaultmemory=lagoconfig["defaults"]["memory"],
        defaultcores=lagoconfig["defaults"]["cores"],
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
