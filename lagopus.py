#!/usr/bin/env python3
import click
from ruamel import yaml
import time
import subprocess
import os
import pathlib
import shutil

from kubernetes import client, config
from kubernetes.client import Configuration

JOB_VOLUME_PATH="/opt/lagopusvolume"

# load api
configuration = Configuration()
Configuration.set_default(configuration)
batchv1 = client.BatchV1Api(client.ApiClient(configuration))
corev1 = client.CoreV1Api(client.ApiClient(configuration))

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
@click.option("--cores", default=4)
def addjob(name, driver, target, cores):
    # generate job ID
    jobid = "lagopus-job-{}".format(int(time.time()))

    # create persistent volume for jobs
    with open("pv.yaml") as pvfile:
        print("Creating persistent volume")
        pv = yaml.safe_load(pvfile)
        pv["spec"]["hostPath"]["path"] = JOB_VOLUME_PATH
        pathlib.Path(JOB_VOLUME_PATH).mkdir(parents=True, exist_ok=True)
        with open("pv-{}.yaml".format(jobid), "w") as pvgen:
            pvgen.write(yaml.dump(pv))
        subprocess.run(["microk8s.kubectl", "apply", "-f", "pv-{}.yaml".format(jobid)])
        # response = corev1.create_persistent_volume(body=pv)
        # print(response)

    # create persistent volume claim
    with open("pvc.yaml") as pvcfile:
        print("Creating persistent volume claim")
        pv = yaml.safe_load(pvcfile)
        subprocess.run(["microk8s.kubectl", "apply", "-f", "pvc.yaml"])
        #response = corev1.create_persistent_volume_claim(body=pvc)
        #print(response)

    # customize job with given parameters
    with open("job.yaml") as jobfile:
        job = yaml.safe_load(jobfile)
        job["metadata"]["name"] += "-" + name
        pod = job["spec"]["template"]
        pod["spec"]["containers"][0]["args"] = [str(driver), str(cores)]
        pod["spec"]["containers"][0]["env"].append({'name': 'LAGOPUS_JOB_ID', 'value': jobid})

    # create job directory
    jobdir = JOB_VOLUME_PATH + "/" + jobid

    pathlib.Path(jobdir).mkdir(parents=True, exist_ok=True)

    # copy job zip to job directory
    shutil.copy(target, "{}/target.zip".format(jobdir))
        
    with open("{}.yaml".format(jobid), "w") as genjob:
        genjob.write(yaml.dump(job))

    subprocess.run(["microk8s.kubectl", "apply", "-f", "{}.yaml".format(jobid)])

if __name__ == "__main__":
    cli()
    exit()

    # Retrieve
