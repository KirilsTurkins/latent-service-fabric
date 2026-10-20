# Current bounded host TLS accounting work

This plan concerns #738 / ADR-0061 and the distinct `latent-rustls-outbound`
0.23.46 provider dependency. Production installation stays disabled and
`ACCOUNTING_QUALIFIED=false`. A passing parser reference is one prerequisite;
it cannot be relabelled as complete TLS accounting or ordinary-client proof.
Historical 0.23.45 packets retain their original source and limits.

## Source and build identity

Reproduce all 119 files from the authenticated archive and `PROVIDER.json`.
Require exactly five bounded parser changes plus the package-name derivation;
retain every other upstream byte and all license texts. Actual Cargo artifact
metadata must name this path package for `latent-streams` and retain ordinary
registry rustls for unrelated HTTPS and peer fixtures. Bind the complete
maintained lock, compiler, provider source and reference inputs before/after
each build. No shared-registry rewrite or runtime source generation is allowed.

## Trust configuration

The existing 64 KiB provider metadata reservation precedes protected root
loading. The profile permits 1-8 roots, each at most 8 KiB and at most 32 KiB
aggregate. Account for protected reads, parsed/owned trust anchors, verifier and
client configuration, temporary work and all retained clones. Verify that the
last physical `InstalledTls` owner, not a logical provider handle, releases the
reservation. Root replacement/hash/link/mode denials must precede contact;
protected restart and generation fencing must not migrate authenticated state.

## Connection, stack and kernel

The original 256 KiB TLS host-memory/provider reservations precede connection
construction. Inventory all parser, verification, handshake, error, encrypted
and plaintext buffers under the actual selected crypto/dependency closure.
The 16 KiB write-buffer and 32 KiB encrypted handshake-direction limits remain
unchanged. Bound every supported verification algorithm, key/path cost and
transient overlap; a benign peak or incomplete symbol attribution is not proof.

TLS retains the same physical TCP socket and original 96 KiB socket reservation.
Confirm real send/receive kernel bounds and no additional uncharged owner.
Separately establish native stack costs and the existing executor's bounded
concurrency; heap counters cannot stand in for stack/kernel evidence. Unknown
or unattributed physical costs remain a failing accounting obligation.

## Controlled physical barriers

Use current TLS 1.2 and 1.3 maximum-valid chains/roots/extensions as well as
hostile/truncated/oversized inputs. Retain the original amplification RED and
all eight bounded parser observations. At connect, handshake, read, write,
cancellation, timeout, epoch retirement, close, trap and Store drop, observe
original Io/budget/pool owners and actual socket/buffer retirement. Accepted
cancellation, handle drop or timeout must not refund pending physical work.
Retained chunks/configuration clones and late completion need explicit barriers.

Preserve partial I/O, EOF, backpressure, narrower operation/root deadlines,
strict currentness before dispatch and possible-write uncertainty. No reconnect,
request replay, fallback transport, credential inference or quota expansion is
part of this work.

## Test-only real-provider experiment

A private `cfg(test)` installer can select the already captured bounded provider
for real-peer unit controls. The public qualification installer and public
rotation always retain the `ACCOUNTING_QUALIFIED=false` refusal. The private
installer/rotation symbols and their selector variant are absent from normal and
`development-outbound` binaries; this is not a runtime enablement switch.

The focused hosted lane builds only the actual `latent-streams` library test
harness and dependencies, validates its exact Cargo artifact identity and all
25 registered cases, and executes them with the original 900-second suite cap.
All 19 earlier active controls remain mandatory, including the public
unqualified-installation refusal. Four existing TLS peer controls add actual
exchange, hostname denial, stalled-handshake deadline, and pending epoch
retirement observations through the private experiment; two additional controls
cover current maximum-valid input and the last physical trust owner below. Original reservations,
assertions, policy and cleanup paths remain unchanged. Both the bounded provider
and ordinary upstream peer library identities, complete selected source/lock
before and after, and test executable identity are retained. A missing case,
changed ignore state or partial success cannot produce a passing receipt.

This lane has not run until a source-bound hosted receipt says otherwise. Even
functional success does not establish complete allocator attribution, maximum
verification/stack/kernel bounds, or signed/real-component qualification, and
does not justify changing the accounting flag.

## Current maximum-valid and retained trust owners

The next current-source reference extends the same exact lane to 25 cases with
no extra timeout or allowance. A TLS 1.2/TLS 1.3 real peer presents eight valid
certificates under eight protected roots (32 KiB aggregate), with the existing
4096-byte TLS 1.3 entry-extension cap filled by a 4088-byte OCSP payload. It
preserves the historical reference's chain, trust, PING/PONG and actual-retirement
assertions while selecting the current bounded provider through the private test
constructor. Historical 0.23.45 source and observations remain unchanged.

A second case retains the actual `Arc<InstalledTls>` after provider retirement
and fixture destruction. It observes the original 64 KiB trust reservation still
held with exactly one configuration owner, verifies zero peer contact, then
requires that reservation to retire only after the final physical owner drops.
These controls are source-only until a new exact-source hosted receipt reports
their actual outcomes. Neither ledger observations nor a maximum-valid exchange
prove complete allocator, native-stack or kernel bounds; production refusal and
`ACCOUNTING_QUALIFIED=false` remain unchanged.

## Functional and coupled proof

First compile the actual bounded provider and retain exact Cargo/source identity.
Then run owned real-peer positive/refusal and maximum-valid/hostile controls
under unchanged limits, including trust/hostname failure, pending cancellation,
revocation/drain, forged/stale/cross-activation handles, quota exhaustion, and
fresh cross-tenant invocation. Production constructors must retain their
unqualified refusal while any test-only accounting experiment is selected.

Finally bind current native products and actual signed/component calls to that
same closure. Existing TCP, canonical and direct-SDK tests remain mandatory.
Operator rollout and separate adversarial acceptance are independent gates.
Only complete physical bounds plus current coupled evidence and the required
review can justify changing the accounting flag; this plan supplies no such
qualification claim.
