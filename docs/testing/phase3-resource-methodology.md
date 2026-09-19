# Phase 3 resource campaign (#239)

Status: implementation checkpoint, **not full ticket acceptance**. The executable
provider checkpoint uses a separate real `latentd`, authenticated CLI, compiled
HTTP/blob guests and the maintained signed provider fixture. A successful build,
a synthetic unit test, or an unexecuted recipe is not resource evidence. Actual
SSR/backend/browser qualification is coordinated with #236/#226; no renderer
heap, event, secret, child-call or OCI-network result is inferred from HTTP/blob.
Separate small Rust HTTP/blob/secret/child measurements are documented in the
[checkpoint](phase3-resource-checkpoint.md); they are not a standalone node or
SSR campaign.

## Ownership and populations

- Fixed: one explicitly owned node, configured runtime/control/compiler pools,
  installed provider registrations and shared listeners. The external HTTP
  fixture and ephemeral CLI processes are different owners, not node workers.
- Dormant: increasing actual admitted capability-enabled deployment records,
  without invocation. The profile uses two shared service/contract bindings;
  that fixed binding configuration is included in the baseline. Metadata and
  configuration growth are not presented as zero-cost service density.
- Active: actual guest Stores/cells, broker handles/calls/results, provider
  queues/connections/workers and I/O buffers. An explicitly held real TCP
  request must be observed before cancellation. Acceptance of cancellation is
  not cleanup: peer EOF, terminal result, reclaimed counters and process reap
  are separate observations.
- Recovered/unrouted: repeated quiescent snapshots after bounded churn and after
  deletion of deployments. Unrouting does not delete retained publication
  evidence, package files, terminal records or prepared-cache contents.

Component, package, publication and deployment counts are separate. The current
standalone checkpoint counts three actual admitted package/component/publication
identities and independently pages deployments. It does **not** yet quantify
multiple publications sharing one package or physical storage deduplication.
That #266 campaign remains required, as does the #270 token/acquisition,
resolver-answer/waiter, connection-byte and redirect-owner campaign.

## Collection and load

`tools/phase3_resource_campaign.py` has explicit finite `smoke` and `campaign`
profiles. Both are manual; the larger profile is not added to CI. The shared
`Process`/`OwnedProcess` harness reserves the unreaped process group, bounds
stdout/stderr, cancels descendants and reaps before refunding ownership. No
unrelated container, system PID or target volume is adopted.

The sampler walks only the owned process tree, with byte, task, descriptor,
network-row, process-count and wall-time limits. TCP/UDP namespace rows count
only when their inode belongs to a sampled process descriptor. PID/start-tick
and actual executable hashes bind observations. Every scan is non-atomic;
descriptor disappearances and inventory/inspection/proc time brackets are
retained. The sampler's own process is outside the node population.

Open-loop arrivals have an immutable monotonic origin and fixed planned times.
Completions do not pace new arrivals. A full finite outstanding-client set
produces a recorded `client-shed` arrival, never an invisible queue, retry or
success. Retain offered, attempted, shed and completed populations separately,
including launch lateness and scheduled-to-completion delay. The explicit
overload episode is separate from successful-call latency distributions.

Provider failure is not the same as RPC failure. The maintained HTTP guest
returns `11` for typed uncertain delivery after the controlled peer actually
disconnects. The blob guest returns `10` for an invalid-state handle, not `11`
(permission denied). The collector retains unclassified call results before
checking expectations, records the peer observation, and does not count these
guest-returned error values as successful provider work.

A requested dormant population can receive `resource-exhausted` before the
catalog's configured entry ceiling. The collector stops that population at the
first definite refusal, pages the actual committed population and retains
requested versus admitted counts. It neither retries that mutation nor infers
a proven capacity ceiling or which owner refused when the CLI does not expose
it. Subsequent diagnostic samples use the **actual** admitted count, but a
refused or incomplete requested population makes the overall campaign fail.
The parent is investigating #344 audit-busy enqueue/reconciliation handling;
an old failure is not reclassified as successful density evidence.

CLI latency includes process creation, connection setup, RPC, possible queueing
and preparation, provider work, and actual process reap. It is **not** isolated
provider network latency or a single-hot-service throughput comparison. Cold
means the first invocation of that target in a fresh node; cache/preparation
counters must accompany interpretation. Cache eviction can make later requests
cold again. No universal Docker/Kubernetes or hardware-independent timing claim
is supported by this protocol.

## Unknowns are not zero

`/proc` RSS is actual resident process memory, not an allocator-retained-byte
counter or a JavaScript heap measure. The latter are explicitly unavailable,
not zero. Provider/cache accounting bytes are conservative ownership charges,
not interchangeable with RSS or unique physical disk blocks. Inventory entries
with an unavailable live count remain unavailable even if their configured
ceiling is known. Quiescence fails when a required provider counter is missing.

The checkpoint asserts only observed process/thread/listener/provider-object
plateaus across dormant populations and return of measured active owners after
failure/cancellation/churn. It reports RSS distributions without inventing an
exact memory-return invariant. Full acceptance still needs several configured
ceilings, longer bounded churn, retained-byte/cache/storage analysis and actual
mixed SSR success/failure/cancellation measurements.

## Exact inputs and immutable reports

Use a new container/target volume, at most three CPUs and 6 GiB. The recorded
build runs `cargo build --locked -p latentd -p latent -j 3`; it hashes the actual
binaries, lockfile and explicit workspace source population before and after
building. The supplied Git revision is operator-asserted, not an attestation.
Compiler implicit inputs and dependency hermeticity are not fully attested.
Generated guest build observations, package/evidence files and collector source
hashes are retained independently. A later build or source change requires a
new identity, never relabeling an old binary.

The maintained guest fixture's signature/provenance lifetime is 1,200 seconds.
Export fresh signed evidence to a new directory for each campaign; do not alter
timestamps, clocks or trust policy to reuse expired evidence. Record the native
build **after** fixture export because Cargo integration-test compilation can
replace a native executable. The preflight retains declared validity windows
and requires enough remaining time for the entire bounded profile plus cleanup;
this is not signature verification, which remains the real node's responsibility.

```sh
python3 tools/install_guest_bindgen.py /workspace/target/phase3-resource-bin
PATH=/workspace/target/phase3-resource-bin:$PATH python3 tools/build_guest_capsules.py --output /workspace/target/phase3-resource-guests
LSF_GUEST_CAPSULES=/workspace/target/phase3-resource-guests LSF_PHASE3_WORKFLOW_FIXTURE_ROOT=/workspace/target/phase3-resource-fixtures cargo test --locked -p latentd --test phase3_workflow_fixture export_signed_provider_workflow_fixtures -- --exact --ignored --nocapture --test-threads=1
python3 tools/phase3_resource_campaign.py --record-build /workspace/target/resource-build.json --revision FULL_TESTED_COMMIT
python3 tools/phase3_resource_campaign.py --profile smoke --node /workspace/target/debug/latentd --cli /workspace/target/debug/latent --fixture-root /workspace/target/phase3-resource-fixtures --build-identity /workspace/target/resource-build.json --output /workspace/target/resource-smoke.json --host-condition shared-docker-desktop-host
python3 tools/phase3_resource_campaign.py --validate /workspace/target/resource-smoke.json
python3 -m unittest tools.tests.test_phase3_resource
```

Outputs use exclusive creation, bounded canonical JSON and exact-byte SHA-256
sidecars. Failed attempts retain `status: failed`; a later pass is a different
file. The only current success status is `checkpoint-passed`, with
`ticketAcceptance: pending` and explicit missing acceptance populations. Keep
full temporary data under the owned target volume; commit concise immutable
reports under `docs/testing/phase3-resource-evidence/`. Host outages remain
host-condition evidence, not successful cleanup and not an assumed application
leak. No automatic retry reclassifies such failures.

## Small regression boundary

`tools/tests/test_phase3_resource.py` exercises finite open-loop load shedding,
immutable arrival identities, deadline/error cleanup, false-empty rejection,
missing-counter rejection, inode-scoped socket accounting, bounded input
inventory and immutable output refusal. Linux also measures and reaps a real
owned process. These synthetic regression fixtures are not benchmark evidence.
No shared SDK runner, Angular T1 implementation, merge or issue closure belongs
to this resource worker.

`tools/phase3_resource_rust.py` builds the dedicated `phase3_resource` integration
test, selects only the executable named by successful Cargo JSON metadata,
checks its exact nonempty libtest listing, and runs it through the maintained
owned-process harness. The receipt records commands, compiler/profile/input
identity, bounded output, process reap and the separately hashed observation
file. Failed execution or incomplete active/recovered populations cannot pass.

```sh
python3 tools/phase3_resource_rust.py --revision FULL_TESTED_COMMIT --output /workspace/target/resource-rust-run.json --report /workspace/target/resource-rust-observations.json --host-condition shared-docker-desktop-host
cargo test --locked -p latent-wasmtime --test phase3_resource -- --test-threads=1
```
