# Separate-node SDK provider workflow

The shared harness runs **one language-native participant against a separate
real `latentd` process**. It reuses the Phase 3 management fixture, protected
provider bootstrap and authenticated CLI setup; SDK calls do not invoke CLI
internals or a handwritten JSON/RPC proxy. Each run owns one finite node,
operator setup client, participant and controlled HTTP upstream. It is a
Linux x86-64 development qualification, not an installed-bundle or browser test.

Implementation is staged: the harness alone is not passing real-node evidence.
Each language must implement the complete participant contract and execute it
successfully before its SDK ticket can close. Controlled malformed-wire peers
remain separate focused tests; this runner does not pretend that malformed
responses came from the real node.

## Inputs and authority

Build the maintained Rust/C guests using `tools/build_guest_capsules.py` and
export the signed fixture with the registered `phase3_workflow_fixture` test.
Its fresh evidence must include `rust-http`, `rust-blob` and `rust-callee` under
the same protected publisher/builder policy. The real node enforces package
admission and exact publication/deployment associations. HTTP uses a bounded
static loopback provider destination, one protected upstream credential and an
exact `/allowed` grant. Blob access uses the node-owned immutable `workflow`
namespace. The callee needs no provider grant and supplies a real declared
application error via its maintained `fail` export.

The client credential is the explicit, publicly labelled **test-only** operator
token in a private 0600 file under a 0700 directory. It is not an upstream/provider
credential, is not passed on argv, and must not become a deployment default.
The participant receives only the node's numeric loopback endpoint, its client
credential path, exact guest targets and a private rendezvous directory.

```sh
python tools/run_sdk_provider_workflow.py \
  --cli /absolute/latent --node /absolute/latentd \
  --fixture-root /absolute/fresh-signed-inputs --language rust \
  -- /absolute/sdk-provider-participant
```

The command after `--` is an explicit executable plus at most 15 arguments;
the runner appends `--config /absolute/input.json`. Language runtimes may be
explicit arguments, for example an absolute `node` and absolute participant
module. Executable/module identities, CLI/node hashes and exact signed guest
fixture identities are retained in the bounded final evidence.

## Participant input

The input's `schemaVersion` is `latent.sdk.provider.workflow.input.v1`. It has
`language` (`rust`, `typescript`, `go`, `c`, `java` or `dotnet`), `endpoint`,
`tenant`, `credentialFile`, `controlDirectory`, `upstreamUrl`, `policyDocument`
and `targets`. Target keys are `http`, `blob` and `callee`; each contains
`service`, `route`, `contract`, `function`, `publication`, `componentDigest`.
No `uint64` value is serialized as a potentially lossy JSON number here.

HTTP/blob use `run(which: u32, text: string, handle: u64)` with the supported
WIT-value media type `application/vnd.latent.wit-values.v1+json` and arguments
`[0, URL, "0"]` / `[0, "", "0"]`. HTTP returns `["2201"]` for the fixture's
201 response plus two body bytes; blob returns `["4"]`. Callee `answer`, `fail`
and `spin` have no input arguments. Its contract is `tests:local/api@1.0.0`.
Use the deployed profile's finite budgets, never direct provider access.
The node's five-second execution maximum also bounds the incoming gRPC timeout:
select an RPC timeout at most 5,000 milliseconds, rather than inheriting a
longer SDK default. Held calls use 3,000 milliseconds, except the explicit
500-millisecond deadline case. Do not increase the node ceiling to make an
incorrectly configured client pass.

Choose caller-known activation IDs prefixed with `LANGUAGE-`. Retain every
actually admitted ID in the final result; do not include IDs rejected before
admission (wrong tenant or credential). Choose `LANGUAGE-policy-create` for
the explicit operation ID. The policy document is an empty rule set that grants
no execution authority; create uses the explicit generation precondition zero.
Verify its observed receipt, lookup and exact manual replay, then reject an
incompatible replay/precondition rather than silently changing it.
The current policy RPC emits no audit acknowledgement, as specified by the
shared client profile. Assert that acknowledgement, raw status and attempt
sequence remain absent. Durable node auditing for other operations does not
create a policy acknowledgement. Controlled transport tests independently
exercise known, uncertain and future audit metadata with full-width attempts.

## Controlled pending operations

The participant atomically replaces `controlDirectory/mode` with either `reply`
or a unique `hold-<lowercase-token>` (token length at most 48, letters/digits/
hyphens). Use a temporary file plus same-directory rename so partial writes
cannot look like a valid command. This is a private test rendezvous, not a
production client API or authority grant.

For an authorized `/allowed` request in hold mode, the upstream consumes the
bounded complete request and creates `started-hold-TOKEN`. This marker proves
the provider operation actually started. The participant may now abort its
local wait, explicitly cancel the caller-known activation, await an original
absolute deadline, or shut down its client with outstanding work. Those are
four distinct cases, with four unique hold tokens.

The upstream sends no response in hold mode. It creates `closed-hold-TOKEN`
only after it observes EOF or reset on the actual provider connection. A
three-second watchdog is failure, not proof of closure. Wait for the marker,
observe the original activation's retained terminal status using a fresh live
context/client when necessary, and restore `reply` before the next case.
An abort is not an automatic `Cancel` RPC: the current node may independently
cancel on transport loss, so an explicit later cancel may validly report
already-terminal. Never report local wait cancellation as proven guest cleanup.

## Required result and independent checks

The participant exits zero with one JSON line and no stderr. Its schema is
`latent.sdk.provider.workflow.result.v1`, with exactly `language`, `assertions`,
`activationIds`, `operationId`, `auditAttempt`, `transport` and `schemaVersion`.
`transport` is `numeric-loopback-http2-protobuf-v1`; `auditAttempt` is `null`
when absent, or an actually observed positive canonical decimal `uint64`
string when supplied. Current policy calls must retain `null`, never invent
an attempt from the operation ID or node audit counters. Keep 6–16 unique admitted
activation IDs and no private payloads, credentials or diagnostics.

Every following assertion is required and must represent an executed check:
`httpGuest`, `blobGuest`, `declaredError`, `platformFailure`, `wrongTenant`,
`wrongCredential`, `boundedPages`, `providerInspection`, `mutationReceipt`,
`exactReplay`, `preconditionConflict`, `localCancellation`, `explicitCancellation`,
`lostResponseStatus`, `absoluteDeadline`, `responseLimit`, `shutdownOutstanding`,
`clientOwnersReaped`.

The harness independently checks all retained activation IDs through the real
operator API, the mutation operation receipt, four started/physically closed
upstream holds, provider credential use, no unexpected upstream requests,
actual participant process retirement and the node's real clean shutdown with
provider owners reaped. Node terminal retention is explicitly 32 entries/120
seconds, not indefinite history. A missing retained record cannot be turned
into proof of nonexecution or silently skipped.

All subprocesses use the maintained unreaped-group owner with finite output,
time and cleanup limits. The runner deadline is 240 seconds; the participant
gets at most 90 seconds. Result output is at most 32 KiB, cumulative participant
output 64 KiB and the final evidence 64 KiB. These small deterministic checks
are not load campaigns, universal latency claims or production certification.
Failure reporting accepts only a bounded structured participant stage/reason
token and finite category/gRPC code. Arbitrary stderr, server messages and
additional fields are not copied into operator diagnostics.

## Current native-client checkpoint

The [2026-09-19 native-client checkpoint](../evidence/phase3-sdk-native-checkpoint.json)
records fresh Java and C executions at integration `3584f589`. Both passed all
18 participant assertions, retained nine actual activation identities and the
original mutation operation, and independently closed all four started upstream
holds. Each peer observed six authenticated requests and no unexpected requests;
both nodes and clients were reaped with clean provider shutdown. The current
Java SDK tree matches reviewed `c8229d5a`; C matches `bf466a53`. Original
raw-receipt hashes and exact executable/fixture identities distinguish these
executions from earlier receipts.

The subsequent Go attempt failed during shared-node startup, before the native
participant launched. It is not a successful Go run, a client transport failure,
or evidence of a completed matrix. Diagnosis of the intermittent
`startup-resource-exhausted` result remains under the provider integration.
The new audit-recovery regression fixes an independently demonstrated startup
defect but does not by itself explain or close this remaining failure. Current
combined Rust/Node revalidation, .NET participant execution and the maintained
six-language CI matrix also remain required. No failed attempt is overwritten
or silently retried into a passing claim.
