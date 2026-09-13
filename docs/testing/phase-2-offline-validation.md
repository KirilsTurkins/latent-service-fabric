# Phase 2 offline trust and registry availability

These bounded checks distinguish unavailable transfer from invalid local
authority. They do not extend a trust snapshot or substitute a registry result
for signature, tenant or lifecycle checks.

The [completed Phase 2 gate](../phase-2-completion.md) retains the
[24-command outage/revocation run](../../benchmarks/phase2/2026-09-13/offline-receipt.json)
and [three native-currentness cases](../../benchmarks/phase2/2026-09-13/native-currentness-receipt.json).
Commands below create a new observation with fresh evidence and current binaries;
they do not reproduce those historical execution identities merely by passing.

## Real registry outage and local revocation

The fixed `phase2-offline-r1` schedule uses two freshly signed test packages, one
standalone node/cell, at most 40 CLI processes and exactly three invocation
attempts. Its scenario deadline is 180 seconds; registry certificate generation,
startup/readiness and cleanup use the separately bounded fixture tooling. The
entire registry lifetime has the shared cancellation owner, including setup.

From a clean Linux checkout, build the CLI and node and export the fresh fixture
using the [operator walkthrough](../development/standalone-quickstart.md#bounded-phase-2-operator-workflow).
Then run:

```bash
python3 tools/run_phase2_offline_workflow.py \
  --cli "$PWD/target/debug/latent" --node "$PWD/target/debug/latentd" \
  --fixture-root "$FIXTURE_PARENT/inputs" \
  --source-commit "$(git -c gc.auto=0 rev-parse HEAD)"
```

The runner records exact binaries, collector files, policy/configuration and
package identities. After real authenticated TLS transfer and admission, it
invokes the local route, stops its owned registry and verifies that a fresh pull
fails. The same local route must still invoke with the same component and route
identity. It then revokes the release locally and requires a permission denial
for the next invocation, with the registry still stopped. No route refresh,
readmission, automatic retry or additional canary sampling is involved.

The compact receipt contains both successful pins, failed transfer and revoked
invocation categories, operation receipts, the actual clean shutdown report and
successful node reap. Client/node storage and registry data are temporary. The
fixture's signed observation is explicitly synthetic; actual observed-build
evidence remains the separate OCI provenance integration.

## Current trust at warm and native boundaries

The three explicit ignored tests in
[trust_currentness.rs](../../apps/latentd/src/standalone/start/tests/trust_currentness.rs)
compose real publisher/builder verification, enforced catalogs and the approved
isolated compiler with a controlled host clock. Each compiles one small component
once and successfully invokes it, retaining readiness and an unpolled invocation
before changing authority.

- Proof age advances past its 600-second bound while signatures and policy
  remain valid.
- Joint policy expiry occurs while evidence lifetime and proof age remain valid.
- Publisher revocation changes approved policy at the same clock value, without
  a registry event.

Each schedule renews the clock lease independently, then checks the exact denial
cause at preparation, materialization, final invocation start and native-cache
reopen. Compile, native-load and guest-store counters must not increase. Expired
or revoked catalog recovery preserves readable historical records with denied
eligibility. Fresh explicit verification can legitimately renew an otherwise
valid proof-age-only grant; these tests do not call that revival of an old grant.

```bash
cargo build -p latent-wasmtime --bin latent-aot-compiler --all-features --locked
LSF_OPERATOR_FIXTURE_ROOT="$FIXTURE_PARENT/inputs" \
LSF_AOT_COMPILER="$PWD/target/debug/latent-aot-compiler" \
  cargo test -p latentd --lib --all-features --locked \
  standalone::start::tests::trust_currentness:: -- --ignored --test-threads=1
```

Native output is limited to 2 MiB per case, with one compiler worker/job and
finite request, image and persistent-cache allowances. These are correctness and
ownership checks, not native compilation throughput benchmarks or general
offline availability guarantees.
