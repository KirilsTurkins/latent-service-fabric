# PR #851 reconciliation

PR: <https://github.com/KirilsTurkins/latent-service-fabric/pull/851>

The preserved `0d922003` checkpoint is reconciled with development
`ab4e174c`. The current closed transaction HTTP schema supersedes the old
schema-conjunction workaround. The useful boundary cases now exercise that
maintained schema and its finite validator.

## Ticket context and delivered behavior

Read the bodies and comments of #409 and its transaction foundations #387 and
#388. #409 owns the reusable transaction HTTP route contract. These tests also
protect the identity and precondition boundaries used by that contract.

The manifest codec now enforces the same 256-byte UTF-8 transaction identity
ceiling as HTTP admission. Transaction state and companion digests must use
canonical lowercase SHA-256 identities. Generic artifact digest syntax retains
its existing contract.

Three registered cases cover all transaction mode, HTTP method and precondition
combinations; exact UTF-8 identity boundaries; canonical digests and incarnation
counters; HTTP paths; and canonical padded base64 keys at the 1,024-byte ceiling.
The CI inventory retains every existing case and ignore guard. The captured
composition source identity is refreshed for the changed validator bytes.

## Verification and completion boundary

The locked, all-feature, all-target latent-manifest suite passed 75 cases across
12 targets with no ignored cases. The three new boundary cases passed. Focused
schema, deployment, composition-contract and Java transaction-schema Python
checks passed 25 cases. Foundation and CI coverage validation passed. Formatting
and latent-manifest Clippy passed with the existing validator length warning.

This PR supplies a shared route-boundary correction. It does not close #409,
#387 or #388: their full installed consumer, recovery and qualification matrices
remain separate acceptance work. Historical checkpoint campaigns are preserved
as historical evidence and are not reused as qualification for changed bytes.
