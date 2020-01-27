#!/usr/bin/env python3
import os
import stat
import pathlib
import shutil
import subprocess
import datetime
import yaml

import click
import jinja2

from kubernetes import client, config


# Global settings ------------------------
DIR_LAGOPUS = "/opt/lagopus_storage"  # state directory
SUBDIR_LAGOPUS_JOBS = "jobs"
DIR_LAGOPUS_JOBS = DIR_LAGOPUS + "/" + SUBDIR_LAGOPUS_JOBS  # state directory for jobs
# ----------------------------------------


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
        subprocess.run(
            ["microk8s.status"], timeout=10, check=True, stdout=subprocess.DEVNULL
        )
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


def lagopus_get_kubeapis(confile="kube-config"):
    # load api
    config.load_kube_config(confile)
    corev1 = client.CoreV1Api()
    batchv1 = client.BatchV1Api()
    return {"corev1": corev1, "batchv1": batchv1}


@click.group()
def cli():
    pass


@cli.command()
@click.argument("name")
@click.argument("driver")
@click.argument(
    "target",
    required=True,
    type=click.Path(
        exists=True, dir_okay=False, writable=False, readable=True, allow_dash=False
    ),
)
@click.option("--cores", default=2)
@click.option("--memory", default=200)
@click.option("--deadline", default=240)
@click.option("--namespace", default="default")
def addjob(name, driver, target, cores, memory, deadline, namespace):
    """
    Add a new job.
    """
    lagopus_sanitycheck()

    jobid = lagopus_jobid(name, driver)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("./k8s/base/fuzzer/"))

    # create job
    job = env.get_template("job.yaml.j2")
    jobdir = DIR_LAGOPUS_JOBS + "/" + jobid
    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)
    os.chmod(jobdir, stat.S_IWOTH | stat.S_IXOTH | stat.S_IROTH)
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

    apis = lagopus_get_kubeapis()

    try:
        response = apis["batchv1"].create_namespaced_job(
            jobyaml["metadata"]["namespace"], jobyaml, pretty=True
        )
    except ApiException as e:
        print("API exception: {}".format(e))
    finally:
        print("API response:\n{}".format(response))


if __name__ == "__main__":
    cli()
    exit()
