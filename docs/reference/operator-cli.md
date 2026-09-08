# Operator CLI

`latent` is the Phase 1 client for the [standalone Linux node](standalone-node.md).
It validates local inputs, connects once, and sends one generated gRPC request per
remote command. It does not open the node's catalogs or execute components locally.
Start with the [scriptable echo quickstart](../development/standalone-quickstart.md).

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
| `release publish --manifest FILE --component FILE --contracts FILE` | Checks tenant, typed exports, and exact component hash, then publishes once. |
| `release get DIGEST` | Gets one tenant-scoped release summary. |
| `release list [--service S] [--page-size N] [--page-token TOKEN]` | Returns one release page. |
| `deployment apply FILE [--expected-generation N]` | Applies a manifest with the exact optional object-version precondition. |
| `deployment get ID` | Gets the canonical deployment manifest and its object version. |
| `deployment list [--service S] [--page-size N] [--page-token TOKEN]` | Returns one deployment page. |
| `deployment delete ID [--expected-generation N]` | Deletes once, with no preliminary read. Successful response data is `{}`. |
| `route get [--generation N]` | Gets the current tenant route projection; unavailable generations are not found. |
| `invoke --service S --contract C --function F --input FILE` | Invokes once using the selected profile tenant. Additional options are below. |
| `activation get ID` | Gets bounded retained lifecycle/status information. |
| `activation cancel ID [--reason TEXT]` | Preserves `accepted`, `already_terminal`, or `not_found`. |
| `node get ID` | Gets operator-authorized node inventory. |
| `node list [--trust-class C] [--region R] [--zone Z] [--page-size N] [--page-token TOKEN]` | Selects the standalone node and returns its actual inventory. |

There is no automatic pagination, cursor restart, retry, stale-generation
replacement, invocation-ID generation, or hidden reconciliation request. Build,
OCI packaging, signing, policy management, durable state, cluster registration,
watch, and benchmark commands are outside this CLI surface.

## Credentials and limits

Remote commands require an explicit `--config FILE`. The CLI performs no automatic
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

Manifest and contract documents are each bounded to 1 MiB. Identifiers are at most
512 bytes; invocation metadata allows 64 unique keys and 32 KiB in total; cancel
reasons allow 256 bytes. Page sizes are 0–1000, with zero selecting the node's
default. Continuation tokens are opaque and at most 8192 bytes. A catalog mutation
or reopen can expire them; the CLI reports the error instead of restarting a list.
`-` means standard input for file inputs and may be used only once per command.
Readers enforce actual bytes read rather than trusting file metadata alone.

## Versions, identity, and execution

For deployment apply/delete, omitted `--expected-generation` is unconditional;
zero requires absence; a positive integer compares the live object's exact version.
Delete with zero therefore conflicts when present and is not found when absent.
Apply data contains `{ "deployment": { "generation": "...", "manifest": {...} },
"warnings": [...] }`. Delete has no version receipt on the wire, so the CLI does
not invent one. Read and reconsider a conflicting object before issuing a new
mutation. See [management semantics](management-services.md).

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
outbound requests, state/blob access, and effects are rejected in Phase 1. These
request ceilings are intersected with capsule, deployment, and node grants.

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
  "data": {"deployment": null},
  "error": null,
  "requestDispatched": true,
  "outcomeKnown": true
}
```

Every `u64` version, timestamp, size, and consumption value is a decimal JSON
string; `u32` counts remain integers. Canonical manifest objects preserve their
schema-defined numeric budget representation. Missing optional values are null.
List data contains items and `nextPageToken`, without fabricated totals or catalog
versions. Release locators remain opaque and are not client paths. A publication
timestamp of `"0"` reflects the wire's unavailable timestamp; `admitted:true`
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
Validated `committed:true` deployment details preserve commit evidence, without
reconstructing a later receipt. Raw status messages, paths, credentials, arbitrary
platform diagnostics, and backtraces are excluded from error output.

Malformed/unknown contracts are protocol failures. Bare ResourceExhausted or
OutOfRange statuses are conservatively transport failures because local message
limits can produce them. Valid bounded structured platform details retain their
typed classification. See [validation tiers](../../VALIDATION.md) for the bounded
CLI/unit/real-process tests. This surface does not establish the heavy Phase 1
completion evidence tracked by #16.
