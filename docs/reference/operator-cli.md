# Operator CLI

`latent` builds and inspects local packages, transfers exact package bytes through
OCI, and manages the [standalone Linux node](standalone-node.md). Node commands
connect once and send one generated gRPC request. Local paths never name the
node's catalogs, and the CLI does not execute components locally.
Start with the [scriptable echo quickstart](../development/standalone-quickstart.md)
and the [Phase 2 operator workflows](../phase-2-operator-workflows.md).

Build the binaries with `cargo build -p latent -p latentd --locked`. The existing
`make echo-capsule` build produces `echo-capsule.wasm`, `capsule.json`,
`contracts.json`, `deployment.json`, and `input.json` under `target/capsules/echo/`.
The typed metadata is checked against the component's extracted WIT; the generated
deployment names the actual component digest. Existing Phase 0 build receipts and
spike commands retain their own format and behavior.

## Commands

Every group and leaf supports `--help`. Global options can appear before or after
the command.

| Command | Behavior |
| --- | --- |
| `validate capsule FILE` | Bounded schema and Phase 1 semantic checks, without credentials or a connection. |
| `validate deployment FILE` | Local manifest checks; release-aware admission remains the node's responsibility. |
| `release publish --manifest FILE --component FILE --contracts FILE [--operation-id OP --expected-generation 0]` | Publishes raw component inputs once, optionally with a managed publication identity; the configured node admission mode still applies. |
| `release get DIGEST` | Gets one tenant-scoped release summary. |
| `release list [--service S] [--page-size N] [--page-token TOKEN]` | Returns one release page. |
| `deployment apply FILE [--expected-generation N] [--operation-id OP --expected-state-version S]` | Applies once. Managed mode requires both operation flags and an explicit object generation. |
| `deployment get ID [--operation-snapshot]` | Gets the canonical manifest/object version; opt in to one coherent global state/route/durability snapshot, including for an absent object. |
| `deployment list [--service S] [--page-size N] [--page-token TOKEN]` | Returns one deployment page. |
| `deployment delete ID [--expected-generation N] [--operation-id OP --expected-state-version S]` | Deletes without a preliminary read. Managed mode requires a positive object generation and returns operation/audit metadata. |
| `deployment operation OP` | Looks up the tenant's bounded retained managed-operation receipt; unknown does not prove absence of execution. |
| `route get [--generation N]` | Gets the current tenant route projection; unavailable generations are not found. |
| `invoke --service S --contract C --function F --input FILE` | Invokes once using the selected profile tenant. Additional options are below. |
| `activation get ID` | Gets bounded retained lifecycle/status information. |
| `activation cancel ID [--reason TEXT]` | Preserves `accepted`, `already_terminal`, or `not_found`. |
| `node get ID` | Gets operator-authorized node inventory. |
| `node list [--trust-class C] [--region R] [--zone Z] [--page-size N] [--page-token TOKEN]` | Selects the standalone node and returns its actual inventory. |

Package commands use explicitly supplied local files and a separate OCI profile:

| Command | Behavior |
| --- | --- |
| `package build --source FILE --input-root DIR --output-dir DIR [--sbom-inputs FILE]` | Packages selected existing bytes and optional SBOM inventory. Does not compile source, run scripts, sign, or manufacture provenance. |
| `package inspect DIR` | Checks exact package inventory, digests and supported semantics; does not establish trust. |
| `package verify DIR --evidence-index FILE --evidence-root DIR --policy FILE --tenant TENANT` | Checks publisher, builder, SBOM and tenant using an explicit local policy; returns a diagnostic report without execution authority. |
| `package push DIR --registry-profile FILE --reference REF [--evidence-index FILE --evidence-root DIR]` | Publishes exact package and selected referrers. Evidence flags must be supplied together. |
| `package pull --registry-profile FILE --reference REF --output-dir DIR --evidence-output DIR` | Resolves a tag once, then exports its immutable package and selected evidence into new directories. |

Release lifecycle commands use the node's current policy and catalog:

| Command | Behavior |
| --- | --- |
| `release publish-package DIR [--evidence INDEX] --operation-id OP --expected-generation 0` | Submits a checked package and explicit evidence to node admission. Omitted evidence means no detached evidence. |
| `release lifecycle DIGEST` | Reads current lifecycle state and generation. |
| `release operation OP` | Reads the tenant's retained publication/lifecycle operation outcome. |
| `release revoke DIGEST --operation-id OP --expected-generation N` | Explicit operator revocation at an exact positive lifecycle generation. |
| `release retire DIGEST --operation-id OP --expected-generation N` | Explicit operator retirement at an exact positive lifecycle generation. |
| `release renew-evidence DIGEST --package-digest SHA --evidence INDEX --operation-id OP --expected-generation N` | Rechecks new evidence against the stored exact package; does not replace component bytes. |

For publication/renewal, evidence paths resolve below the index file's parent.
The index must be a file, not standard input. Local `package verify` and OCI push
instead take an explicit evidence root. See the [evidence and registry formats](../phase-2-operator-workflows.md#local-packages-and-evidence).

Rollout operations retain their own revision and operation identity:

| Command | Behavior |
| --- | --- |
| `rollout start ID --base ID --expected-base-generation N --candidate FILE --weights 2500,5000,10000 --operation-id OP --expected-revision 0 [--canary-policy FILE]` | Starts one bounded base/candidate rollout with explicit increasing weights ending at 10000. |
| `rollout get ID` | Reads the rollout, including its exact rollback target when available. |
| `rollout list [--service S] [--state STATE] [--page-size N] [--page-token TOKEN]` | Returns one bounded page. |
| `rollout operation ID OP` | Looks up an exact retained rollout operation. |
| `rollout advance ID --operation-id OP --expected-revision N --next-step N` | Advances a manual rollout one stage; cannot bypass a canary policy. |
| `rollout pause ID --operation-id OP --expected-revision N` | Pauses coordination while retaining route weights. |
| `rollout resume ID --operation-id OP --expected-revision N` | Revalidates and resumes at the same declared step. |
| `rollout abort ID --operation-id OP --expected-revision N` | Stops coordination; it does not restore old traffic weights. |
| `rollout evaluate ID --expected-revision N` | Returns diagnostic canary evidence without changing routes. |
| `rollout promote ID --operation-id OP --expected-revision N --next-step N` | Uses the node's complete, exact-cohort canary evidence to authorize the next stage. |
| `rollout rollback ID --operation-id OP --expected-revision N --target-generation N` | Restores the recorded pre-Start target through a fresh eligible publication; the historical target generation is not the new route generation. |
| `audit query [--scope tenant\|node] [--kind KIND] [--actor ACTOR] [--from-unix-millis N] [--to-unix-millis N] [--page-size N] [--page-token TOKEN]` | Reads one authorized typed audit page, filtering durable accepted-at timestamps. |

There is no automatic pagination, cursor restart, retry, stale-precondition
replacement, operation-ID generation, or hidden reconciliation request. Source
compilation, signing/key creation, policy mutation, watch, cluster registration,
and benchmark commands remain outside this CLI. General capability providers,
HTTP/web hosting and expanded SDK transports belong to Phase 3; durable service
state, transactional effects and clustering remain later phases.

## Credentials and limits

Node RPC commands require an explicit `--config FILE`. The CLI performs no automatic
directory search or environment-based credential selection. Keep this JSON file
private; tokens have no command-line flag and are never printed in diagnostics.

```json
{
  "formatVersion": 1,
  "defaultProfile": "local",
  "profiles": [{
    "name": "local",
    "endpoint": "http://127.0.0.1:50051",
    "tenant": "examples",
    "token": "REPLACE_WITH_THE_PRIVATE_NODE_CONFIGURED_TOKEN",
    "connectTimeoutMillis": 2000,
    "rpcTimeoutMillis": 1000,
    "limits": {
      "maximumComponentBytes": 16777216,
      "maximumPayloadBytes": 1048576,
      "maximumResponseBytes": 4194304
    }
  }]
}
```

Choose `--profile NAME`, otherwise `defaultProfile`, otherwise the sole profile.
Multiple profiles without a selection fail locally. `--endpoint`, `--tenant`,
`--connect-timeout-ms`, and `--rpc-timeout-ms` override the selected nonsecret
values. The profile tenant selects invocation targets and must match publication
and deployment manifests; the node's authenticated credential remains authoritative.
An operator credential supports inventory and the tenant's management/invocation
calls. Lesser roles retain the permissions described in the node reference.

Endpoints must be literal loopback HTTP addresses with a positive port, such as
`http://127.0.0.1:50051` or `http://[::1]:50051`. DNS, non-loopback addresses, TLS,
paths, redirects, queries, fragments, and userinfo are not accepted. Credentials
use the node's 32–256-byte ASCII token vocabulary and become one Bearer header.

Configuration is limited to 64 KiB, 16 profiles, depth 16, and bounded structural
counts. Unknown/duplicate fields, duplicate names, unsupported versions, and
invalid integer values fail locally. Timeouts allow 1–300000 milliseconds.
Component input defaults to 16 MiB and permits at most 64 MiB; payload input is
at most 1 MiB; response input defaults to 4 MiB and permits at most 16 MiB. All
three limits must be positive. Response HTTP/2 headers are bounded to 16 KiB;
typed error details are decoded only within 8 KiB. The node's independent limits
still apply.

Package build/inspect/verify need no node credential. OCI push/pull use
`--registry-profile FILE`, separate from node tokens: a fixed origin/repository,
explicit numeric addresses and optional credential/CA files below the profile's
parent. HTTPS is required except explicitly configured loopback fixtures.
Transfers use one absolute `--rpc-timeout-ms` allowance (default 60000 ms), with
separately bounded cleanup; a partial multi-referrer push is not a transaction.
See [OCI transfer](../phase-2-operator-workflows.md#oci-transfer).

Package layers are bounded to 16 MiB each and 32 MiB in total. Detached evidence
has a separate 16 MiB ceiling, at most eight entries per kind and a 16 KiB index.
Build/pull output directories must be new. The package manifest and the separate
evidence index are published last; partial output is not reported as complete.

Manifest and contract documents are each bounded to 1 MiB. Identifiers are at most
512 bytes; invocation metadata allows 64 unique keys and 32 KiB in total; cancel
reasons allow 256 bytes. Operation and rollout IDs are at most 128 bytes. Release,
deployment and node page sizes are 0–1000, with zero selecting the node's
default; rollout and audit pages allow 0-128. Continuation tokens are opaque and
at most 8192 bytes. A catalog mutation or reopen can expire them; the CLI reports the error instead of restarting a list.
`-` means standard input for file inputs and may be used only once per command.
Readers enforce actual bytes read rather than trusting file metadata alone.

## Versions, identity, and execution

Without `--operation-id`, deployment apply/delete keeps the legacy contract:
omitted `--expected-generation` is unconditional, zero requires absence, and a
positive integer compares the live object's exact version. Legacy Delete with
zero conflicts when present and is not found when absent.

Managed Apply/Delete adds an explicit `--operation-id`, `--expected-state-version`
and `--expected-generation`. Delete requires a positive object generation; Apply
uses zero to create an absent object. First read `deployment get ID --operation-snapshot` to obtain the object and global state version together.
The node requires configured audit and never silently falls back to legacy mode.
Actor and tenant come from authenticated credentials, not caller-supplied identity
fields. See the [managed receipt contract](../phase-2-operator-workflows.md#managed-deployment-receipts).

Keep the original operation ID and exact request. A retained exact replay returns
the original receipt before current-state or execution checks and does not mutate
routes or restore a revoked release. Changed request fields conflict. The default
deployment receipt ring has 256 slots, so lookup can become Unknown after eviction.
The global state precondition prevents an evicted creation from running again after
a later deletion; unrelated catalog changes can also cause an explicit conflict.
Read and reconsider that conflict before choosing a new operation.

Release lifecycle generation, deployment object generation, catalog state version,
route generation and rollout revision are distinct. Rollback requires the recorded
historical target generation and publishes a newer route generation. Old rollout
rows without a captured target remain readable but cannot accept a new rollback.
Pause/abort, receipt lookup and diagnostic evaluation never imply that traffic was
restored or a release became eligible.

Audit results are separate from catalog durability. A lost response or unknown
terminal audit acknowledgement does not undo a committed mutation. Query the
original release, deployment or rollout operation explicitly. Unknown includes
missing/evicted history; Uncertain indicates that durable confirmation is absent.
Audit pages may be empty with a continuation because scan work is bounded. Preserve
the returned cursor and coverage, including previous-session loss uncertainty; the
CLI neither restarts the query nor claims a complete history from an empty page.

Invoke supports `--route`, `--activation-id`, `--root-activation-id`,
`--parent-activation-id`, `--media-type`, `--deadline-unix-millis`, `--priority`,
`--idempotency-key`, repeated `--metadata KEY=VALUE`, `--budget FILE`, `--cpu-fuel`,
`--memory-bytes`, `--wall-time-ms`, `--log-bytes`, and `--payload-output FILE`.
Priority is 0–255. Duplicate metadata keys fail. An absent activation ID requests
server assignment; an explicitly empty ID fails. Supplied lineage is preserved,
parent requires root, and lineage does not confer authority. Idempotency metadata
does not promise redispatch deduplication. The server supplies a fresh trace and
retry attempt zero.

The default payload media type is `application/vnd.latent.wit-values.v1+json`.
Inputs are positional arrays, for example `["hello"]` for echo. The
[canonical WIT value mapping](../protocol/wit-values.md) defines integer strings,
tagged options/results/variants, and composite values. The node validates the
actual export types; the CLI does not infer Phase 0 text dispatch from payloads.

Budget files use the resource budget's camelCase JSON fields. Omitted fields use
CPU fuel `100000000`, memory `67108864`, log bytes `16384`, no relative wall limit,
and zero for later-phase dimensions. Present scalar flags override the corresponding
file values. Explicit zero remains zero, including wall time. Nonzero child calls,
outbound requests, state/blob access, and effects remain unsupported by the current
standalone execution profile. These request ceilings are intersected with capsule, deployment, and node grants.

One monotonic RPC allowance starts after local preflight and covers connection
and response waiting. Connection also obeys its smaller configured ceiling. An
explicit absolute invocation deadline can tighten the allowance and is forwarded
unchanged; it cannot extend server limits. A cold compilation can exhaust a short
allowance, so configure client and node time ceilings deliberately.

Ctrl-C drops the client future and exits 130. It does not send a hidden Cancel or
claim server cancellation was accepted. Use a second process to explicitly cancel
or query a known activation ID while the first call is pending. After a lost
server-assigned receipt, identity can be unavailable. Not-found status can also
mean eviction, restart, or foreign scope; it never proves that no work ran.

For the measured budget and cold-preparation limits, see the
[extension guidance](../phase-1-extension-completion.md#tuning-and-closure).
A successful warm-call percentile is not a cleanup deadline or a reason
to retry an invocation whose outcome is unknown.

## Output and exits

`--output json` emits one bounded JSON document and newline on stdout. Help and
version remain ordinary text. Syntax/profile/input failures also use the JSON
envelope when JSON output was selected. `--quiet` is a human-output option and
cannot be combined with JSON; it suppresses optional success chatter while
preserving explicitly requested invocation output. Human returned data goes to
stdout, including failed-operation data; fixed diagnostics go to stderr. Untrusted
text is quoted/escaped rather than rendered as terminal control sequences.

```json
{
  "schemaVersion": "latent.cli.result.v1",
  "command": "deployment get",
  "category": "not-found",
  "data": {"deployment": null, "stateVersion": null, "routeGeneration": null, "durability": null},
  "error": null,
  "requestDispatched": true,
  "outcomeKnown": true
}
```

Every `u64` version, timestamp, size, and consumption value is a decimal JSON
string; `u32` counts remain integers. Canonical manifest objects preserve their
schema-defined numeric budget representation. Missing optional values are null.
List data contains items and `nextPageToken`, without fabricated totals or catalog
versions. New typed lifecycle, rollout and audit enum values preserve canonical
protobuf enum names; CLI categories and explicit durability strings keep their
own documented spellings. Release locators remain opaque and are not client paths.
A publication timestamp of `"0"` reflects the wire's unavailable timestamp; `admitted:true`
means catalog validation passed, not that an invocation has run.

Invocation data preserves `activationId`, optional `resolvedRevision`, and final
consumption. Success includes `payload` with `encoding:"base64"`, `mediaType`,
`data`, and decimal `byteLength`. Declared errors preserve their typed payload and
use a separate category. Pre-resolution failures have a null revision pin. Status
keeps spellings such as `completed` and `deadline_exceeded`; cancellation keeps
its exact disposition. These differ from hyphenated platform error codes.

`--payload-output FILE` creates a new file containing successful returned bytes;
existing files are never overwritten. Failure to write after completion reports
local-error while preserving the remote receipt and `data.remoteCompleted:true`.
It does not make the remote invocation unexecuted.

| Exit | Category | Meaning |
| --- | --- | --- |
| 0 | `success` | Validation/read/mutation success, returned guest success, or accepted/already-terminal cancellation. |
| 2 | `local-error` | Arguments, profile, input, or local output failure. |
| 3 | `declared-error` | Declared guest result with typed error payload and consumption. |
| 4 | `platform-failure` | Valid explicit platform outcome or definitive application rejection. |
| 5 | `transport-failure` | Connection, timeout, malformed response, or ambiguous transport failure. |
| 6 | `not-found` | Absent optional read, explicit not-found response, or Cancel not-found. |
| 130 | `interrupted` | Local interruption, with no fabricated cancellation acknowledgment. |

`requestDispatched:false` records failure before a call was submitted.
`outcomeKnown:false` warns that a submitted mutation or invocation may have run.
The client never retries, even when an explicit platform error says retryable.
Validated `committed:true` legacy deployment details preserve commit evidence.
Managed Apply includes the compact receipt, replay flag, durability and audit
acknowledgement. Managed Delete keeps an Empty protobuf body and projects its
bounded operation/audit metadata; `deployment operation OP` returns the full
receipt. On uncertain control responses, `data.recovery` retains the caller's
selectors and tenant for an explicit lookup, without issuing that request. Raw
status messages, paths, credentials, arbitrary platform diagnostics, and backtraces are excluded from error output.

Malformed/unknown contracts are protocol failures. Bare ResourceExhausted or
OutOfRange statuses are conservatively transport failures because local message
limits can produce them. Valid bounded structured platform details retain their
typed classification. See [validation tiers](../../VALIDATION.md) for the bounded
CLI/unit/real-process tests. The separate
[Phase 1 completion report](../phase-1-completion.md) records the completed
scaling, reclamation and integrated conformance gate.
