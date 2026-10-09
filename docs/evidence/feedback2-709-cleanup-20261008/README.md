# Feedback 2 issue 709 cleanup handoff

Status: incomplete, explicitly stopped by the user for cleanup on 8 October 2026. Issue #709 remains open. This commit preserves work; it does not deliver or qualify the milestone.

PR #768 landed the diagnostic contract. Its clean merged worktree was removed, freeing 3.64 GiB. Four fresh adapted Java components were actually compiled and packaged from source `37b48cd8e485a826cd87e23aea184d99c17e4731`; all 104 commands succeeded. The original third-party compiler materials were extracted through their unchanged original producer owner in a separate process. Current and original ABI guards remain unchanged. The 1,123-file capture and its original receipts are retained here; compilation does not establish runtime admission or execution.

The current native run completed six useful vectors and strict Clippy under the original limits. It was positively stopped and reaped at the user's request. The first attempt failed after its prepared Docker volumes were deleted and recreated empty. The second used a bounded read-only keeper during handoff; that keeper was removed when the actual run owned the volumes. Both failures/progress remain separate.

The frozen source lacks the `transaction_recovery` example and several original 40-phase selectors. Zero-test outcomes cannot satisfy those vectors. Much of that old proof used unmerged Phase 4 state/recovery source, which #709 does not require. No current six-vector receipt was fabricated and the legacy proof gate remains unchanged.

The next agreed implementation is an additive, explicit authenticated current-publisher input owner for the same complete 900-second diagnostic programme. It must bind the native three executables and Java two helpers to exact source/ref/manifest/archive/checksum/Sigstore provenance, require genuine current profile/signature regression evidence, and preserve every existing diagnostic case, private-store capture, deadline, scope and independent exact candidate approval. This design has not yet been implemented. No new source PR was opened.

The live diagnostic programme, signing and capability grants have not started. Old candidate approvals are expired and must not be replayed. A fresh final approval request must prominently include the two HTTP output ceilings changing from 8,192 to 14,336 bytes, the unchanged operation/scope limits, and the actual complete candidate hash.

`handoff.json` records source pins, exact completion boundaries, remaining work and hashes of preserved public materials. Private stores, auth/signing keys, credentials and bulk environment caches are excluded.
