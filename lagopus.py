#!/usr/bin/env python3
import click
import yaml

from kubernetes import client, config
from kubernetes.client import Configuration
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

base_fuzzjob_spec = {
    "apiVersion": "v1",
    "kind": "Job",
    "metadata": {"name": "fuzztest"},
    "spec": {
        "template": {
            "spec": {
                "containers": [
                    {
                        "image": "qlyoung/fuzzbox-frr",
                        "name": "fuzzer",
                        "args": ["/bin/sh", "-c", "while true;do date;sleep 5; done"],
                    }
                ]
            },
        },
    },
}


@click.group()
def cli():
    pass


@cli.command()
@click.argument("name")
@click.option("--cores", default=4)
@click.option(
    "--target",
    required=True,
    type=click.Path(
        exists=True, dir_okay=False, writable=False, readable=True, allow_dash=False
    ),
)
def addjob(name, target, cores):
    # create spec
    jobspec = dict(base_fuzzjob_spec)
    jobspec["metadata"]["name"] += "-" + name
    jobspec["spec"]["template"]["spec"]["containers"][0]["args"] = [target, cores]

    # render as yaml
    print(yaml.dump(jobspec))

    # load api
    config.load_kube_config()
    c = Configuration()
    c.assert_hostname = False
    Configuration.set_default(c)
    batchv1 = client.BatchV1Api()

    #job = client.V1Job(api_version=jobspec['apiVersion'], kind=jobspec['kind'], metadata=jobspec['metadata'], spec=jobspec['spec'])
    #print(job)

    #resp = batchv1.create_namespaced_job(job, jobspec)


if __name__ == "__main__":
    cli()
    exit()

    # Retrieve
