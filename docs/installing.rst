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

NFS
^^^
lagopus uses NFS as its storage system. This allows you to keep lagopus storage
on any device you want; it doesn't even have to be on a cluster node. As long
as the NFS server is accessible from the cluster you can use it.

This section describes how to set up an NFS share on Ubuntu 18.04. If you want
to use some other system, that's fine; there are lots of tutorials on how to
set up NFS shares online, it's pretty easy.

- Pick somewhere to host NFS on - the master node is okay for this and usually
  easiest, but any cluster-accessible machine will work.

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


Take note of the hostname or IP address of the NFS server, and the share path.
You will need to specify them when installing lagopus.

Cluster Configuration
^^^^^^^^^^^^^^^^^^^^^

This section is broken down by platform. Each k8s implementation has its
quirks. If you're setting up a new cluster I recommend `k3s
<https://k3s.io/>`_. If you want to test locally I recommend `kind
<https://kind.sigs.k8s.io/>`_ or `minikube
<https://kubernetes.io/docs/tasks/tools/install-minikube/>`_. `microk8s
<https://microk8s.io/>`_. is also an acceptable choice, but you have to deal
with snaps, which have many problems.  Don't use microk8s if you have ZFS
anywhere in your cluster, your troubles will be endless.

.. _basic_node_setup:

Basic node setup
""""""""""""""""

This section assumes you already have a cluster. It is agnostic to whatever
implementation of k8s you choose.

Each node in the cluster needs a few tweaks to support lagopus. The necessary
changes are:

* Install NFS support
* Normalize core dumps
* Disable apport (Ubuntu only)
* Disable swap
* Allow the kubelet to provision static cpu resources
  (``--cpu-manager-policy=static``)
* Set kernel CPU scheduler to performance mode

The last 3 are required for AFL to work as a fuzzing driver.

On each node, do the following:

1. Install NFS support

   This is OS-dependent. For example, on Ubuntu::

      apt update
      apt install -y nfs-common

2. Normalize core dumps::

      echo "kernel.core_pattern=core" >> /etc/sysctl.conf
      sysctl -p

3. If on Ubuntu, the previous setting will be overwritten by Apport each boot.
   You need to disable Apport::

      systemctl stop apport
      systemctl disable apport

4. Next, disable swap to prevent fuzzer memory from being swapped, which hurts
   performance::

      swapoff -a

5. Set the CPU governor to ``performance``::

      cd /sys/devices/system/cpu; echo performance | tee cpu*/cpufreq/scaling_governor

6. Set the following kubelet parameters on each of your nodes and restart
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

On the master node (or the host when using ``kind``) you need to install `Helm
<https://github.com/helm/helm>`_. Lagopus is packaged as a Helm Chart, so you
need Helm to install it.

Installing helm is easy; go `here <https://github.com/helm/helm/releases>`_,
download the latest 3.x release for your platform, extract the tarball and put
the ``helm`` binary in :file:`/usr/local/bin`. If necessary, ``chmod +x
/usr/local/bin/helm``.


kind
""""

`kind <https://kind.sigs.k8s.io/>`_ is a nice option for running locally
without needing a physical cluster.  ``kind`` spins up a cluster on your local
machine by running k8s inside of docker. It's oriented towards proof-of-concept
and local deployments.

Follow the instructions on the ``kind`` homepage to install kind and create a
cluster. After creating a cluster, go through the steps in
:ref:`basic_node_setup`.

In ``kind``, you can log into the nodes as you would a docker container. Find
the container IDs of the cluster nodes with ``docker ps``:

::

   qlyoung@host ~> docker ps
   CONTAINER ID        IMAGE                  COMMAND                  CREATED             STATUS              PORTS                       NAMES
   98bae8548619        kindest/node:v1.18.2   "/usr/local/bin/entr…"   2 hours ago         Up 2 hours          127.0.0.1:39245->6443/tcp   kind-control-plane


After running through the :ref:`basic_node_setup`, you need to get the LAN IP
of the ``kind`` master node. This is the IP that lagopus will expose its web
interface on. Log into the master node, then:

.. code-block:: console

   ip addr show eth0

It should be the first address. For example, on my ``kind`` cluster:

.. code-block:: console

   # ip addr show eth0
   30: eth0@if31: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
       link/ether 02:42:ac:13:00:02 brd ff:ff:ff:ff:ff:ff link-netnsid 0
       inet 172.19.0.2/16 brd 172.19.255.255 scope global eth0
          valid_lft forever preferred_lft forever
       inet6 fc00:f853:ccd:e793::2/64 scope global nodad
          valid_lft forever preferred_lft forever
       inet6 fe80::42:acff:fe13:2/64 scope link
          valid_lft forever preferred_lft forever

The address is ``172.19.0.2``. You should verify that this address is reachable
from your host by pinging it. Note this address; this is what you'll use as
``lagopusIP`` when installing lagopus.

At this point you can skip to :ref:`installing`.


k3s
"""

Go through the steps in :ref:`basic_node_setup`.

TODO: document how to enable static CPU scheduling for k3s kubelets


microk8s
""""""""

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


If the service fails, check ``journalctl -u snap.microk8s.daemon-kubelet``
for debugging logs.


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

.. _installing:

Installing
^^^^^^^^^^

To install Lagopus onto the cluster, clone the repository, ``cd`` into it,
then::

   helm install --set lagopusStorageServer=<nfs_host>,lagopusStoragePath=<nfs_share_path>,lagopusIP=<prefix> <release_name> ./chart/lagopus

where:

- ``nfs_host`` is the hostname of your nfs server
- ``nfs_share_path`` is the path of the share you want lagopus to use as its
  storage
- ``prefix`` is an address range from which to select the IP address to host
  the lagopus web interface and API on. If you want to use a specific address,
  pass it as a /32 prefix (e.g. ``1.2.3.4/32``). This address should be
  directly connected relative to the external cluster network; for instance, if
  your cluster machines have addresses in ``172.19.0.0/24``, a reasonable choice
  might be ``172.19.0.2/32``. In practice, you probably want to use the
  "public" IP of the master k8s node.

Lagopus will select one of the IPs out of the range you configured during
installation to expose the web interface. To get this address:

.. code-block:: console

   kubectl get service | grep lagopus-server | tr -s ' ' | cut -d' ' -f4

Supposing the IP address is ``A.B.C.D``, you can access the web interface by
navigating to http://A.B.C.D/ in your browser. Lagopus does not yet support
TLS.

Uninstalling
^^^^^^^^^^^^

To remove Lagopus from the cluster, uninstall it with Helm.

:::

   helm uninstall charts/lagopus
