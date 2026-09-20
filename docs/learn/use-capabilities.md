# Invoke capabilities and recognize denied authority

## Outcome, version and prerequisites

Run maintained HTTP and immutable-blob guests through a real standalone node,
then inspect denial, revocation, restart and cleanup. Continue with the actual
streaming, local-call, secret, randomness and metric guest fixtures. These are
development contributor scenarios for Linux x86_64, not released-alpha APIs.

Use a clean source checkout at
`50f003dd006e0786494936c49e55dc683cf26fd6` and its
[pinned toolchain](../development/toolchain.md): Rust 1.97.1, Python 3.13.5,
`wasm-tools`, `wit-bindgen` and Zig from `tools/toolchain.toml`. Install the Python
requirements from `tools/requirements.lock`. The fixture uses literal loopback,
temporary storage and public test-only credentials; no provider account or
existing installed node is involved. Native installation has its own
[verified-bundle procedure](../../packaging/linux/INSTALL.md).

The complete configuration owner is
[`phase3_management_scenario.py`](../../tools/phase3_management_scenario.py),
the guest source is in [the maintained examples](../../tools/toolchain-smoke/examples),
and [the workflow](../../tools/run_phase3_management_workflow.py) owns every
command and expected result. The website never executes these commands.

## Select the installed provider before writing a grant

| Operation | Available composition | Authority and reference |
| --- | --- | --- |
| Buffered HTTP and durable local immutable blobs | Opt-in standalone `providers` configuration | [Closed configuration and installed descriptors](../reference/standalone-providers.md) |
| Isolated local calls | Phase 3 capability runtime and exact local binding | [Configured target, child admission and descendant budgets](../runtime/local-service-invocation.md) |
| Streaming HTTP, S3 blobs, local/Vault secrets, NATS events/triggers, randomness and custom metrics | Their maintained trusted Rust composition and guest conformance fixtures | Provider references below; these are not additional accepted fields in standalone `providers` JSON |

An installed provider is necessary but insufficient. The component import,
deployment grant, current tenant/publication policy, compiled binding, provider
epoch and remaining activation budget must all agree. A checked configuration,
valid package signature, or `capability explain` result grants no execution
permission. Use the descriptor returned by the actual node for the provider
binding; do not invent a matching configuration digest.

The fixture configures `budgetProfile.mode = "phase3"`, a durable audit owner,
bounded capability policy jobs and protected provider credentials. Its HTTP
allowlist names the exact local origin, port, address, method and path. Loopback
is deliberately allowed only for this controlled peer. Production SSRF policy
must separately constrain DNS answers, private/special networks and every
redirect destination. A hostname or trusted publisher alone is insufficient.

## Run the standalone workflow

Start at the clean checkout root. The fresh review directory keeps inputs and
receipts separate from earlier runs. Compilation and guest packaging are setup;
neither counts as executing an allowed operation.

```bash
set -euo pipefail
umask 077
test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
test "$(git rev-parse HEAD)" = 50f003dd006e0786494936c49e55dc683cf26fd6
test -z "$(git status --porcelain=v1 --untracked-files=normal)"
export CARGO_TARGET_DIR="$PWD/target"
mkdir -p "$CARGO_TARGET_DIR"
CAPABILITY_REVIEW=$(mktemp -d "$CARGO_TARGET_DIR/capability-guide.XXXXXXXX")
cargo build --locked -p latent -p latentd
python3 tools/build_guest_capsules.py --output "$CAPABILITY_REVIEW/guests"
LSF_GUEST_CAPSULES="$CAPABILITY_REVIEW/guests" \
LSF_PHASE3_WORKFLOW_FIXTURE_ROOT="$CAPABILITY_REVIEW/inputs" \
  cargo test --locked -p latentd --test phase3_workflow_fixture -- \
    export_signed_provider_workflow_fixtures --exact --ignored --nocapture
python3 tools/run_phase3_management_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$CAPABILITY_REVIEW/inputs" \
  > "$CAPABILITY_REVIEW/management.json"
```

Export immediately before execution: the fixture signs the exact guest packages
with expiring test evidence. It never exports private signing keys. Generated
policy and public test credentials are not a trust root for an installed node.

Read the bounded public result without printing private process logs:

```bash
python3 - "$CAPABILITY_REVIEW/management.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
assert 0 < p.stat().st_size <= 262144
r = json.loads(p.read_text())
assert r['schemaVersion'] == 'latent.phase3.management.workflow.v1'
assert r['grantsRevoked'] and r['selectedRevisionPreservedAcrossRestart']
assert r['upstream'] == {'requests': 4, 'authorized': 4, 'unexpected': 0}
assert len(r['shutdown']) == 2
assert all(s['record']['report']['providers']['clean'] for s in r['shutdown'])
print('provider authority, restart and cleanup passed', r['clientCommands'])
PY
```

Observe the sequence in the maintained runner: allowed HTTP reaches the
credential-checking peer, the wrong path returns a typed denial, local blobs
exercise creation/read/error cases, and both providers are used after restart.
The selected deployment revisions remain unchanged. Revoking `http-allow`
prevents the next call with a platform failure; the peer sees exactly four
authorized requests over the whole scenario, so denial did not send extra work.
`capability explain` checks both paths while explicitly returning
`executionPermission = false`.

## Exercise active resources and deliberate failures

These tests run real guest components and owned local peers through the existing
embedding. They create their own finite configuration; do not transplant that
configuration into standalone JSON or call their test credentials production
secrets. Run the complete named targets so a misspelled test filter cannot
silently report zero selected tests.

```bash
cargo test --locked -p latent-wasmtime \
  --test http --test streaming_http --test local_blobs --test local_secrets \
  --test local_service --test random --test metrics -- --nocapture
```

| Reader task | Source to follow and expected failure/recovery |
| --- | --- |
| Stream with finite backpressure | [Streaming guest tests](../../crates/latent-wasmtime/tests/streaming_http.rs) read before the body completes, retain owned chunks and abort/trap/cancel. The socket and all active owners must close; a full input/output window returns a typed exhausted result instead of allocating without limit. Follow the [resource contract](../runtime/streaming-http.md). |
| Read immutable local objects | [Local-blob tests](../../crates/latent-wasmtime/tests/local_blobs.rs) check durable scoped references and bounded reads. Sealing an object and delivering a response are distinct; follow the [local storage/recovery rules](../runtime/local-blobs.md). |
| Rotate protected secret references | [Secret guest tests](../../crates/latent-wasmtime/tests/local_secrets.rs) reject a held read after rotation, keep the old generation charged until release, preserve the prior generation after a failed reload, and enforce revocation/expiry at disclosure. Only an authorized guest read receives bytes; public reports use identities and typed outcomes. |
| Call a local service | [Two-component tests](../../crates/latent-wasmtime/tests/local_service.rs) and [acceptance cases](../../crates/latent-wasmtime/tests/local_service/acceptance.rs) use the normal activation manager and exact compiled target. A child has a fresh store and conserved descendant budget; saturation or cancellation cannot refund still-live work or add a hidden cell. |
| Obtain randomness | [Randomness tests](../../crates/latent-wasmtime/tests/random.rs) exercise both OS-backed methods, zero/max/exhausted requests, denied principals and cancelled disclosure. Failed entropy returns no partial bytes; an attempted byte charge is not silently refunded. |
| Emit bounded custom metrics | [Metric tests](../../crates/latent-wasmtime/tests/metrics.rs) exercise all four kinds, invalid/nonfinite values, cardinality exhaustion and unavailable export. Host-owned identity cannot be injected through guest labels; a new activation does not reset shared series limits. |

For S3, Vault KV-v2 and NATS, continue with
[the owned TLS provider walkthrough](../how-to/exercise-provider-failure-and-recovery.md).
It supplies pinned local services, complete source, rotation, denied paths,
uncertain multipart/publication recovery and actual cleanup. It deliberately
retains its own source and execution identities instead of claiming this newer
checkout executed those historical receipts.

## Cleanup and verification scope

The standalone runner owns and reaps its two node processes and local peer,
then removes its private runtime directory. The Rust tests own their stores,
sockets and temporary data. A failed cleanup or zero selected tests is a failure.
Keep the review receipt and generated guest build observations together; the
fresh `CAPABILITY_REVIEW` directory contains only this run's inputs and results
and can be removed after review. Do not remove an installed node's data directory
to recover a failed fixture.

Machine evidence and human walkthrough review are separate. The coverage matrix
links exact executed sources where available; these source-pinned commands alone
do not certify a new runtime, hosted provider configuration or production SLA.
Use [operator diagnosis and security boundaries](../how-to/operate-capability-providers.md)
to interpret failures without replaying an uncertain mutation.
