- AFL requires kernel.core_pattern=core. k8s has support for allowing nodes to
  allow sysctls, and allowing pods to use them, which results in a taint on the
  node and therefore requires tolerances on the pod. However, k8s only supports
  namespaced sysctls; core_pattern isn't one, and thus must be manually set on
  the node entirely outside of k8s before starting the kubelet.

- fuzzer jobs should run with dedicated cores. This is a bit tricky to do in
  k8s. First the nodes must be configured with the "static" cpu policy via
  "--cpu-manager-policy=static" on each node. Second, the pod containers must
  be in the "Guaranteed" QOS class, which means memory and cpu requests and
  limits must be set, and must equal each other. This will cause each container
  to have N cpus assigned to it exclusively. Finally with AFL, because
  container runtimes expose all host CPUs but only N of them have been assigned
  to the container, AFL's cpu binding search heuristics will fail because it
  won't be allowed to cores that haven't been assigned to the container but it
  doesn't know which those are. So AFL must be modified to try *all* cores
  until it finds one that binding succeeds on.
