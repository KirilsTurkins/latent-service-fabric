# Current POST recipient and Java compiler custody

The current deferred HTTP recipient is a separate finite synthetic fixture for
`lsf-atomic-idempotent-http-v1`. The historical PUT provider, its keys, wire
headers, reports and approvals remain unchanged. This packet supplies current
transport and compiler inputs to #970/#718; it does not claim signed Java
execution, recipient delivery, packaged release approval or complete ticket
acceptance.

`tools.java_transaction_qualification.current_recipient` accepts an explicit
endpoint declaration, TLS directory and complete authorization-value file.
The fixed current declaration uses HTTPS `localhost:52027`, POST `/effect`, GET
`/effect` for profile inspection and GET `/receipts/lsf-effect-{hex}` for lookup.
Its endpoint incarnation is 64 `e` characters, retention is 600000 ms, payload
is at most 27 bytes and JSON replies are at most 2048 bytes. The server retains
at most 32 immutable acceptance records, 64 requests and 96 connections across
at most three clean sessions. Every process has the original finite deadline.
Neither this fixture nor its declaration grants platform authority.

The actual TLS control first obtained the profile and an absent lookup, then
denied a wrong credential. It fsynced one mutation before deliberately losing
the reply on the real connection. Lookup recovered that exact acceptance;
duplicate POST returned the original sequence, while changed bytes under the
same identity produced conflict without rewriting the record. A separately
started process reopened the same durable recipient, looked up and deduplicated
again. The final cumulative observation retained one mutation and one record,
two duplicate POSTs and one lost reply. Both processes reaped successfully with
zero active connections or worker threads and closed listeners. These are
external synthetic transport observations, not platform commitment or delivery.
All nine independent current-recipient source controls passed on Windows and
Linux. Earlier 4096-byte r1 transport evidence stays separate; the current native
profile and captures use only the explicitly narrowed 27-byte r2 declaration.

The native `latentd inspect-configured-http-effects --config` command constructed
the real installed provider and adapter from that fixed r2 declaration. Its
actual output selected `qualified-http-effect-v1`, `http-body-value-v1`, intent
format 1 and idempotency profile
`qualified-http-v1:96de426fb7aebd66c97033631e9aec1f85d4eac11f581637e67b7f25239bd161`.
The exact binary and configuration identities are retained in the packet.
No business or checkpoint file, publication or grant was created by preview.
The constructor-derived profile is an input identity and creates no approval.
That r4 binary was built with all features, including development outbound
streams and test-node support, from an uncommitted gateway overlay. Its exact
binary and configuration are known; a committed full source-tree identity is
not established for those earlier bytes. It is neither ordinary-default native
qualification nor source-approved runtime evidence. A fresh committed native
tuple, matching constructor preview and current policy receipts remain required
before the combined signed campaign uses these inputs.

Six actual Java captures used one clean source commit
`9bae83952d9513c965a88d375b2a533916a98473`, tree
`629d64a235c73721bfe7b6dc450b6e233aeafcae`. The maintained compiler CLI ran with
the explicit pinned read-only cache, JDK 25.0.4, Gradle 9.1.0, TeaVM 0.15.0,
WASI SDK 29 and unchanged WIT/engine contracts. Real Git commit/tree objects and
explicit shallow history boundaries established the compiler's original
source-revision and clean-status checks; no reported field was rewritten.
Aggregate and forbidden immediate-HTTP inputs carry no current-effect marker.
Legacy, compatible, writer and post-stage diagnostic inputs carry the exact
current profile marker and operation `http`. They retain the original 27-byte
payload, 2048-byte response, three-attempt, 600000-ms age and 2000-ms attempt
ceilings. The old `put-once-*` variant labels remain report identities; the
explicit current marker and effect fields distinguish their new source bytes.

Every actual component was copied exclusively from its reported
`compiled/component.wasm` output after verifying digest and byte length. The
strict current collector then checked all six reports, compiler closures,
captured projects, source archives, actual imports and current markers. The six
components are distinct. New source/component approval entries must be reviewed
separately; original byte approvals are not reused.

[The public bounded packet](pr970-current-post-evidence.json) includes exact
component, `Capsule.java`, marker, report, compiler and receipt identities.
Complete reports, candidate components and failed attempts remain in the owned
helper volume and `target/pr970`. Private keys, authorization files, native
products and generated components are excluded from Git. The integrated signed
command/query/effect/recovery campaign and #718/#682 completion remain separate
acceptance work.
