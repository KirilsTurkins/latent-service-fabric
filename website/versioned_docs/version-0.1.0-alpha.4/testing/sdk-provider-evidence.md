# Native SDK provider qualification observations

Date: 2026-09-19. Tested integration source:
`7ce92052` on `feat/sdk-real-node-qualification`, with Rust SDK
`d2b84fd9eee2e322f50cbd65b5d2a1c3e29f6bc6` and Node SDK
`6981f4b9e98370946ca047069ec23334c1779a82`.
These are actual separate-node observations, not issue closure or a release tag.

The [shared workflow contract](sdk-provider-workflow.md) defines all 18 checks.
Both native participants pass, retain nine admitted activation identities and
recover the original policy receipt. Each upstream observes six authenticated
requests, zero unexpected requests, and four started/finally closed held
connections. Policy audit metadata remains absent as the authoritative profile
requires; `auditAttempt: null` is not a durability acknowledgement.

| Participant | Retained actual receipt |
| --- | --- |
| Rust `provider_workflow` example | [Rust evidence](../evidence/phase3-sdk-rust.json) |
| Node `tests/provider-workflow.mjs` | [Node evidence](../evidence/phase3-sdk-typescript.json) |

Each receipt includes exact node/CLI/entrypoint binary or module digests,
signed guest component/package/build-observation identities, retained result
identities and the real shutdown report. Node/provider workers, calls, sockets,
handles, response owners, activations and execution-cell resources retire; the
operator checks the actual reaped node process, not merely a shutdown request.
Entrypoint digests alone are not a complete dependency-closure attestation;
the pinned source, lockfiles and commands identify the tested build context.

## Environment and commands

Linux x86-64 in a dedicated 3-CPU/10-GiB development validation container,
Rust 1.97.1, Node 24.19.0, TypeScript 5.8.3, Zig 0.16.0,
wit-bindgen 0.60.0 and wasm-tools 1.254.0. Guests use the maintained build
recipe with its recorded incomplete dependency/hermeticity boundaries.
The node uses one runtime worker, one control worker, one standard execution
cell, bounded provider pools and 32 retained terminal records with a 120-second
TTL. Client and provider credentials are separate public test-only values in
private files, never browser credentials or deployment defaults.

```sh
cargo build --locked -p latentd -p latent -p latent-sdk --examples --bins
python3 tools/build_guest_capsules.py --output /target/sdk-guests
LSF_GUEST_CAPSULES=/target/sdk-guests LSF_PHASE3_WORKFLOW_FIXTURE_ROOT=/target/sdk-fixture-02 cargo test -p latentd --test phase3_workflow_fixture --locked export_signed_provider_workflow_fixtures -- --exact --ignored --nocapture --test-threads=1
npm ci --prefix sdk/typescript-client --ignore-scripts
npm --prefix sdk/typescript-client run test:transport
python3 tools/run_sdk_provider_workflow.py --cli /target/debug/latent --node /target/debug/latentd --fixture-root /target/sdk-fixture-02 --language rust -- /target/debug/examples/provider_workflow
python3 tools/run_sdk_provider_workflow.py --cli /target/debug/latent --node /target/debug/latentd --fixture-root /target/sdk-fixture-02 --language typescript -- /opt/lsf-node24/bin/node /workspace/sdk/typescript-client/tests/provider-workflow.mjs
```

The fixture output directory must be fresh. Paths describe this owned run,
not required system installation paths. All 18 Node controlled-wire tests also
pass on Linux with zero skips at the recorded revision. Rust's 49 protobuf
cases, 11 profile TCP tests, 10 legacy transport TCP tests, complete SDK tests,
strict SDK-only Clippy and model-only configuration pass separately on Windows.

## Corrections and limits

Actual execution caught two qualification mistakes: the generic ten-second SDK
timeout exceeded the node's five-second ceiling, and the harness initially
expected an audit acknowledgement that policy RPCs do not emit. Examples now
select the existing node limit and assert audit absence; no server ceiling,
authority rule or audit guarantee was relaxed. It also caught the Node codec's
missing unsigned provider-usage map handling; real counters now decode losslessly
and a focused zero/max/invalid-value regression is retained.

One earlier fresh process exited before emitting its startup record. That
attempt was rejected, not counted as passing. Closed stage/code diagnostics
were subsequently added without exposing raw stderr; five new complete owned
Rust workflows passed with no recurrence. The original rejection is not
described as diagnosed or fixed, nor as proof of general startup availability.

No browser, installed native bundle, production security certification,
large-load plateau or cross-language client not named above is qualified by
these observations. Exact-head CI and prerequisite integration remain required
for PR acceptance. The contract CI now explicitly executes both participants
and retains their bounded receipts rather than counting skipped fixtures.
