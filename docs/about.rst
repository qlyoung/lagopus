.. _about:

*****
About
*****

Lagopus is a distributed fuzzing platform. It allows you to run multiple
fuzzing jobs across multiple machines.

Lagopus handles all lifecycle management for fuzzing workloads, including
creating, distributing, running, and monitoring fuzzing jobs. It automatically
analyzes crashes, minimizes test cases, and manages corpuses. It supports
`libFuzzer <https://llvm.org/docs/LibFuzzer.html>`_ and `AFLplusplus
<https://github.com/AFLplusplus/AFLplusplus>`_ out of the box, but can be made
to support any fuzzing driver or framework.

Lagopus intends to be an alternative to ClusterFuzz with a focus on a more
modular codebase, better hackability and first class support for on-prem
clusters and single-node deployments.

.. see-also:: :ref:`installation`

Architecture
------------

Lagopus is built on Kubernetes (k8s). The core application runs as a set of k8s
containers. Fuzzing jobs run in additional containers created by the core.
Kubernetes handles cluster and resource management, job distribution, container
lifecycle, and to some extent storage. Lagopus has four main components , each
corresponding to one container image. There is one instance of each image in
Lagopus deployment, except for fuzzing containers, which are created on demand
to run jobs.

The first is ``lagopus-server``. This is more or less the application core. It
is a Flask app that exposes a REST API used to interact with Lagopus. It talks
to the k8s API, primarily to spin up containers for running fuzzing jobs. It is
stateless; application state is stored in ``lagopus-db``.

The second is ``lagopus-db``, which is just a MySQL instance that provides the
application database. Details on jobs, crashes, corpuses, etc are all stored
there.

The third is ``lagopus-scanner``. When fuzzing jobs complete, they dump their
artifacts to the Lagopus shared storage area for later use; this container
periodically scans that directory looking for recently finished jobs and
imports their results into the database. This container is also stateless, and
just runs a Python script that does the importing.

The fourth is ``lagopus-fuzzer``. This is an Ubuntu 18.04 docker image
preloaded with a collection of fuzzing utilities. Each fuzzing job is run in a
new instance of this image. In the future, support for custom containers should
allow a choice of platforms.


Why Kubernetes
^^^^^^^^^^^^^^
Kubernetes was chosen not out of any particular desire to use microservices,
but because it provides both container management and a distributed systems
platform, both of which Lagopus needs. It was decided early on that Lagopus
should not try to roll its own versions of these two things. 

Unfortunately, k8s has something of a reputation for being very complex and
unwieldy, and to some extent this is true. It does much more than Lagopus needs
it to do. Fortunately the k8s setup required to run Lagopus is relatively
minimal;
a cluster, some sysctls on the nodes, and an nfs volume.

