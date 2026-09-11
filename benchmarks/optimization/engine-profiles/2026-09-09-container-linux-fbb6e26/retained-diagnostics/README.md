# Retained #106 diagnostics

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

This archive preserves original bytes from four earlier matrix attempts for inspection. It is a **diagnostic-only subset**, not a qualifying full suite, performance comparison, or standard Phase 1 evidence archive. Referenced executables, source trees and other unselected files are deliberately absent; the complete original Docker roots were separate at publication. The final qualifying matrix-full-05 and primary external-full-04 evidence are separate publications.

| Attempt | Original collection suite | Actual owners | Attempted Invokes / commands | Original aggregate validated Invokes / commands / processes |
|---|---|---:|---:|---|
| matrix-smoke-01 | failed | 1 | 0 / 1 | 0/0/0 |
| matrix-smoke-02 | failed | 1 | 52 / 125 | 0/0/0 |
| matrix-smoke-03 | passed | 5 | 260 / 625 | unavailable: no original aggregate |
| matrix-full-04 | failed | 3 | 2382 / 4827 | 1588/3218/2 |

- **matrix-smoke-01:** capsule namespace validation rejected the first publication. Zero Invokes, one attempted setup command; the original raw has no successful setup response row. The failure and joined cleanup are retained.
- **matrix-smoke-02:** all 52 offers retained: 17 successes, one expected platform failure and 34 gRPC3 transport failures. The collector's original maximum-deadline rounding and WIT option oracle were corrected afterward; these bytes and identities were not rewritten.
- **matrix-smoke-03:** all five actual runtime collectors passed: 260 Invokes/625 commands, 215 successes and 45 expected platform failures. The old Python verifier then rejected the Echo fixture's intended guest log (`engine-unexpected-guest-log`), so the original root has no aggregate.json or failure.json. The original 64-byte command log is included under supplemental/. A separately retained corrected-verifier aggregate/receipt verifies the unchanged 260/625/5 graph, labels its smoke aggregate incomplete, explicitly denies full benchmark qualification and binds its validator modules. It does not relabel the original collector identities. Packaging did not rerun this verifier.
- **matrix-full-04:** all 2,382 offers/4,827 commands from three actual owners remain: both D0 owners passed; P0 succeeded 448 times then retained 346 consecutive gRPC3 maximum-deadline rejections. Overall 2,018 successes, 18 expected platform failures, 346 transport failures. The original failed aggregate validates only the two D0 owners (1,588/3,218/2); full completion flags remain false. All owners retained clean shutdown. Later clock observations established a frozen-projection mismatch, without this subset establishing an allocator or host-clock cause.

The selected contents include original suite/aggregate/failure files where they existed, backend-builds and engine-fixtures metadata, every actual owner's raw report/plan/identity/log/process/parent-cleanup receipts, and the five small maintained fixture components plus their referenced optimization contracts. Every path, original source root/relative path, byte size and SHA-256 appears in manifest.json. Its exclusions are explicit; absent references are not manufactured or interpreted as zero.

Packing is deterministic: sorted USTAR regular files, fixed permissions/ownership/time, gzip level 9 with timestamp 0 and no filename. A bounded memory-only extraction independently checked every member's size/hash against the original source inventory; no links, additional members or archive-controlled filesystem writes were accepted. This proves byte integrity, **not semantic qualification**. No benchmark, test, workload or full semantic replay ran during packaging. No original files were changed or removed.

Archive: 1,414,473 compressed bytes; 16,663,853 expanded file bytes; 105 files. SHA-256: `7fe288047eb4cc885ddde1af98e1347149bdb8d6cb4eb5f996df1fc4006e05e6`. Bounds: 64 MiB expanded and 256 regular files.
