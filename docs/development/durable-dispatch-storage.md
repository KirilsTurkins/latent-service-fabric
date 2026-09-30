# Durable dispatch storage

The atomic command envelope stores the committed `EffectRecord`, its exact
`PayloadRecord` and initial due index in one engine batch. These records retain
command, commit, caller, namespace incarnation and payload linkage without a
guest instance. Publication state-schema changes do not reinterpret payloads.

The selected profile is unordered. Sequence identifies an intent within its
command; it grants no ordering or predecessor-skipping behavior. Ordered mode
requires a separately supported profile and is rejected by the dispatcher.

## Closed initial formats

| Family | Key | Value |
| --- | --- | --- |
| Outbox | `effect-v1\0` + raw 32-byte effect identity | Existing checked `LER\0\x01` effect record |
| PayloadReference | `effect-payload-v1\0` + raw effect identity | `LEP\0\x01` + raw effect identity + LE u32 canonical Value length + canonical Value |
| Maintenance | `dispatch-due-v1\0` + BE u64 due milliseconds + raw effect identity | `LDI\0\x01` + BE u64 namespace incarnation + BE u64 claim generation |
| Maintenance | `dispatch-owner-v1\0` | `LDO\0\x01` + BE u64 process epoch + BE u64 trusted clock floor |
| Attempt | `dispatch-history-v1\0` + raw effect identity + BE u64 history sequence | `LDH\0\x01` + bounded receipt/attempt JSON, at most 4 KiB |

The initial due time is the immutable authority's committed time, and initial
claim generation is zero. Big-endian time and binary identity make finite prefix
pages sort by due time, then effect identity. Guest strings never select an
engine family or construct an index; scope comes from the captured authority.

Canonical Value bytes are `LEV\0\x01`, LE u32 payload length and binary payload,
LE u16 media-type length and UTF-8 media type, LE u16 metadata count, then sorted
metadata entries. Each entry uses LE u16 key length/key and LE u16 value
length/value. Metadata names sort by UTF-8 bytes; duplicate or noncanonical
encoded names fail decoding. Digest is SHA-256 of
`lsf-effect-payload-v1\0` followed by these exact canonical Value bytes.

Payloads retain the contract's 1 MiB body, 128-byte media type, 32 metadata pairs
and 8 KiB combined metadata bounds. Decoder limits/counts/types/trailing bytes
are checked before application buffers are allocated. The row key binds the
decoded effect identity, and retrieval also calls `PayloadRecord::verify` against
the immutable authority's payload length/digest. A decoded record grants no
current dispatch authority. Unsupported record versions fail visibly.

`dispatch_store::validate_row` validates only its closed outbox, payload and due
prefixes; other namespace/command/maintenance codecs remain responsible for
their own rows. Full dispatcher startup must also verify cross-row linkage and
recover interrupted claims under exclusive process ownership before readiness.

## Integration ports

`payload_digest(&Value)` lets the command coordinator capture immutable payload
identity. `PayloadRecord::new` verifies that authority and returns the retained
binary row. `effect_row_key`, `effect_payload_key` and `initial_due_mutation`
produce the shared store's exact keys/mutation. The coordinator includes every
row in its atomic state/result/outbox/payload boundary; an independently appended
outbox is not a transactional guest path.

The borrowed `DispatchCatalog` runs inside fixed storage jobs. Claim CAS consumes
the exact due row, advances the record's attempt/generation and fences the node
epoch. A durable send marker precedes physical dispatch. Completion replaces the
outbox and appends one history row atomically; stale or duplicate completions
cannot overwrite an active or terminal disposition. Qualified retries alone add
another due row under the same stable effect/payload/provider identity. Unsafe
retry proofs preserve the actual uncertain receipt.

Startup advances the process epoch under exclusive store ownership, then checks
cross-row linkage and recovers finite outbox pages. A persisted send marker means
uncertain provider acceptance. Recovery before that marker is known nonexecution
only after affirmative old-process physical retirement. An admitted protected
external checkpoint rejects epoch/clock rollback on restore; wall time alone
cannot synthesize continuity. Process epochs never change business namespace
incarnation or command identity.

The focused tests prove canonical identity/tamper rejection, bounded malformed
decoding, due ordering, actual atomic snapshot/reopen, stale receipt fencing,
send/claim restart boundaries, qualified retry, bounded history, policy/expiry,
clock regression and older-checkpoint rejection. Fixed provider workers and
standalone node lifecycle remain the ongoing #391 implementation.

Measured on 2026-10-01: all 34 effect tests passed on Windows and the pinned
Linux Rust 1.97.1 image, with strict all-target/all-feature Clippy on both hosts.
The exact Linux test discovery is registered in the existing workspace suite.
