# Java transport validation evidence

Validated implementation: `b7e270d3faaa08aef7837f83133be8d0b6b0426f`, following
code milestones `a13b335d` and `29abda86`, PR #367, branch
`feat/262-bounded-java-client`. Base: development `9c271713` plus the complete
shared-profile dependency through `e4096670`. These checks ran on 2026-09-19;
no issue closure, merge or parent acceptance is claimed. The real-node receipt
below belongs to that original implementation, not automatically to later heads.

## Unsigned-clock review follow-up

`a900ad83ea951b03a3fb6ae558df8462b554aa87` corrects native invocation deadline
handling. Controlled real TCP calls transmit `9223372036854775808` and
`18446744073709551615` unchanged, while the peer observes the finite local RPC
budget. A held maximum-deadline request still reaches its original 500ms local
deadline. Expired absolute values open no connection. Relative timeouts above
the configured cap, including signed-positive overflow-range and high-bit u64
values, uniformly fail locally with `Limit` and the original recovery identity.

Six additional schedules test both Invoke and ApplyPolicy against actual
HTTP/2 REFUSED_STREAM, GOAWAY with last-stream zero, and gRPC Unavailable.
`resetGoAwayAndUnavailableNeverReplay` counts exactly one original request,
requires an explicit subsequent status call to succeed, and observes real socket
closure after client shutdown. GOAWAY uses a fresh TCP connection for that new
call; reconnection is not prohibited or confused with retry of the failed call.

After Docker recovery, pinned Linux Temurin 21.0.11+10 passes all 68 shared
vectors, legacy/lifetime checks, 49 protobuf cases and the expanded eleven TCP
suites. Production/example Java 21 strict lint passes. Windows Temurin 25.0.3+9
with `--release 21` also exercises the expanded suites. Interrupted Docker work
is not counted as either successful or failed evidence. No dependency changes,
new real-node qualification, stronger socket-lifetime guarantee or parent
integration/CI result is inferred from these focused regressions.

## Executed local checks

- Windows x86-64, Temurin 25.0.3+9, Java `--release 21`, Python 3.13.5:
  locked generator/dependency preparation, compilation, all 68 shared model
  vectors, legacy identity/lifetime tests, 48 actual protobuf round trips and one
  rejected contradictory oneof, and all nine controlled TCP suites passed.
  JDK 25 emits the upstream protobuf `sun.misc.Unsafe` deprecation warning; this
  is not pinned Java 21 runtime evidence.
- Linux x86-64, Temurin 21.0.11+10, Python 3.13.5, in the existing qualification
  toolchain image: same locked generation, model/codec and nine TCP suites passed. Production
  transport/example sources pass `javac --release 21 -Xlint:all -Werror`.
- Source generation checks the shared contract against authoritative protobuf
  before comparing the committed typed bridge. No runtime JSON DTO bridge exists.
- Controlled peer payloads/identities are fixed public test values. No real
  provider/client credentials are retained in test output or this record.
- The new GetActivation NotFound regression first failed with
  `activation NotFound remains uncertain`. The corrected implementation passes
  both GetActivation and GetPolicyOperation status-5 checks with Unknown outcome
  and the original recovery IDs, rather than claiming nonexecution.
- TCP cases cover all eight calls on one connection, snapshots, full u64 counter
  maps/epochs/generations, presence, page bounds, all cancellation dispositions,
  declared/platform outcomes, known/future audit metadata with maximum u64,
  malformed/oversized protobuf, lost mutation receipt/replay, bounded admission,
  legacy cancellation, concurrent close/shutdown and blocked user callbacks.

```sh
python3 sdk/java-client/tools/build.py test
python3 sdk/java-client/tools/build.py build
javac --release 21 -Xlint:all -Werror \
  -cp 'sdk/java-client/build/classes:sdk/java-client/build/deps/*' \
  -d sdk/java-client/build/lint-classes \
  $(find sdk/java-client/src/transport/java sdk/java-client/src/example/java -name '*.java')
```

## Separate real-node qualification

The final implementation passed two consecutive executions of the unchanged
parent-owned shared runner at `916515f091c72e2f8de8aefb7d08f5d2d634a158`.
Both executions used the same built SDK JAR and the maintained signed HTTP/blob/
callee guests, not a fake client or CLI invocation bridge. The runner source and
parent binary/fixture volume were mounted read-only into a separate owned Linux
container with 2 CPUs, 3 GiB memory and 256 PIDs. Toolchain image identity:
`sha256:f9748d8e225788b858bb6a6e341308d00055bd60b7f9b5968f4ee86acfee748e`.

```sh
python3 /qualification-source/tools/run_sdk_provider_workflow.py \
  --cli /target/debug/latent --node /target/debug/latentd \
  --fixture-root /target/sdk-fixture-02 --language java \
  -- /opt/temurin-21/bin/java -jar /workspace/sdk/java-client/build/latent-java-client.jar
```

The [compact final receipt](evidence/provider-workflow.json) records all exact
CLI/node/Java/JAR/signed-fixture identities and independent cleanup observations.
The SDK JAR is 1,167,735 bytes, SHA-256
`92bec8316181f15e99f3b8c0c468963606c698d0f50d258147cd79b4c5b90645`.
Raw output SHA-256: first run
`7038c408a36cd904877e848bd8ce41acc64a6a35cb00df7eb13c063c43241a8a`;
retained second run
`6f41b161cef8d6f808d8fbaef22fb176288ef8fa693c9ae24f72e0b98ee0a1b2`.

- Both runs passed all 18 participant assertions, with 9 admitted activation
  identities and exact operation ID `java-policy-create` independently recovered.
- Upstream observations: 6 requests, all 6 authenticated, 0 unexpected requests,
  and all 4 started holds physically closed, not merely locally cancelled.
- Each real node exited cleanly and was reaped. Provider connections/jobs/
  sessions/handles, active RPCs/activations/leases/stores/instances and cleanup
  owners were zero; compiler, epoch and audit workers were joined.
- Create, receipt lookup, exact replay and rejected precondition preserve absent
  audit acknowledgement/status/attempt fields. Result `auditAttempt` is null;
  durable auditing elsewhere on the node does not invent a policy acknowledgement.
- Ordinary RPC budgets are 3000ms and held deadline 500ms; the activation fixture
  ceiling remains 5000ms. No fixture/resource ceilings were raised.

## Acceptance boundaries

The single Java transport invocation added to `tools/validate_sdks.sh` is
coordinated with the parent; Node and other language stanzas are untouched.
The SDK root support matrix and shared runner PR #366 integration remain
parent-owned. Parent review and exact-head CI must still be checked at integration;
these local results do not substitute for them. The standalone HTTP/blob example
compiles and shares the exercised native framing/configuration helpers; this
receipt executes ProviderWorkflow. The Gradle entry point was not separately
executed; the maintained locked Python build/test command was.

No installed-bundle, remote/TLS, browser, Android, Windows JDK 21 protected-file
or production-load qualification is claimed. The signed guest observations
retain their existing non-hermetic/incomplete-input and reproducibility-not-
checked declarations; Java transport validation does not upgrade their assurance.
