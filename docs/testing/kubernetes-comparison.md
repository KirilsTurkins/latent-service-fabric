# Kubernetes Service comparison

This is the #112 runbook for the fixed local Kubernetes comparison.
Cluster setup, smoke/full outcomes and measured results require their actual
receipts; this document asserts no Kubernetes performance result. The pure
[model](../../tools/optimization_kubernetes/model.py) builds the plan, owned
namespace, Pods and Services. The [Docker runbook](docker-comparison.md) defines
the unchanged client workload and business-operation comparison.

The [retained comparison](../../benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f/README.md)
publishes the actual outcomes, failed attempts, resource differences and replay
receipts. Its restoration command retrieves the exact original Docker dependency
without restoring unrelated historical archives.

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
worker carries `latent.benchmark.worker=<owner>` with the exact unique cluster
owner from the setup receipt. `model.plan(profile, owner=owner)` and Pods select
that owned label and use
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

Declared native application requests and limits total LSF's four CPUs and 2 GiB,
including wrappers. Effective enforcement is recorded separately. In smoke03,
all 32 native D32 Pods requested `125m` and their CRI runtime specifications
recorded `12500 100000`, while every observed leaf and Pod ancestor recorded
`cpu.max = 13000 100000`. The effective native cohort ceiling was therefore
4.16 CPUs versus LSF's 4.0 CPUs, a 4% difference in permitted CPU, not observed
CPU use. The ordinary pinned runtime is retained; this is a comparison with
matched requested resources and an explicit effective CPU difference at D32.
Replay preserves both values and accepts only the specifically evidenced
configuration, without normalizing the observations or applying a general
tolerance.

The observed rounding is consistent with the upstream report that the runc
systemd driver rounds fractional CPU percentages upward and can restore that
rounded quota after another resource update. The campaign observations do not
isolate which update caused the change. See [runc issue 4622](https://github.com/opencontainers/runc/issues/4622).

The distribution also differs: global C4 cannot borrow the idle CPU/memory partitions
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
PID/FD enforcement from matched requested CPU/memory quantities.

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

EndpointSlice readiness and worker proxy programming are separate gates. After
the API graph becomes ready, the parent reads the owned worker's original
`iptables-save -t nat` and `iptables-save -t filter` output. Every current Service
IP and port must have the expected Service-chain to endpoint-chain to Pod-IP
forwarding path, without a matching rejecting rule, before `begin-group` opens
the client channels. These are bounded rule-table observations, not TCP probes
or extra Invokes. Retain every poll and its original command/output receipt, with
at most 20 attempts and a 120-second overall readiness deadline.
`graph_ready_nanos` continues to denote the API graph milestone;
`proxy_ready_nanos` records the later observed forwarding-rule milestone.
Neither is an exact timestamp of when the kernel first became reachable.

This gate follows the retained smoke-02 failure: its 30 LSF offers succeeded,
then the first new native Service connection failed despite an API-ready
EndpointSlice. No native Invoke was made and owned cleanup completed. The failed
attempt remains diagnostic; the new gate does not alter that original record or
turn its partial population into a completed smoke.

Replay preserves the original API response bytes. Kubernetes typed List responses
can omit `kind` and `apiVersion` on their embedded items: the enclosing
`PodList`, `ServiceList` or `EndpointSliceList` supplies that type only after its
own type and complete, unpaginated population are checked. A conflicting explicit
item type still fails. Specific omitted false/zero manifest fields use their
declared API defaults; omission does not authorize changing other controls.
EndpointSlice owner labels may be absent, but the exact Service name and UID in
the controller owner reference are required. A lingering slice from an earlier
group remains in the original response and is excluded from the current graph
only when it matches that earlier owned Service creation. Unknown, foreign or
crossed owners fail validation. No normalized replacement API record is published.

The current `latent.optimization.kubernetes-plan.v2` declares
`startup_protocol: exec-ready-event.v1`. Its startup probe uses the unchanged
images' `/bin/sh` and `/usr/bin/head` to read at most 65,536 bytes of the fresh
`/output/events.ndjson`. It requires complete LF-terminated `started` sequence 0
and `ready` sequence 1 records, the exact wrapper schema and fixed details,
matching application/child PID, wrapper PID 1 and ordered numeric elapsed times.
The existing wrapper flushes `ready` only after its child is ready and port 7070
is bound. Absent, partial or mismatched records fail the probe. The check opens
no network connection and performs no guest Invoke. Its one-second period and
timeout, failure threshold 120 and success threshold one remain unchanged.
There is no ongoing readiness or liveness probe. Pod Ready, Service/EndpointSlice
and the proxy-rule gate still precede client connection through ClusterIP.

Original `plan.v1` TCP-probe records remain immutable and replay only for the
four retained owner/source/run/profile identities: smoke-01, smoke-02, smoke-03
and full-01. Historical smoke-03 is a completed workload with its separate
cleanup-completion proof; it is not a run of the new probe protocol. Historical
successful owners require one residual accepted connection, consistent with the
TCP startup probe under the owned path; no source-peer tracing was captured.
Current owners require exactly the client channels and zero residual accepted
connections. Every actual forwarding failure remains fatal. The full-01
`forward-failed` record did not retain its errno, and its byte counters excluded
failed forwards, so neither a probe root cause nor zero transferred bytes is
claimed. The exec check removes the startup probe's TCP interaction while
preserving exact #111 images and workload populations. New smoke evidence must
pass before the new full campaign; no original attempt is relabelled or replaced.

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
container start, wrapper/Pod ready, endpoint ready, forwarding-rule readiness and
first semantic response
as their actual observed milestones. Images are already present; all application
Pods in a group are submitted before waiting for them, unlike the original
Docker campaign's sequential provisioning. Pod creation, both readiness gates,
channel setup and deliberate barriers
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
Completed `suite.json` stores ordered identity/hash references to the original
`group-P-G.json` files; replay verifies each reference before expanding its group
in memory, keeping the existing per-document decoder limits unchanged.
Whole-campaign Kubernetes bookkeeping uses an explicit 6,144-entry inventory cap
(including the root directory), eight directory levels, 256 MiB per file and
1 GiB total; small fixture/transfer checks and the unchanged nested Docker plan's
4,096-entry limit retain their original scopes. Smoke-03 retained 903 files and
178 subdirectories, and the full campaign's repeated owner/client/transfer
records require this separately bounded inventory.

The Windows [setup helper](../../tools/optimization_kubernetes/setup.py) creates
the unique owned cluster and imports the pinned original images. Its fresh root
must be `target/phase1-extension/issue112-setup-NN` in the selected repository.
Setup failure retains its original receipt, cluster and private credentials;
`--resume-from` verifies a specifically retained import without repeating it.
It is not a generic retry switch. The setup and Linux controller identities are
source-bound to this experiment; inspect their declared pins before reproduction.

```text
python -m tools.optimization_kubernetes.setup --repository <repository> --root <repository>/target/phase1-extension/issue112-setup-NN
```

Transfer the hash-bound public setup provenance and the private kubeconfig to the
owned Linux controller. Keep the latter outside publication inputs. Bootstrap
uses the original successful setup, or its separately validated resume receipt
plus the unchanged original. The bootstrap root is exactly
`/bench/kubernetes/<owner>`. Run from the clean collector checkout with the exact
`--source-ref`; each output must be its fresh run-ID child. Build and Docker run
roots are the unchanged #111 closures, not newly built substitutes.

```text
python tools/run_optimization_kubernetes.py bootstrap --setup <verified-setup.json> --original-setup <original-setup.json> --kubeconfig <private-kubeconfig> --output /bench/kubernetes/<owner>
python tools/run_optimization_kubernetes.py run --profile smoke --source-ref <clean-collector-SHA> --run-id smoke-NN --bootstrap /bench/kubernetes/<owner>/bootstrap.json --build-root <docker-build> --docker-run <docker-full> --output /bench/kubernetes/<owner>/smoke-NN
python tools/run_optimization_kubernetes.py validate --root <smoke-root> --build-root <docker-build> --docker-run <docker-full> --bootstrap-root <bootstrap-root> --output <fresh-smoke-analysis>
python tools/run_optimization_kubernetes.py run --profile full --source-ref <clean-collector-SHA> --run-id full-NN --bootstrap /bench/kubernetes/<owner>/bootstrap.json --build-root <docker-build> --docker-run <docker-full> --output /bench/kubernetes/<owner>/full-NN
python tools/run_optimization_kubernetes.py validate --root <full-root> --build-root <docker-build> --docker-run <docker-full> --bootstrap-root <bootstrap-root> --output <fresh-full-analysis>
```

The driver records HTTPS API calls with private TLS identity and bounded request
deadlines; kubectl is used for the owned persistent client attach. Do not replace
the driver with ad hoc Pod commands or extra probes. Inspect both smoke collection
and offline replay before full collection. Validation reads original records,
performs no Kubernetes operations and writes only a fresh analysis directory.

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

After all campaigns and any explicit failure recovery, perform final teardown
once. The cleanup command retains the actual Linux cluster, network and copied
credential-removal receipts. Separately remove the original Windows private
kubeconfig with the retained ownership/hash-checking helper and retain its
`windows-credential-cleanup.json` receipt and exact helper source.

```text
python tools/run_optimization_kubernetes.py cleanup --bootstrap /bench/kubernetes/<owner>/bootstrap.json --output /bench/kubernetes/<owner>/cleanup-NN
```

## Offline archive and original Docker dependency

The Kubernetes publication depends on the immutable original #111 Docker package
with logical gzip SHA-256
`b51441c7d23eb9569f77d00026533e9a5395c7732b1109b38cfbc3defeca43fd`.
It does not duplicate that package's build, images or Docker campaign. Prepare a
fresh stage containing:

```text
aggregate.json, docker-aggregate.json   exact full-analysis JSON outputs
*.csv, manifest.json                   all sixteen exact tables and analysis manifest
docker-reference.json                  original Docker archive/manifest/aggregate byte hashes
run/                                   complete full Kubernetes campaign
smoke/                                 complete successful smoke and its aggregate.json
bootstrap/                             complete public bootstrap/provenance closure
cluster-cleanup/                       final Linux and Windows cleanup receipts and helper
attempts/                              optional indexed original failed attempt and recovery
prior-smokes/                          earlier completed smokes, replayed separately
```

Never copy `bootstrap/private/`, TLS key/certificate files or private kubeconfig
contents into the archive. Their recorded identity hashes are public evidence;
the archive rejects a retained private subtree. Preserve each failed attempt and
its separate recovery without rewriting the failed suite. Indexed failure
evidence is diagnostic and contributes no offers to either qualified population.
The recorded full-01 failure retains its five completed groups and 1,130
successful offers, alongside the failed forward and original failed cleanup.
Its separate recovery captures the remaining 33 output directories and proves
owned cleanup without a new Invoke. The full failure adapter requires the exact
original source, four original journal/suite hashes and the Docker dependency;
it cannot qualify this prefix as a completed full campaign. A completed earlier
smoke, including smoke-03 and its separate cleanup completion, belongs under
`prior-smokes/` with an exact suite/aggregate index. Its offers remain separate
from the current smoke and full populations.

```text
python tools/package_phase1_evidence.py --source <stage> --output <fresh-package> --compression-level 9 --split-archive --docker-package <original-docker-package>
python tools/validate_phase1_archive.py <kubernetes-package> --docker-package <original-docker-package>
```

Packaging and replay verify the original Docker package, safely extract its
bounded dependency into a temporary directory, rehash its members, and replay
both Kubernetes campaigns against that same build and full Docker run. They
check exact aggregate, CSV and manifest bytes and require final cluster cleanup
after both campaigns. No retained source or executable is run. Repeat archive
replay independently on Linux and Windows, preserving package hashes.

The Kubernetes package allows 8,000 files to retain the current full and smoke,
completed prior smoke, failed attempts and bootstrap/cleanup together. Its
expanded limit remains 1 GiB, with at most 256 MiB per file. The separately
validated Docker dependency keeps its own 6,000-file bound; other families'
file-count limits are unchanged.
Split gzip remains at most 198 MB, in two to four parts of at most 50 MB. This
does not establish that any not-yet-packaged population fits: actual compressed
size, both semantic replay results and cleanup receipts remain required.

When run on Docker Desktop/WSL2, the result describes a real Kubernetes Service
path inside this host's shared Linux VM. One local worker and a separate local
control plane are not hardware isolation, a cloud or multi-host deployment, HA,
bare-metal Linux, or a universal Kubernetes overhead claim.
