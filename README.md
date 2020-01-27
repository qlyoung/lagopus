lagopus
-------

Distributed fuzzing for the rest of us.

About
-----
lagopus is a distributed fuzzing application build on top of Kubernetes. It
allows you to fuzz arbitrary targets using clustered compute resources. You
specify the target, fuzzing driver (`afl` or `libFuzzer`), corpus, and job
parameters such as #CPUs, memory and TTL. Lagopus then builds the job and hands
it to your k8s cluster. When the job completes, lagopus deposits the results in
your NFS share for further analysis.

lagopus accepts job definitions in a format very similar to
[ClusterFuzz](https://github.com/google/clusterfuzz). It wants a zip archive
with the following structure:

```
job.zip
├── corpus
├── target
└── target.conf
```

- `corpus` is a directory containing a fuzzing corpus
- `target` is your target binary (see `Targets`)
- `target.conf` is a config file for
  [afl-multicore](https://gitlab.com/rc0r/afl-utils); this is only necessary
  when the job type is `afl`, libfuzzer jobs do not use this

Philosophy
----------
- KISS
- F*** the cloud


FAQ
---
- Q: Why not ClusterFuzz?

  A: Google Cloud.

- Q: Why not LuckyCAT?

  A: [I couldn't get it to work for me.](https://github.com/fkie-cad/LuckyCAT/issues/3)

- Q: Why just AFL and libFuzzer?

  A: I am most familiar with those tools. More fuzzers can be added with time.

- Q: Why Kubernetes?

  A: Kubernetes is, to my knowledge, the only clustered orchestration tool that
     supports certain features necessary for high performance fuzzing jobs,
     such as static CPU resources, privileged containers, and distributed
     storage. Also, my existing workloads were already running in Docker. And I
     wanted to learn Kubernetes.

- Q: Why [lagopus](https://en.wikipedia.org/wiki/Arctic_fox)?

  A: Cuz they're fucking awesome

- Q: My target is dynamically linked and the fuzzer image doesn't have its
     shared libraries; what do?

  A: I've had good success with [ermine](http://magicermine.com/index.html).
     Statifier will likely not work due to ASLR.


Limitations
-----------
This is also a todo list.

lagopus cannot distribute multithreaded / multiprocess jobs across nodes.
Distribution is at the job level. This means a small cluster where each node
has a high CPU count is preferable to a large cluster of smaller nodes.

lagopus does not (yet) offer corpus minimization. You must maintain your corpi.

lagopus depends on the existence of an NFS share external to itself to store
job data.

lagopus runs on Kubernetes.

Prerequisites
-------------
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

Kubernetes cluster configuration
--------------------------------

* Recommended platform: Ubuntu 18.04
* Recommended k8s: [microk8s](https://microk8s.io/)

If you only have 1 node, `minikube` is acceptable, but `microk8s` is still a
better choice to eliminate KVM / Virtualbox overhead.

1. Install Kubernetes on your nodes
2. On your nodes, run the following:

   ```
   echo "kernel.core_pattern=core" >> /etc/sysctl.conf
   sysctl -p
   ```
   ```
   swapoff -a
   ```
   ```
   cd /sys/devices/system/cpu; echo performance | tee cpu*/cpufreq/scaling_governor
   ```

3. Set the following kubelet parameters on each of your nodes and restart
   kubelet:

   ```
   --cpu-manager-policy=static
   --kube-reserved="cpu=200m,memory=512Mi"
   ```

   * microk8s:

     Add the above lines to `/var/snap/microk8s/current/args/kubelet`, then:
     ```
     rm /var/snap/microk8s/common/var/lib/kubelet/cpu_manager_state
     systemctl reset-failed snap.microk8s.daemon-kubelet
     systemctl restart snap.microk8s.daemon-kubelet
     ```
     Check `journalctl -u snap.microk8s.daemon-kubelet` if the service fails
     for debugging logs.

4. Join your nodes to the cluster:

   * microk8s:

     Control plane:
     ```
     microk8s.add-node
     ```
     Node (run what the control plane gave you):

     ```
     microk8s.join <id>
     ```

5. Verify your cluster is configured on the control plane node, e.g.:
   ```
   root@minikube:~# microk8s.kubectl get no
   NAME         STATUS   ROLES    AGE     VERSION
   microk8s-1   Ready    <none>   38m     v1.17.0
   minikube     Ready    <none>   5d15h   v1.17.0
   ```
   All nodes should read `Ready`.

6. Deploy the test job and verify that it gets scheduled. It's a good idea to
   adjust `spec.parallelism` to force k8s to schedule onto nodes other than the
   control plane to make sure this works. The test job requires 4 cpus so
   increase parallelism to ceil(C/4)+1 where C is # cpus on your master node to
   ensure at least 1 other node gets scheduled.

   * microk8s:

     ```
     microk8s.kubectl apply -f job.yaml
     ```

     Verify that at least some pods have been scheduled:

     ```
     root@minikube:~# microk8s.kubectl get pod
     NAME             READY   STATUS    RESTARTS   AGE
     fuzztest-grb9t   0/2     Pending   0          29m
     fuzztest-kxswf   2/2     Running   0          29m
     fuzztest-lw8d8   0/2     Pending   0          29m
     fuzztest-nnzfn   2/2     Running   0          29m
     fuzztest-tqp96   2/2     Running   0          29m
     ```

     Verify that those pods are pegging CPUs. You can do this with
     `kubectl describe node <node>`, or by logging into the node and looking at
     `top` or `htop`.

7. Remove the test job.

   * microk8s:

     ```
     microk8s.kubectl delete fuzztest
     ```

At this point the cluster is set up to run fuzzing jobs.

Next you must configure an NFS share, which is used by fuzzers to download jobs
and then store the results when done.

On Ubuntu 18.04:

- Pick a node to host NFS on - the master node is okay for this and usually
  easiest. This node should have lots of disk space, at least 200gb.

- Install nfs:

  ```
  sudo apt update && sudo apt install -y nfs-kernel-server
  ```

- Make a share directory:

  ```
  sudo mkdir -p /opt/lagopus_storage
  sudo chown nobody:nogroupd /opt/lagopus_storage
  ```

- Export this share:

  ```
  echo "/opt/lagopus_storage *(rw,sync,no_subtree_check" >> /etc/exports
  ```

- Open firewall to allow NFS

- Verify that nfs is working by trying to access it from a cluster node:

  ```
  apt install -y nfs-common && showmount -e <nfs_host>
  ```
  If it's working, you should see:

  ```
  Export list for minikube:
  /opt/lagopus_storage ::
  ```

Building
--------
`cd` into the repository, then:

```
./build.sh
```

This builds the necessary docker images and pushes them to DockerHub, generates
the necessary resources YAMLs and concatenates them all into `lagopus.yaml`.

Usage
-----
Build the project as in `Building`.

To start `lagopus`:

```
kubectl apply -f ./lagopus.yaml
```

This starts the jobserver and results server.

New jobs can then be added with `./lagopus.py`. See `--help` for usage.

To undeploy `lagopus`, delete its resources:
```
kubectl delete -f lagopus.yaml
```
Then kill all its jobs:
```
kubectl delete jobs --all
```
