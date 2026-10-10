# PR #795 HTTP-only stream authority control

## Scope and issue ownership

PR #795 provides the focused HTTP-only authority control consumed by
[#738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738),
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739) and
[#740](https://github.com/KirilsTurkins/latent-service-fabric/issues/740).
These provider, operator and adversarial tickets remain open. Architecture and
security review #737, production rollout, TLS allocation qualification and
ordinary all-six-language socket compatibility are separate requirements.
This PR closes no issue and enables no additional production profile.

The original head is `27cc15565c0219c8a7f1307ae9543b92a368ccea`. Its historical
Rust test job fails before execution with
`latent-wire.test.management-service: renamed-or-missing-test`; the aggregate
fails with it. Normal integration of development
`02b098c2981e514dfff1dd13945038984dd8cf9a` retains the delivered #775 provider,
protected reload/inspection controls, current Phase 4 work, exact test inventory
and all existing execution guards. The old inventory is not accepted or weakened.

## Snapshot and source decisions

Snapshot #952 preserves the exact original head; it contains no extra changes.
The central SDK cleanup #960 and stream snapshots #954, #909 and #911 record the
earlier provider/operator integration. Their revisions retain their own evidence;
development already has the later delivered provider/control implementation.
The TLS preparation and parser checkpoints #913/#912 explicitly retain unresolved
allocation qualification and are not production enablement or prerequisites for
this denial test. No TLS implementation is imported.

The old branch also contains a separate Java executor/continuation stack. Its
source remains preserved in #952 and the SDK runtime checkpoints, with the
related futures work owned by #807. It is excluded from this focused PR rather
than publishing an unqualified runtime change through an authority-test update.
Current Java implementation, qualifiers and existing source closures are kept
from development. The small shared authoring CLI change is retained: an explicit
finite six-language selection reaches the existing maintained workflow and its
original language-specific limits. No new execution policy is introduced.

## Control and validation

The new stream library case creates a real sealed HTTP-only broker session with
one approved GET path. A stream attempt against the same endpoint fails before
DNS/TCP contact, outbound-attempt charge, host-memory charge or physical owners.
The unchanged session then executes that approved GET through the real typed HTTP
provider and local peer. It uses the fixture's original 16 KiB I/O ceiling and
explicit 8 KiB HTTP body bounds; it does not increase a product default.

All 15 stream library cases pass on pinned Rust 1.97.1 Linux, including this new
control and the original physical-retirement/uncertainty tests. All seven actual
canonical-component stream cases pass. The current management-service target
passes all 48 cases, resolving the old failed inventory's execution boundary.
All 34 focused Python inventory/discovery/result/migration and provider-lifetime
cases pass on pinned Python 3.13.5 Linux without skips. Read-only CI coverage
retains 88 baseline and 274 current required run blocks with 145 delegated owners.
All six CLI language selections reach the original workflow; an unsupported
selection refuses before dispatch. Formatting, scoped stream Clippy with
warnings denied, repository/foundation and documentation validation pass.

Historical receipts remain historical. These controls do not establish TLS,
ordinary socket-library integration, complete operator/adversarial coverage,
signed packaged distribution or closure of #738/#739/#740. Hosted CI is required
after publication and is not awaited for commit/push delivery.
