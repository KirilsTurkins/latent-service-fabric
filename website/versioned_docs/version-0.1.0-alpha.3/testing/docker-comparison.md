# Docker comparison collection and replay

This runbook describes the fixed #111 comparison. Measurement results require a
completed full campaign and independent replay; no performance result is asserted
here. The entrypoint is [run_optimization_docker.py](../../tools/run_optimization_docker.py),
with `build`, `import`, `images`, `run` and `validate` subcommands. The
[private schemas](../../tools/optimization_docker/schemas/README.md) document the
completed evidence shapes. Semantic replay remains the authority for qualification.

The [completed comparison](../../benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc/README.md)
retains the 300-offer smoke and 9,926-offer full results, paired tables and
limitations. Its raw archive was compacted after delivery; restore the exact
historical package using its report or the
[retention policy](benchmark-retention.md) before running archive replay.
The separate [Kubernetes comparison](kubernetes-comparison.md) reuses those
original images and requires the restored Docker package for its own replay.

## Workload and comparison boundary

For each density D=1, 8 and 32, one LSF container serves D deployed services;
D separate native containers each serve one corresponding service. Both paths
use the same persistent gRPC client, authorization token, request/response
validation and bounded forwarding wrapper. Echo receives
`["optimization-reference-v1"]`; compute receives `[17, 10000]`. The native
implementation executes the equivalent Rust business operation directly; LSF
executes a component with platform admission, fuel and memory enforcement.
Equivalent successful outputs do not make those execution or isolation costs
identical. The native path also lacks LSF's cancellation registry, journal,
catalog, routing and preparation. This experiment covers these two operations,
not arbitrary services.

Full collection has seven ordered pairs and 9,926 logical offers. Smoke has one
pair and 300 offers. Each pair has six groups and 30 phases. Density order rotates
by pair; LSF runs first when pair plus position in that rotated order is even.
There are no hidden warmups, retries or adaptive workload changes.

| Density | Phases per arm | Smoke offers per arm | Full offers per arm and pair |
| --- | --- | --- | --- |
| 1 | First; density warmup/measured; echo C1, compute C1 and echo C4 warmup/measured | 30 | 349 |
| 8 | First; density warmup/measured | 24 | 72 |
| 32 | First; density warmup/measured | 96 | 288 |

The first phase visits each service once at concurrency one. Density warmup and
measured phases use global concurrency four and rotate over all D services.
First, warmup and measured populations remain separate. Request budgets are one
second, with five-second connect and outer response limits. The LSF grant requests
10 billion fuel, 64 MiB memory and 16,384 log bytes. The client has two workers.
At D8/D32, full provides only four warmup and four measured echoes per service;
this is not a saturation test or a basis for per-service p99 claims.

Each application cohort has an aggregate CPU quota of four cores, a 2 GiB memory
limit and a 512-PID limit. Each native container receives 1/D of those limits;
the LSF container receives the whole cohort limit. Swap allowance is zero. The
client separately receives two cores, 256 MiB and 128 PIDs. Every container drops
capabilities and sets no-new-privileges. The per-container 1,024 file-descriptor
limit is not an aggregate-matched limit. Native cohorts also contain D wrappers,
while LSF has one; report this actual density cost.

Matching aggregate limits does not make resource sharing identical. At D32,
native resources are partitioned into 32 limits of 0.125 CPU and 64 MiB, whereas
LSF pools the four CPUs and 2 GiB. Global concurrency four cannot borrow idle
native partitions. Density timing therefore compares these deployment and
isolation choices; it does not isolate Docker overhead.

## Required environment and ownership

Build and collection run in Linux containers against a Linux/amd64 Docker Engine
with cgroup v2 and the required CPU, memory, swap and PID controls. Retain the
actual Engine, image, kernel, cgroup and controller identities. When that Engine
is Docker Desktop on WSL2, results describe Linux containers inside its shared
Linux VM. They do not establish native Windows, bare-metal Linux, cloud or
Kubernetes performance. Shared VM activity remains visible and is not subtracted
from either arm. Do not run builds or unrelated benchmark work during collection.

Prepare an explicitly owned Linux controller containing the clean repository and
its measurement Python dependencies, with access to `/var/run/docker.sock` and a
fresh named volume mounted read/write at `/bench`. Both controller and volume must
carry `latent.benchmark.owner=issue111-controller-01`; pass the actual full
64-hex-character controller ID and volume name. The collector verifies these
identities. The Docker socket grants control over this Engine: use the dedicated
controller for the declared experiment. Preserve unrelated containers and volumes.

The pinned base image must already be available locally:
`debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818`.
Image preparation uses the retained executable bytes and Dockerfiles, disables
network build steps and automatic pulls, and retains actual image IDs, rootfs
layers and any available OCI descriptor or repository digest. A local image ID
and an OCI repository digest are distinct identities.

Reserve real backing-disk space as well as space reported inside the Linux VM.
Use fresh paths and run IDs throughout. The driver owns its labeled internal
bridge and measured containers, disconnects the controller afterward, and checks
stopped, reaped and removed owners. It preserves evidence on failure. It does not
remove the controller, named volume, prepared images or unrelated resources.

## Build and image preparation

Run the build from the exact clean source checkout in the owned implementation
container. `<build-sha>` is its full commit. The reusable Cargo target is fixed;
the receipt output is fresh and separate from compiled target subdirectories.

```text
python tools/run_optimization_docker.py build --source-ref <build-sha> --target-root /workspace/project/target --output /workspace/project/target/optimization-docker/build-01
```

This builds `latentd`, `latent`, the native server, persistent client, wrapper and
actual component. The receipt binds the clean source before and after compilation,
toolchain settings, command, process exit, executable bytes and derived fixtures.
Preserve the complete build output, including all referenced source files and
sidecars. Do not substitute an earlier executable under a new source identity.

Inside the controller, import that retained closure through the Engine API.
`<implementation-id>` is the actual full ID of the container holding the build.
The import source's last path component and destination name must match. The
destination is a fresh direct child of `/bench`.

```text
python tools/run_optimization_docker.py import --implementation-id <implementation-id> --source-path /workspace/project/target/optimization-docker/build-01 --output /bench/build-01
python tools/run_optimization_docker.py images --build-root /bench/build-01
```

Import verifies the closed member set, hashes, sizes and executable modes. It
copies no Cargo target tree or Git checkout. Setup scratch is separately bounded
to one retained import tar and one active image-context tar, each at most 512 MiB,
with at most 1 GiB coexistence. A consumed context tar is removed only after its
retained receipt is written. This setup allowance does not enlarge the collected
or published evidence limit.

## Explicit smoke, then full collection

Run each campaign from the clean controller checkout. `<collector-sha>` identifies
the actual Python collector source; it can differ from the binary build source
only when every retained non-Python input is unchanged. Replay binds both source
identities and their exact retained controls.

```text
python tools/run_optimization_docker.py run --profile smoke --run-id docker-smoke-01 --source-ref <collector-sha> --build-root /bench/build-01 --volume <owned-volume> --controller-id <controller-id> --output /bench/smoke-01
python tools/run_optimization_docker.py validate --root /bench/smoke-01 --build-root /bench/build-01 --output /bench/smoke-analysis-01
```

Inspect the complete smoke replay and its cleanup before starting full. The
driver does not start full automatically. Keep every failed attempt under its
original identity, then use another fresh root after a reviewed correction.

```text
python tools/run_optimization_docker.py run --profile full --run-id docker-full-01 --source-ref <collector-sha> --build-root /bench/build-01 --volume <owned-volume> --controller-id <controller-id> --output /bench/full-01
python tools/run_optimization_docker.py validate --root /bench/full-01 --build-root /bench/build-01 --output /bench/full-analysis-01
```

Each campaign first creates three separate seed LSF containers for D=1/8/32.
The 88 management RPCs publish and deploy the real fixtures and inspect the node;
seed setup performs zero guest Invokes. The CLI accepts loopback endpoints, so
each sequential seed container shares the controller's network namespace and the
CLI uses `http://127.0.0.1:7070`. These seed containers retain separate cgroups and
data directories. This setup-only topology is outside the measured request path.
After actual shutdown, the stopped seed catalogs are hashed and copied into
fresh measured LSF data roots. Measured applications and clients use their owned
internal bridge and DNS endpoints; no Windows bind mount is used in that path.

One persistent client process owns all six groups in a pair. It opens D
independent channels per group, including D32. Exactly 61 bounded commands drive
the pair: begin group; ready inventory; first phase; served inventory; remaining
phases; final inventory; finish group; and finally finish the session. All three
inventory barriers exist in both arms. Each LSF group makes three actual GetNode
RPCs over a clone of channel zero, with no additional connection; native barriers
make zero RPCs. Full therefore has 63 measured inventory RPCs, separate from its
9,926 Invoke offers and 88 seed management RPCs.

Ready, served and final barriers each include a requested 250 ms observation
window. All D channels remain open through the final window, then are dropped
before applications shut down. Six snapshots per application retain actual
child/wrapper process identities and cgroups. Original commands, acknowledgements,
individual Attempt envelopes, inventories, events, copied-template identities,
Engine receipts and cleanup stay in the evidence graph. Completion requires zero
remaining client tasks/channels and the owned runtime dropped. Failure or missing
rows cannot qualify by being omitted from a summary.

The campaign deadline is two hours; parent groups have ten minutes and readiness
has 120 seconds. The client additionally bounds each group at five minutes and a
session at 30 minutes. A client retains at most 32 MiB per pair, with 20 KiB Attempt
envelopes and 64 KiB input commands. Collected roots retain at most 1 GiB, 4,096
files and 256 MiB per ordinary file. Capacity is reserved before active groups;
individual output limits and failed originals remain explicit. No allocation
profiler or expanded-profile scratch allowance is part of this experiment.

## Read the comparison without changing its scope

Replay writes an aggregate, twelve CSV tables and their hash manifest in a fresh
output directory. Decimal strings remain exact and CSV `null` means unavailable.
Report all seven LSF-minus-native pair differences, their median/spread and order
strata. Do not subtract independent arm medians or pool phases, densities and
pairs into a single latency distribution. Separate successful latency from
all-dispatched latency and all-offered outcomes. Attempt throughput spans first
scheduled offer to last completion; phase-span throughput includes validation
and output work.

Sum native application children and wrappers separately. Charge every leaf
cgroup once for the whole application-plus-wrapper cohort; do not add process
RSS to cgroup memory. A sum of process RSS can double-count shared pages and is
not PSS. Cgroup memory includes charged cache and kernel memory, without a
`memory.stat` or PSS decomposition here. A sum of lifetime cgroup peaks is not a
simultaneous cohort peak.
Within-invocation memory peaks are unavailable. Any absent constituent makes its
cohort metric unavailable rather than zero.

Resource CPU deltas cover actual snapshot brackets and observer activity around
the requested 250 ms sleep. Child/wrapper CPU cannot be split from that cgroup
receipt. Retain the client's Docker-stat CPU and memory separately; its intervals
include validation, output and barrier waits. Controller process cost is not
separately sampled, and shared-VM background observations are not an attribution
or subtraction estimate.

Image-present container-start-to-ready and first-response figures are observed
upper bounds on the parent clock. Native cohorts are provisioned sequentially;
channel establishment and intentional ready/served pauses remain in those
observations. This lifecycle is not an ideal cold invocation. Never subtract
timestamps from parent, wrapper and client clock origins. Seven pairs provide
descriptive evidence under these controls, not a universal latency, capacity or
production SLO guarantee.

## Offline replay and publication

Offline `validate` reads retained evidence without calling Docker or executing
retained binaries. It can use copied roots on Linux or Windows. Preserve original
`collection_path` and `build_path` values and source bytes when copying; replay
binds those original paths to the new local roots. Use a fresh analysis directory.

Prepare a fresh publication staging root with this exact layout:

```text
<stage>/aggregate.json          exact full-analysis aggregate
<stage>/build/                  complete shared imported build and image receipts
<stage>/run/                    complete full campaign root
<stage>/smoke/                  complete successful smoke campaign root
<stage>/smoke/aggregate.json    exact smoke-analysis aggregate
<stage>/attempts/               optional indexed original failed-attempt evidence
```

Copy the complete referenced closures with original file bytes and modes, then
verify the copied file set, lengths and hashes. Keep report CSVs separately if
they are not part of those closures. Do not edit a failed root into a passing
one. Original failed smoke roots may be retained under `attempts/`, with the
optional checked index and all included files covered by the archive hash
manifest and existing total bounds. These remain diagnostic populations.
The standard Docker archive adapter replays both campaigns against the shared
build and checks exact regenerated aggregates, common build/image identities,
full 7-pair qualification and smoke 1-pair completion. A smoke aggregate has
`completed_paired_run=true` but both full-population flags false.

```text
python tools/package_phase1_evidence.py --source <stage> --output <fresh-package> --compression-level 9 --split-archive
python tools/validate_phase1_archive.py <fresh-package>
```

Packaging performs semantic replay. Docker evidence allows 6,000 regular-file
members so the complete original failed-smoke closures can accompany the shared
build and successful smoke/full roots. The actual initial staging preflight
found 5,014 files before adding the attempts index and rejected the former
5,000-member limit before changing the stage. Other archive kinds retain their
5,000-member limit. Docker's remaining limits stay at 1 GiB expanded, 256 MiB per
file and 198 MB split gzip total, in two to four parts of at most 50 MB.
Compression fit and replay success require actual
receipts. Independently copy and hash the closed package and replay it on the
second platform. Publish measurements, validation receipts, exact source heads
and final CI only after each corresponding action has completed. Identify any
omitted diagnostic files explicitly. Archive membership does not qualify a
failed attempt or add its offers to the successful full population.
