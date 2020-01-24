#!/usr/bin/env python3
import os
import pathlib
import shutil
import subprocess
import datetime

import click
import jinja2

from kubernetes import client, config
from kubernetes.client import Configuration


# Global settings ------------------------
DIR_LAGOPUS="/opt/lagopus"
DIR_LAGOPUS_JOBS=DIR_LAGOPUS + "/jobs"
# ----------------------------------------

# load api
configuration = Configuration()
Configuration.set_default(configuration)
batchv1 = client.BatchV1Api(client.ApiClient(configuration))
corev1 = client.CoreV1Api(client.ApiClient(configuration))

def lagopus_sanitycheck():
    """
    Check that:
    - all necessary directories exist
    - kubernetes is healthy
    """
    dirs = [DIR_LAGOPUS, DIR_LAGOPUS_JOBS]

    for d in dirs:
        if not os.path.exists(d):
            print("Creating '{}'".format(d))
            pathlib.Path(d).mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(["microk8s.status"], timeout=10, check=True, stdout=subprocess.DEVNULL)
    except CalledProcessError:
        print("Kubernetes seems unhealthy, check microk8s.status")
        exit(1)
    except TimeoutExpired:
        print("microk8s.status timed out, check cluster health")
        exit(1)

def lagopus_jobid(name, driver):
    """
    Generate a unique job ID based on the job name.
    """
    now = datetime.datetime.now()
    return "{}-{}.{}".format(name, driver, now.strftime("%Y_%m_%d_%H_%M_%S"))

@click.group()
def cli():
    pass

@cli.command()
@click.argument("name")
@click.argument("driver")
@click.argument("target", required=True,
    type=click.Path(
        exists=True, dir_okay=False, writable=False, readable=True, allow_dash=False
    ))
@click.option("--cores", default=2)
@click.option("--memory", default=200)
@click.option("--deadline", default=240)
def addjob(name, driver, target, cores, memory, deadline):
    """
    Add a new job.
    """
    lagopus_sanitycheck()

    jobid = lagopus_jobid(name, driver)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("./templates"))

    # setup persistent volume
    pv = env.get_template("pv.yaml.j2")
    opath = "/tmp/pv-{}.yaml".format(jobid)
    with open(opath, "w") as pvgen:
        pvgen.write(pv.render(path=DIR_LAGOPUS_JOBS))
    subprocess.run(["microk8s.kubectl", "apply", "-f", opath])

    # create persistent volume claim
    pvc = env.get_template("pvc.yaml.j2")
    opath = "/tmp/pvc-{}.yaml".format(jobid)
    with open(opath, "w") as pvgen:
        pvgen.write(pvc.render())
    subprocess.run(["microk8s.kubectl", "apply", "-f", opath])

    # create job
    job = env.get_template("job.yaml.j2")
    jobconf = {}
    jobconf["jobname"] = name
    jobconf["jobid"] = jobid
    jobconf["cpu"] = str(cores)
    jobconf["memory"] = "{}Mi".format(memory)
    jobconf["deadline"] = deadline
    jobconf["driver"] = driver
    jobdir = DIR_LAGOPUS_JOBS + "/" + jobid
    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)
    shutil.copy(target, "{}/target.zip".format(jobdir))
    with open(jobdir + "/job.yaml", "w") as genjob:
        rj = job.render(**jobconf)
        genjob.write(job.render(**jobconf))
    subprocess.run(["microk8s.kubectl", "apply", "-f", jobdir + "/job.yaml"])

if __name__ == "__main__":
    cli()
    exit()
