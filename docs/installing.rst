.. _installation:

************
Installation
************

How to install Lagopus!

.. note::

   Installing Lagopus is rather difficult right now, since it's still very much
   in development. You will probably have a hard time unless you already have
   some operational experience with Kubernetes. This setup process will be
   improved prior to the initial release to make it easier and more accessible.

The installation process for Lagopus is roughly:

1. Set up a Kubernetes cluster
2. Configure the cluster nodes; some ``sysctl``'s need to be set on the nodes
   for performance reasons, and k8s doesn't have the ability to do that itself
   right now. The necessary changes can be done with Ansible to make it easier.
3. Create an NFS share accessible by the cluster
4. Clone the Lagopus repository
5. Edit the Kustomizations to reflect your deployment choices; right now, these
   are:
   - What IP you want Lagopus to be accessible from
   - The location of the NFS share configured in step 3
6. Build the resource descriptor file (``lagopus.yaml``) using the provided
   build script
7. Deploy Lagopus on the cluster by applying the resource file with ``kubectl``

Presently, the docker images are stored on my personal Docker Hub instance, but
those will be moved to something more offical before the initial release.
