# Kubernetes Service comparison

This is the initial #112 runbook for the fixed local Kubernetes comparison.
Cluster setup, smoke/full outcomes and measured results require their actual
receipts; this document asserts no Kubernetes performance result. The pure
[model](../../tools/optimization_kubernetes/model.py) builds the plan, owned
namespace, Pods and Services. The [Docker runbook](docker-comparison.md) defines
the unchanged client workload and business-operation comparison.

## Fixed workload and image reuse

Reuse the exact three #111 application/client image tags, retained image content,
five executable hashes and actual component/fixture bytes. The forwarding
wrapper is already PID 1 inside each application image and owns the loopback
application child; it is not an additional sidecar. Preserve that entrypoint and
command. Import the existing images before timing and set `imagePullPolicy: Never`.
An absent image is a setup failure, not permission to pull or rebuild silently.
Bind the original Docker image identity, imported manifest/config/layers, CRI
image inspection and Pod-reported image ID without assuming their digest fields
identify the same object.

The Kubernetes plan nests the unchanged `optimization_docker.model.plan` under
`workload`: seven full pairs / 9,926 logical offers or one smoke pair / 300 offers.
Each pair has six groups, 30 phases and 61 persistent-client commands. Density
order rotates by pair, with the same alternating first arm. D=1/8/32 compares one
LSF application Pod serving D services with D native application Pods. Each arm
exposes D Services, so each pair creates 82 measured Service objects.

Reuse the three actually stopped, pristine #111 density catalogs, with original
clean-stop and inventory hashes. Copy fixtures and fresh group data before Pod
creation. No new seed LSF process, setup management RPC or guest Invoke is
performed for this reuse. The nested Docker plan's 3 seed starts / 88 management
RPCs remain provenance for how the originals were produced, not additional #112
operations. The measured client still performs three GetNode calls per LSF group
over an existing channel: nine per pair and 63 for full; native barriers make none.

Echo receives `["optimization-reference-v1"]`; compute receives `[17, 10000]`.
Keep the same authentication, payload/result oracle, one-second request budget,
five-second connect/outer response limits and two client workers. The first
phase visits each service once at C1. Density warmup and measured phases use
global C4; full D8/D32 has four warmup and four measured echoes per service.
D1 adds the existing echo C1, compute C1 and echo C4 phases. These are small fixed
populations, not saturation tests or per-service p99 evidence. First, warmup and
measured populations remain separate, without retries or replacement offers.

## Owned cluster and ordinary runtime

Use a uniquely owned kind cluster with one control plane and one dedicated worker,
an explicit private kubeconfig/context and retained tool/node-image pins. The
worker carries `latent.benchmark.worker=issue112`. Pods select that label and use
the normal Kubernetes scheduler; they do not set `nodeName`. Keep the ordinary
runc runtime. There are no experiment RuntimeClasses or altered runc base specs.
The previously considered four-runtime configuration is outside this protocol.

Retain actual inner containerd/runc, kubelet, CNI, proxy, DNS, node UIDs, image IDs,
capacity/allocatable and enclosing node resource settings. An outer Docker
runtime version does not identify the inner kind runtime. Image import and
cluster creation are setup costs, separate from application timing. Use explicit
owner identities; never alter the user's kubeconfig, Docker context or unrelated
cluster. Keep failed setup evidence before any owned cleanup.

The manifest namespace is `<owner>-<run>` with a validated maximum of 63
characters. Every Pod and Service carries owner, run and role labels. Parent
lifecycle receipts must also bind API UIDs/resourceVersions and actual container
identities; matching a reusable name is insufficient for cleanup or endpoint
ownership.

All input and mutable paths are prepared on the exact owned worker beneath
`/var/local/lsf112/<owner>/<run>/`. Fixtures mount read-only at `/fixtures`;
fresh outputs mount at `/output`; only LSF mounts a fresh data directory at
`/data`. The builder rejects foreign or overlapping mount roots and uses
`hostPath.type: Directory`, so Kubernetes does not silently create missing data.
The parent additionally verifies real filesystem ownership, symlink absence,
inventory hashes and fresh output/data before submitting the Pod. A canonical
path string alone is not this physical proof. No Windows data mount is used in
the measured request path.

## Pod controls and resource scope

Each Pod has one container named `lsf`, `native` or `client`. CPU and memory
requests equal limits, using the following fixed quantities:

| Owner | CPU request/limit | Memory request/limit |
| --- | --- | --- |
| LSF application, any density | 4000m | 2048 MiB |
| Each native application, D1 | 4000m | 2048 MiB |
| Each native application, D8 | 500m | 256 MiB |
| Each native application, D32 | 125m | 64 MiB |
| Persistent client | 2000m | 256 MiB |

Native application totals match LSF's four CPUs and 2 GiB, including wrappers.
The distribution differs: global C4 cannot borrow the idle CPU/memory partitions
of other native Pods. LSF pools the cohort allocation. Compare these deployment
and isolation choices, rather than attributing the entire difference to a
Kubernetes transport cost. The native implementation performs the same business
operations but lacks Wasm fuel/memory enforcement and the platform's routing,
preparation, cancellation registry, journal and catalog.

Declare kubelet `podPidsLimit=512` for the dedicated worker and retain actual
Pod/container/ancestor PID controls. This common per-Pod setting does not match
Docker's divided native PID limits or separate client PID limit; report those
differences. There is no invented PID-limit or file-descriptor field in these
Pod manifests. Retain actual process FD limits and counts. Do not claim equal
PID/FD enforcement from matched CPU/memory quantities.

Pods use `restartPolicy: Never`, a 40-second termination grace, no host network,
PID or IPC namespace, no shared Pod process namespace, and no automounted service
account token. Containers have a read-only root filesystem, drop all capabilities
and disallow privilege escalation. `/tmp` is an `emptyDir` with `medium: Memory`
and `sizeLimit: 16Mi`. Retain its actual mount flags; this manifest does not prove
Docker's `noexec`/`nosuid` mount behavior. Observe effective memory/swap/CPU
controls and ancestor limits rather than treating submitted limits as their proof.

## Actual ClusterIP and readiness path

For each group, create Services `p<pair>-g<group>-s<index>`. Every Service selects
the exact owner/run/Pod role. All D LSF Services select
`p<pair>-g<group>-lsf-0`; native Service i selects
`p<pair>-g<group>-native-i`. Each Service is IPv4, selector-backed, non-headless
ClusterIP with TCP port/targetPort 7070, `sessionAffinity: None` and
`publishNotReadyAddresses: false`.

The measured path is persistent client Pod -> Service ClusterIP -> matching
EndpointSlice endpoint -> existing wrapper -> loopback application. Retain the
allocated Service IP/UID, all matching EndpointSlices, their Pod UID targetRefs,
readiness/serving/terminating conditions and the selected Pod/container identity.
Use that actual Service destination in the original client target records.
Direct Pod IP, port-forward, NodePort, Ingress or a Windows host listener is not
this population. One LSF Pod behind multiple Services remains one process owner.

Application Pods have only a TCP startup probe on 7070, with one-second period
and timeout, failure threshold 120 and success threshold one. The wrapper binds
that port after its child-ready event. Retain the actual wrapper-ready record,
Pod Ready state and matching ready endpoint before connecting the client.
There is no ongoing readiness or liveness probe during measurement, avoiding
extra continuing connections alongside the 32-channel case. Probe quantization
and observed failures remain visible; startup is not a hidden semantic Invoke.

Client Pods are named `client-p<pair>`, have stdin open, `stdinOnce: false`, no
TTY and no startup/readiness/liveness probe. The unchanged client emits its first
ready acknowledgement before attach. Retain that original Pod-log line, then
attach the persistent stdin/stdout transport before sending the first command.
Bind the final original Pod stdout to every acknowledgement, including ready;
do not synthesize a replacement ready event or drop an acknowledgement because
attachment began later.

Ready, served and final inventory barriers retain the same requested 250 ms
resource windows, with all D channels held through the final window. Parent,
wrapper and client clock origins stay separate. Report API-create, scheduling,
container start, wrapper/Pod ready, endpoint ready and first semantic response
as their actual observed milestones. Images are already present; sequential
native provisioning, endpoint readiness, channel setup and deliberate barriers
remain in parent upper bounds. This is not idealized image-absent cold latency.

## Collection, evidence and limits

The bounded parent driver prepares submitted JSON with the model, retains those
exact bytes, creates one group at a time, drives the unchanged client and records
API/CRI/process/resource observations. Use a fresh namespace/data root for each
campaign and a fresh Pod UID/process for every group owner. At most 32 application
Pods and one persistent client are active; no replicas, autoscaler, sidecars or
unplanned workload are added. Run and inspect the explicit 300-offer smoke before
the seven-pair full campaign. An incomplete or failed attempt cannot qualify by
dropping failed rows or shrinking density.

Use explicit private kubeconfig, context, namespace and bounded request timeout
on every kubectl call. The following are operation templates, not a completed
collection or a substitute for the owned driver and retained receipts:

```text
kubectl --kubeconfig <private-config> --context <owned-context> --request-timeout=10s create -f <owned-namespace.json>
kubectl --kubeconfig <private-config> --context <owned-context> --namespace <owned-namespace> --request-timeout=10s create -f <group-manifests.json>
kubectl --kubeconfig <private-config> --context <owned-context> --namespace <owned-namespace> --request-timeout=10s get pods,services,endpointslices -o json
kubectl --kubeconfig <private-config> --context <owned-context> --namespace <owned-namespace> attach -i <client-pod> -c client --pod-running-timeout=120s
```

Keep child and wrapper RSS/thread/FD observations separate and count every leaf
cgroup once. Pod and kind-node totals include enclosing costs and must not be
added to descendant totals. Retain client cost and fixed worker/control-plane
background separately without claiming exact background subtraction. RSS sums
can double-count shared pages; summed lifetime peaks are not a simultaneous
cohort maximum. Missing observations remain unavailable. Preserve all seven
pairs and order strata; do not pool their latency distributions or subtract
unrelated clock origins.

Cleanup requires the original wrapper child/copy-task shutdown receipts, client
task/channel/runtime completion, final container exit status and actual owner
absence. A deletion acknowledgement alone is insufficient. Delete only the
recorded owned UIDs, verify termination and CRI disappearance, and remove only
their verified data and namespace. Cluster teardown additionally checks the
recorded kind node/container identities; retain pre-existing/shared networks and
all #111 image/catalog evidence. Report any forced termination or failed cleanup.

When run on Docker Desktop/WSL2, the result describes a real Kubernetes Service
path inside this host's shared Linux VM. One local worker and a separate local
control plane are not hardware isolation, a cloud or multi-host deployment, HA,
bare-metal Linux, or a universal Kubernetes overhead claim.
