# Go client qualification evidence

Scope: #260, native numeric-loopback HTTP/2 + Protobuf client. This record keeps
controlled-wire/lifecycle evidence distinct from separate real-node provider
qualification. It is not production, browser, installed-bundle, remote-node or
Go guest-runtime certification.

## Current security-remediated transport

The initial measurements below describe the earlier grpc-go/x/net transport,
not the current dependency graph. Commit `88ec3078` replaces it with the owned
Go 1.27.1 standard-library `http.ClientConn`; integration source
`c0ada12f879e18613a4070779a1638427581324a` includes current development. It uses
Protobuf 1.36.12 and the repository's small descriptor-driven unary interface
generator. No grpc-go, x/net or x/crypto module remains in the selected graph.
The earlier vulnerable graph is not exempted or claimed safe.

Parent validation on 2026-09-19 at 16:47 UTC uses the explicit Go 1.27.1 binary
in the isolated Linux/amd64 container. Regeneration checking, complete graph
reproduction, all-package tests, all-package race tests, `go vet` and participant
build pass. The complete suite has 37 top-level and 104 subcase passes; the
transport subset has 21 top-level and 90 subcase passes, including all 49 shared
wire vectors. Both real raw-TCP `REFUSED_STREAM` and unprocessed-GOAWAY peers
observe exactly one mutation header block. The ten graph-checker unit tests
also pass. The current participant SHA-256 is
`e2c4e27dcbf2b6e0c83804067d5aba696c861f1a1a02e1c6403bce7bac013bb7`.

Fresh dependency scanning at 16:48:42 UTC with controls
`de51d033469ba6c76b85b72a37f6fb8ea91c5476` and clean source `c0ada12f` reports
zero findings and zero exceptions across 285 unique coordinates in three OSV
queries. The Go subset is the three selected modules plus stdlib 1.27.1;
generator, test-only and transitive modules are not dropped. These scans are
time-bound observations, not a permanent vulnerability-free guarantee.

The current implementation still needs the separate real-node provider runner
and exact-head CI before ticket closure. The earlier participant binary and
controlled-peer results below are retained as history, not substituted for
current native qualification.

## Initial stack and reproducible setup

- Worktree: `target/phase3-260`; branch: `feat/260-bounded-go-client`.
- Implementation milestone: `482b057be70c10114a3e986b95a75702cc227d59`.
- Diagnostic graph-bound refinement: `c5975ca5`; page-presence and not-found
  regression milestone: `e5357660b81662646a739d933a28af4d11b11731`.
- Development integration base: `13d94f021dcce9bed2abf3e5231dd20f246c1312`;
  immutable-assets integration is inherited, not reimplemented by this Go ticket.
- Shared models: #227 `e40966703606d36f4443b44edb2336fcc80eea29`, including the
  independent raw audit attempt and unknown-status correction. Common model and
  other-language changes are inherited from that dependency, not edited here.
- Go 1.23.2 Linux/amd64, Buf 1.72.0; protobuf 1.36.6, grpc 1.75.1 and x/net 0.41.0
  are pinned with module checksums. Generation pins both local code generators.
- Validation ran in the isolated development container for this worktree, with
  two CPUs, 6 GiB memory and 256 PIDs; it did not use another agent's build tree.

See [the SDK instructions](../../sdk/go/README.md) for clean-checkout generation,
API and resource ownership. The build requires generation before `go test` or
`go build`; `sdk/go/internal/rpc` is intentionally ignored output.

## Executed controlled tests

Commands executed successfully on the Go implementation:

```sh
python3 sdk/go/generate.py --check
cd sdk/go
go test -timeout 30s ./... -count=1
go test -race -timeout 60s ./... -count=1
go test -race -timeout 60s ./transport \
  -run 'TestCancellationQueueAndReservedRecovery|TestConcurrentCloseReapsPendingAndQueuedCalls|TestFailedStartupAndAdoptedConnectionOwnership' \
  -count=10
go vet ./...
go build -trimpath -o target/provider-workflow ./cmd/provider-workflow
```

The final all-package race run passed: native facade, shared profile, protected
participant helpers and transport. The private generated bindings and executable
entrypoint compile in that run. Ten repetitions of the focused shared-client
cancellation/startup/Close race checks also passed. These are small deterministic
checks, not a load campaign or a universal latency promise.

The transport suite reports 18 top-level passes and 84 subtest passes, including
49 shared wire vectors. It uses actual bounded loopback TCP/HTTP/2 peers, not
only semantic test doubles. It verifies:

- Exactly the eight generated operations over one owned connection; no implicit
  pagination, replacement connection or invocation/mutation replay.
- Caller-known and server-assigned IDs, nil versus present-empty fields,
  present-zero values, full uint64 values, opaque byte/map ownership and legacy
  success/declared-error/platform-failure separation.
- All cancellation dispositions, pending status/recovery reservations (including
  a lower advertised peer stream limit), cancelled queues, finite admission,
  original deadlines and unusable/overflowing timeouts before dispatch.
- Lost mutation response after the peer has retained it, explicit original-ID
  lookup, exact manual replay and changed-document conflict. The peer records
  request counts so hidden resubmission cannot be called a recovery success.
- Fifteen malformed/oversized/header/framing cases, extra frames, compression,
  contradictory oneofs and response/header/graph/request bounds. A separate raw
  HTTP/2 `REFUSED_STREAM` peer observes exactly one request header block.
- Tonic's raw typed platform-error detail bytes, raw gRPC status, unknown signed
  management enum values and bounded unsupported invocation values.
- Audit absence, all four known textual statuses, independent zero/max-u64
  attempt values, future textual status without an invented acknowledgement,
  metadata on success and failure, and malformed/duplicate/overflowing headers.
- Forty-nine shared protocol vectors round-trip through generated authoritative
  descriptors in addition to the shared profile's native semantic vectors.
- Concurrent Close with outstanding and queued calls, failed HTTP/2 startup,
  adopted-socket ownership on both success and rejection, actual peer/socket
  retirement and no caller-visible recovery identity loss.
- Private participant input/credential permissions, authority-free policy input,
  bounded closed JSON, exact WIT framing and u64 parsing, and atomic rendezvous
  mode publication without temporary-file retention.

Only controlled test tokens are used; logs/evidence do not contain a real bearer,
provider credential, policy payload or private application payload. Test names
and bounded pass/fail output are retained rather than raw network captures.

## Separate real node: integration pending

The executable participant is implemented at `sdk/go/cmd/provider-workflow`.
The Linux/amd64 executable built after the `e5357660` refinement has SHA-256
`9f59b813794fdd653f2fa219af47b9b19769c256833839abcdd89cb75a6514dc`.
It uses only this SDK for protocol calls and is built for the shared runner's
`--config /absolute/input.json` contract. It supplies nine caller-known admitted
IDs when all checks execute (HTTP, blob, declared error, platform failure,
response limit, and four held cases), one original policy operation ID, all 18
required assertions and null audit attempt after checking actual absence.

The parent owns `tools/run_sdk_provider_workflow.py`,
`tools/sdk_provider_scenario.py`, provider/bootstrap CLI setup and the fresh
three-guest #226 fixture. That stack is deliberately not merged here just to
duplicate its setup. The first published runner contract incorrectly required
a positive audit attempt; the agreed correction is null for this current
eight-operation real-node profile. Controlled peers still test actual known and
future acknowledgements; no server audit behavior is changed by this ticket.

**No successful separate-real-node run is claimed in this record yet.** Parent
qualification must execute the Go participant with the corrected audit contract
and three signed maintained guests, retain exact executable/CLI/node/fixture
identities and independently check all admitted status records, operation
receipt, four actual upstream closes, clean process shutdown and provider-owner
reclamation. A runner implementation or compiling participant alone does not
satisfy that acceptance criterion. The Go example uses 3,000 ms RPC budgets
within the fixture's 5,000 ms cap, with a 500 ms held original deadline.

## Remaining acceptance gates

The first exact-head SDK CI job at `bdc286d1` failed before Go tests because
that job did not install Buf. The fix adds the same commit-pinned Buf setup
action/version already used by the contract job to the SDK job. Generation
requirements and checks are not weakened; a new exact-head run is required.
The complete `tools/validate_sdks.sh` then passed in the isolated Go worktree,
including generation/checking, Go tests/race checks, TypeScript, Java, .NET and
C validation. Workflow validation passed for 74 pinned/local references;
its focused unit suite ran 13 tests with one environment-dependent skip.

- Execute and review the corrected shared separate-node workflow, including
  real provider cleanup evidence; fix any participant/transport integration
  failures rather than replacing them with a fake pass.
- Coordinate the root SDK support-matrix row with the parent, distinguishing
  native Go transport from Go guest bindings and model parity.
- Review exact-head CI after the code/documentation milestones and shared-profile
  integration. Parent alone merges PRs and closes issues after full acceptance.
