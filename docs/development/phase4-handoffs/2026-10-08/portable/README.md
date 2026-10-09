# Portable Phase 4 cleanup handoff

The user stopped implementation and validation. All owned Source, Native and SDK jobs are reaped; the private container observation contains only init/sleep and the read-only process probe. No new tests, builds, Docker cleanup or worktree deletion were performed for this handoff.

The complete inventory records89 clean owned worktrees with verified remote archive refs under `checkpoint/phase4-cleanup-20261008/portable/`. Root's central preservation draft #850 also indexes the wider Phase 4 history. No uncommitted source remains in these89 trees. Peer trees are excluded from the owned list.

## Delivered existing pull-request heads at the stop

| PR | Portable delivered head |
| --- | --- |
| #784 | `b43ab914f9ffbdd4fa26c26b66c913daf3342aef` |
| #787 | `4ce4eb63a04cded8bbb4b875c1b6863a3cc84678` |
| #790 | `9977333b18c3990e52b5aebb7e0382a26dfa35aa` |
| #791 | `a129773f52c4fc15c59b4ce62b52744a233cd4cd` |
| #796 | `8f85a60021786138a25f75b8fbc22c32f8789844` |
| #800 | `5d41e9b481e78818db4ac2a8ff30095301e61f94` |
| #811 | `f149bb009952e823c6d6f3877af80b298c5c7258` |
| #825 | `601038c2b908144dadd11bcb48ddbab51606b5d4` |
| #828 | `1b7a8073f9ec7b354a4dd00a365deb1c4094e3aa` |

These are preserved source states, not claims of full hosted CI, admin merge or issue completion. Root owns final remote-state refresh and ticket/PR progress comments.

## Exact recent qualification boundaries

- #784 b43: Source226 tests/all7 gates, Native all9 gates at the same head; Signing58/Node91 compiled sets equal their registry and all tests pass, activation66 passes, custom AOT12 real-entry plus exact syscall marker passes, original ordinary and selected strict gates pass. Receipt `portable-v2-pr784-current-main-native-20261008-v315/receipt.json`, SHA `0ba2625d9db20f7d41c6011137baecdbeef4133017f511f28172876f61c37ad9`.
- #811 f149: actual pinned Buf1.72.0 produced the same descriptor twice, SHA `539496c72df533c343b0904b1b4aad0546cf33adbeb110322cd911d9726fd3fd`. The tracked compact LF golden183f differs from peer physical CRLF66c only by a trailing CR; all previous semantics are preserved. Source all9 gates/226 tool tests plus12 profile tests pass. Receipt SHA `b7764c8e2b3788f1a7b4648806d19c15ad5716915279e02f3b1f1e185bd0722c`. Original v277 Source ran208 actual tests; unused arguments are corrected in v312's238 actual count. Parent335d Native9 receipts retain their actual head.
- #828 1b7: Source375 discovered/374 passed/one original Windows skip and all7 gates pass, receipt SHA `70082840aea65dc413d13df8f3430ddbbd10cf62879c91bbb325f3a42f25c317`. Existing control29 SDK suites both pass10; the later audit proves deployment preparation rejected before writer acceptance with `admission-clock-lease-uncovered`, operation lookup remains Unknown. The closed six-stage diagnostic and CLI sanitizer are published; actual new Control255/CLI162/RPC27 tests and the exact original subphase remain unqualified. No lease, grant, budget, deadline or mutation retry was added.
- #825 unchanged6010: the one infrastructure-failed Admitted C job was rerun after completed-attempt/head guards. Attempt2 completed successfully, new job113169978107. Original installer timeout and all receipts remain in the archive; other workflow qualification is separate.
- Current #791 a129 Source278/all8 gates passes, including the pinned scanner. Core127/Signing58/Node114 current Native and the separate queued Go preparation result remain pending.
- Current #796 retains Native9 at8f85 and Source227. Its original installer conflict was classified by the coordinating agent; full #397's twelve acceptance criteria were not closed by focused CI evidence.

## Distinct unpublished feature

Reference app #402 is checkpoint `7bc1ca796e5b1a2125a0fb6be905484fec6e8b63`, pushed branch `feat/phase4-reference402-current-foundation-v292` and Root-created draft #956. Source7 passes389 discovered/388 passing/one original Windows skip, with all27 app files and the finite producer branch preserved. Actual six app compilers, signed node, SSR/hydration, two-user browser, JetStream/inbox/crash redelivery, schema, rollout and dormancy remain pending. No current-foundation proof is transferred to the app.

The historical Go accounting d6 and HTTP c766 work are source-adopted in delivered feature heads. d6 is not a Git ancestor of6010, but both source files compare byte-identical there; archive it for provenance, without a duplicate active implementation PR. Root coordinates draft visibility for distinct work.

## Evidence archive and limitations

`portable-evidence.zip` stores2631 small coordination scripts, plans, exact receipts and authenticated Source/ordinary-Cargo logs. The manifest gives every original file hash and the ZIP hash. Both passing and failed attempts retain their actual heads and outcomes. Credential-shaped content is omitted rather than uploaded. Large toolchains, compiled guest payloads and private campaign databases are not copied to this compact Git archive; their absence means historical packaged/signed execution cannot be reconstructed solely from this handoff. Source commits and retained small proofs remain durable.

No issues are closed by this handoff. No global cleanup has been performed. Automatic review previously rejected deletion of three audited SDK derivative folders; no deletion or bypass occurred.
