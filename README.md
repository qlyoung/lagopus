<p align="center">
<img src="https://github.com/qlyoung/lagopus/blob/master/lagopus.svg" alt="Icon" width="20%"/>
</p>

# lagopus

Distributed fuzzing for the rest of us.

https://docs.lagopus.io/


## About

*Note*: This is early access software with no production-ready releases yet.
It works, but theres's a lot left to do to make it easy to use.

Lagopus is a distributed fuzzing application built on top of Kubernetes. It
allows you to fuzz arbitrary targets using clustered compute resources. You
specify the target binary, fuzzing driver (`afl` or `libFuzzer`), corpus, and
job parameters such as #CPUs, memory and TTL. Lagopus then creates a container
to for the fuzzing job and runs it on an available node.

Lagopus also takes much of the manual work out of analyzing fuzzing results.
When a fuzzing run finishes, Lagopus collects any crashing inputs and their
stack traces and analyses them for type and severity. Results are collated,
deduplicated and stored in a database. The generated corpus is cleaned and
minimized. All results are deposited in your NFS share for later use.

Lagopus has a web interface for creating jobs, monitoring progress and fuzzing
statistics, and viewing crash analyses. This interface is built on top of an
HTTP API which can be used directly for integration with external tools such as
CI/CD systems and test suites.

Lagopus runs on Kubernetes, so it runs as well in on-prem, bare metal
deployments as it does on your choice of k8s cloud providers.

## Installation & Usage

See the docs for:

- [Installation](http://docs.lagopus.io/en/latest/installing.html)
- [Usage](http://docs.lagopus.io/en/latest/usage.html)

## FAQ

- Q: Why not ClusterFuzz?

  A: ClusterFuzz is tightly integrated with Google Cloud. While bots can be
     deployed locally with some effort, the application itself runs on App
     Engine, requires Firebase for authentication, only supports Google for
     user authentication, and is quite difficult to deploy. Perhaps the most
     annoying thing is that ClusterFuzz has a hard dependency on Google Cloud
     Storage for fuzzing results. Because of the amount of corpus data
     generated by fuzzers, and the long term size of uploaded target binaries,
     this can get expensive. App Engine is also an unavoidable fixed cost.
     Finally, even if a cloud budget is available, CF still locks you into
     Gcloud.

     ClusterFuzz is primarily designed for Google's scale and use cases. Google
     uses ClusterFuzz to fuzz V8, Fuschia and Android, so much of the codebase
     has customizations for these targets. It's also designed as a massively
     scalable system - Google claims their internal instance is sized at 25,000
     nodes. Depending on who you are, these design choices could be a pro or
     con. I personally wanted something lighter, with first class support for
     on prem deployments as well as non-Google clouds, and a smaller, more
     hackable codebase.

     Please note that none of this should be taken as criticism directed at
     Google, ClusterFuzz, or any of the people working on ClusterFuzz.
     ClusterFuzz is obviously super awesome for the scale and workloads it is
     designed for, and if you have the cloud budget and scaling requirements,
     it's your best option. Lagopus is for the rest of us :)

- Q: Why just AFL and libFuzzer?

  A: I am most familiar with those tools. More fuzzers can be added with time.

- Q: Why Kubernetes?

  A: Kubernetes is, to my knowledge, the only clustered orchestration tool that
     supports certain features necessary for high performance fuzzing jobs,
     such as static CPU resources, privileged containers, and distributed
     storage. Also, my existing workloads were already running in Docker. And I
     wanted to learn Kubernetes.

- Q: Why [lagopus](https://en.wikipedia.org/wiki/Arctic_fox)?

  A: Cuz they're awesome ^_^

- Q: My target is dynamically linked and the fuzzer image doesn't have its
     shared libraries; what do?

  A: I've had good success with [ermine](http://magicermine.com/index.html).
     Statifier will likely not work due to ASLR. In the future I would like to
     provide support for image customizations, or custom images.


## Prior Art

Other projects in the same vein.

- The venerable [ClusterFuzz](https://github.com/google/ClusterFuzz), parts of
  which are used in Lagopus
- [LuckyCat](https://github.com/fkie-cad/LuckyCAT) (greetz!)


## Limitations

This is also a todo list.

Lagopus cannot distribute multithreaded / multiprocess jobs across nodes.
Distribution is at the job level. This means a small cluster where each node
has a high CPU count is preferable to a large cluster of smaller nodes.

Lagopus does not (yet) offer corpus minimization. You must maintain your corpi.

Lagopus depends on the existence of an NFS share external to itself to store
job data.

Lagopus runs on Kubernetes.

## Prerequisites

You should have a k8s cluster, ideally on bare metal, or vms with static CPU
resources.

You should have at least 1 node with at least 4 real CPUs (not hyperthreads /
smt). More CPUs are better. More nodes are better.

You should understand how AFL and libFuzzer operate and the differences between
them.

You should be aware that fuzzers thrash disk and consume massive amounts of
CPU, and plan accordingly. See AFL docs for more info.

You should understand how rss limits work with ASAN on x86-64, and how
libFuzzer and AFL handle those.

You should install the absolute latest stable version of k8s. This project uses
advanced features of k8s for performance reasons, many of which are only
available in k8s >= v1.17.

It's a good idea to have an operational understanding of Kubernetes.
Specifically, you will have an easier time with debugging cluster setup if you
understand how k8s handles:

- `sysctl`s
- CPU management policies (`none` and `static`)
- CPU affinity & resources
- Container QOS policies (`Guaranteed`, `BestEffort`, etc)


## Todo

- ~~Backtrace collection~~ :heavy_check_mark:
- ~~Job monitoring~~ :heavy_check_mark:
- ~~Job input validation~~ :heavy_check_mark:
- Source coverage analysis
- Better deployment process
- Job tags
- CLI client
- Corpus management
- Docker-compose support
- Reduce k8s tendrils
- Reduce vendored code
- Python support
- More fuzzers
- Performance audit
- Security (always last :-)

## Dev Notes

Miscellaneous bits of information that may be relevant in the future, or for
debugging.

- `gdb` will not work in a container without `seccomp=unconfined`; this is the
  default in k8s, so it's not explicitly set anywhere in Lagopus, but when
  running the fuzzer container manually make sure to pass
  `--security-opt seccomp=unconfined` or you won't get the detailed analysis of
  crashes usually provided by
  [exploitable](https://github.com/jfoote/exploitable).

- Lagopus was using gdb exploitable ^ to analyze crashes, but exploitable is
  currently turned off because its heuristics see ASAN terminations as clean
  exits. Currently the crash analysis code is lifted from ClusterFuzz, as it
  already has all the gritty regex's and classifiers sorted out.

- `afl` requires sysctl `kernel.core_pattern=core` to get core files. k8s has
  support for allowing nodes to allow pods to set sysctls (pods also have
  settings to allow that at the pod level) which results in a taint on the node
  and therefore requires tolerances on the pod.  However, k8s only supports
  namespaced sysctls; `kernel.core_pattern` isn't one, and thus must be
  manually set on the node entirely outside of k8s before starting the kubelet.

- Fuzzer jobs should run with dedicated cores, for a couple reasons. The first
  is that this is just better for performance regardless of the particular
  fuzzer in use. The second is more subtle, and applies to fuzzers that pin
  themselves to particular CPUs in order to increase cache locality and
  reduce kernel scheduler overhead. `afl` in particular does this. When
  starting up, `afl` searches for "free" (not already pinned by another
  process) CPU cores to bind itself to, which it determines by looking at
  `/proc`. However, `/proc` is not bind mounted into containers by default, so
  it's possible for another process, either on the host or another container, to
  be bound to a given CPU even though the container's `/proc` says the core is
  free. In this case the bind will still work but now you have two processes
  pinned to the same CPU on the host. This is far worse than not binding at
  all. So until container runtimes fix this (if they ever do), CPU assignments
  must be manually set on the container itself by the container runtime.

  This is a bit tricky to do in k8s. First the nodes must be configured with
  the `static` cpu policy by passing `--cpu-manager-policy=static` to kubelet.
  Second, the pod containers must be in the "Guaranteed" QOS class, which means
  both requests and limits for both memory and cpu must be set, and must equal
  each other. This will cause each container to have N CPUs assigned to it
  exclusively, which solves the issue with `/proc` by sidestepping it
  completely.

  However, again there is a caveat. A pecularity of container runtimes is that
  even when containers are assigned to specific CPUs, the containers still see
  all of the host CPUs and don't actually know which of them have been assigned
  to it. This again poses some complications with `afl`'s CPU pinning
  mechanism.  `afl`'s current (upstream) CPU selection heuristics will usually
  fail when run in a container because it tries to bind to the first available
  CPU (as per `/proc`), typically CPU 0, which may or may not be assigned to
  the container. If not, the system call to perform the bind -
  `sched_setaffinity` - will fail and `afl` will bail out.  This is solved for
  Lagopus by packaging a patched `afl` that tries *all* cores until it finds
  one that binding succeeds on. I have an open PR[0] against `afl` for this
  patch, so hopefully at some point Lagopus can go back to using upstream
  `afl`. However, Google doesn't seem to be paying much attention to the
  repository, so who knows how long that will take.

  [0] https://github.com/google/AFL/pull/68

- It would be nice to use
  [halfempty](https://github.com/googleprojectzero/halfempty) for minimization
  instead of the current tools, as it's much faster. This can probably be done
  fairly easily.

- Corpus minimization probably shouldn't be subject to the same resource
  constraints as fuzzing itself, because it takes so long. However, doing this
  would introduce a lot of complications; multiple stages of pods (hard to do
  with k8s Jobs), resource availability no longer corresponds directly to the
  jobs the user scheduled...definitely should evaluate halfempty first to see
  if it speeds things up enough on e.g. 2 core jobs to make this a non issue.

- Jobs could be distributed across nodes by using the NFS share as a source for
  new corpus inputs and periodically synchronizing?

- Collecting `perf stat` output for fuzzing tasks into InfluxDB could be cool.
  However, perf inside containers is still a pita, for the same reasons that
  make procfs a pain. Brendan Gregg touched on this in his container perf talk,
  https://www.youtube.com/watch?v=bK9A5ODIgac @ 33m.
