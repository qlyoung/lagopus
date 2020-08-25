.. _installation:

************
Installation
************

How to install Lagopus!

.. note::

   Installing Lagopus is rather difficult right now, since it's still very much
   a work in progress. You will probably have a hard time unless you already
   have some operational experience with Kubernetes. This setup process will be
   improved prior to the initial release to make it easier and more accessible.

The installation process for Lagopus is roughly:

1. Set up a Kubernetes cluster
2. Configure the cluster nodes; some ``sysctl``'s need to be set on the nodes
   for performance reasons, and k8s doesn't have the ability to do that itself
   right now. The necessary changes can be done with Ansible to make it easier.
3. Create an NFS share accessible by the cluster
4. Clone the Lagopus repository
5. Run ``helm install charts/lagopus``

Presently, the Docker images are stored on my personal Docker Hub instance, but
those will be moved to something more offical before the initial release.

Guide
-----

The steps below assume you are using Ubuntu 18.04 LTS on your cluster nodes.
More generic instructions should be available prior to the initial release.

Cluster Configuration
^^^^^^^^^^^^^^^^^^^^^

* Recommended platform: Ubuntu 18.04
* Recommended k8s: `microk8s <https://microk8s.io/>`_ or `k3s <https://k3s.io/>`_

(k3s is better but all the instructions here are for microk8s)

If you only have 1 node, `minikube <https://minikube.sigs.k8s.io/docs/>`_ is
acceptable, though it invokes virtualization overhead.

If you already have a cluster set up, here is an Ansible playbook to do all of
the steps described if your nodes are running microk8s on Ubuntu 18.04. Change
``qlyoung`` to any root-privileged account.

.. code-block:: yaml

   - hosts: fuzzers
     vars:
       fuzzing_user: qlyoung
     remote_user: {{ fuzzing_user }}
     become: yes
     become_method: sudo
     gather_facts: no
     pre_tasks:
       - name: 'install python2'
         raw: sudo apt-get -y install python
     tasks:
     - name: install-microk8s
       command: snap install microk8s --classic
     - name: microk8s-perms
       command: sudo usermod -a -G microk8s {{ fuzzing_user }}
     - name: microk8s-enable-dns
       command: microk8s.enable dns
     - name: disable-apport
       shell: |
         systemctl disable apport
         systemctl stop apport
       ignore_errors: yes
     - name: set-kernel-core-pattern
       shell: echo 'kernel.core_pattern=core' >> /etc/sysctl.conf && sysctl -p
     - name: set-kubelet-resources
       shell: |
         echo '--cpu-manager-policy=static' >> /var/snap/microk8s/current/args/kubelet
         echo '--kube-reserved="cpu=200m,memory=512Mi"' >> /var/snap/microk8s/current/args/kubelet
         rm /var/snap/microk8s/common/var/lib/kubelet/cpu_manager_state
         systemctl reset-failed snap.microk8s.daemon-kubelet
         systemctl restart snap.microk8s.daemon-kubelet
     - name: install-nfs
       command: apt install -y nfs-common
     - name: set-kernel-scheduler-performance
       command: cd /sys/devices/system/cpu; echo performance | tee cpu*/cpufreq/scaling_governor
       ignore_errors: yes

1. Install Kubernetes on your nodes

2. Join your nodes to the cluster

   * microk8s:

     On the "master" node::

        microk8s.add-node

     On the node (run what the above command told you to run)::

        microk8s.join <id>

3. On your nodes, run the following::

      echo "kernel.core_pattern=core" >> /etc/sysctl.conf
      sysctl -p

   If on Ubuntu, this setting will be overwritten by Apport each boot. You
   thus need to disable Apport::

      systemctl stop apport
      systemctl disable apport

   Next, disable swap to prevent fuzzer memory from being swapped, which hurts
   performance::

      swapoff -a

   Set the CPU governor to performance, which is required by ``AFLplusplus``::

      cd /sys/devices/system/cpu; echo performance | tee cpu*/cpufreq/scaling_governor

4. Set the following kubelet parameters on each of your nodes and restart
   kubelet::

     --cpu-manager-policy=static
     --kube-reserved="cpu=200m,memory=512Mi"

   The first option is absolutely necessary to allow fuzzing jobs to bind to
   CPUs (required by ``AFLplusplus``). The second one reserves some resources
   for the ``kubelet`` process itself, so that fuzzing jobs cannot starve
   ``kubelet``.

   * microk8s:

     Add the above lines to ``/var/snap/microk8s/current/args/kubelet``, then
     run the following to apply them immediately::

        rm /var/snap/microk8s/common/var/lib/kubelet/cpu_manager_state
        systemctl reset-failed snap.microk8s.daemon-kubelet
        systemctl restart snap.microk8s.daemon-kubelet

     If the service fails, check ``journalctl -u snap.microk8s.daemon-kubelet``
     for debugging logs.

5. Verify your cluster is configured on the control plane node, e.g.:

   .. code-block:: console

      root@k8s-master:~# kubectl get no
      NAME         STATUS   ROLES    AGE     VERSION
      microk8s-1   Ready    <none>   38m     v1.17.0
      k8s-master   Ready    <none>   5d15h   v1.17.0

   All nodes should read ``Ready``.


Next you must configure an NFS share, which is used by fuzzers to download jobs
and then store the results when done.

On Ubuntu 18.04:

- Pick somewhere to host NFS on - the master node is okay for this and usually
  easiest.

  .. warning::

     This node should have **lots** of disk space, at least 200gb for
     production deployments; more depending on how heavy your usage is.
     Presently Lagopus doesn't do any management of disk resources itself,
     which is a known limitation; for now, just give yourself as much storage
     headroom as you can. If you're just trying it out, 10gb or so should be
     sufficient depending on your job sizes.

- Install NFS::

     sudo apt update && sudo apt install -y nfs-kernel-server

- Make a share directory::

     sudo mkdir -p /opt/lagopus_storage
     sudo chown nobody:nogroup /opt/lagopus_storage

- Export this share to NFS::

     echo "/opt/lagopus_storage *(rw,sync,no_subtree_check,no_root_squash)" >> /etc/exports
     systemctl restart nfs-server

- Open firewall to allow NFS, if necessary

- Verify that NFS is working by trying to access it from a cluster node::

     apt install -y nfs-common && showmount -e <nfs_host>

  If it's working, you should see:

  .. code-block:: console

     Export list for <nfs_host>:
     /opt/lagopus_storage ::

At this point the cluster is set up to run fuzzing jobs.

Building
^^^^^^^^

This is for development purposes, you do not need to do this if you just want
to deploy the latest release.

``cd`` into the repository. Make your changes. Open ``build.sh`` and edit the
repository information to point at your own Docker repository. Then run
``build.sh`` to build and push the images.

After that you need to replace all the hardcoded references to my repo in the
Helm templates with yours (look for ``qlyoung`` in
``chart/lagopus/templates``).


Installing
^^^^^^^^^^

To install Lagopus onto the cluster, install Helm 3. Then::

   helm install --set lagopusStorageServer=<nfs_host>,lagopusStoragePath=<nfs_share_path>,lagopusIP=<prefix> <release_name> ./lagopus

where:

- ``nfs_host`` is the hostname of your nfs server
- ``nfs_share_path`` is the path of the share you want lagopus to use as its
  storage
- ``prefix`` is an address range from which to select the IP address to host
  the lagopus web interface and API on. If you want to use a specific address,
  pass it as a /32 prefix (e.g. ``1.2.3.4/32``). This address should be
  directly connected relative to the external cluster network; for instance, if
  your cluster machines have addresses in ``10.0.1.0/24``, a reasonable choice
  might be ``10.0.1.169/32``.

Lagopus will select one of the IPs out of the range you configured during
installation to expose the web interface. To get this address:

.. code-block:: console

   kubectl get service | grep lagopus-server | tr -s ' ' | cut -d' ' -f4

Supposing the IP address is ``A.B.C.D``, you can access the web interface by
navigating to http://A.B.C.D/ in your browser. Lagopus does not yet support
TLS.

Uninstalling
^^^^^^^^^^^^

To remove Lagopus from the cluster, delete all its resources.

.. warning::

   helm uninstall charts/lagopus
