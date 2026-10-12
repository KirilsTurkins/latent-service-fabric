# Namespace history and live version fences

The immutable `NamespaceRecord` and namespace operation receipts retain their
version-1 bytes. Namespace incarnation and business generation keep their
existing meaning; restoring older history cannot regenerate command, effect,
caller or inbox identities.

`NamespaceHistory` is a bounded sidecar in the same namespace row family. It
binds tenant, namespace, incarnation and exact state schema to separate nonzero
schema and recovery epochs. Legacy absence means epoch 1, with an exact absent
row expectation. Ordinary engine restart preserves that epoch. A deliberate
older-history restore derives a larger recovery epoch from both the current
quiesced store and snapshot, refuses exhaustion and remains
`ReconciliationRequired` until explicit approved recovery. It cannot derive
current policy, provider credentials or permission from restored history.

The session's opaque record and namespace-view tokens bind scope, incarnation,
generation and both epochs. Their closed version-2 encoding is 67 bytes within
the existing 256-byte contract bound. An original minimum-view token requires
the same scope, incarnation and epochs and a generation at least as large.
Comparing only generations cannot establish freshness across recovery. Old
record preconditions fail after a schema/history change even when the recovered
cell bytes and generation are identical. Callers must retain their original
precondition; a conflict is not authority to refresh and retry it.

The common session owns the captured history row. `StatePlan::append_to` adds its
exact expectation to the same atomic envelope as namespace/state/outcome/effect
rows. `StateSession::view_token` describes the acquired view;
`StatePlan::view_token` describes the planned committed view. Persist the latter
with a promised result rather than substituting a current query during replay.
For a disposition with no state plan, `session::version::capture_view` exposes
the actual view identity and history expectation alongside the coordinator's
existing namespace expectation. These descriptors confer no authority.

The engine-backed epoch tests cover ordinary reopen, old row/minimum tokens,
scope mismatch, unsigned limits, malformed codecs, recovery pause and command
or no-state disposition racing history publication. Broader schema compatibility,
quiesced backup/restore and operator migration surfaces are separate required
slices of #398/#399; the epoch port alone does not complete those issues.
