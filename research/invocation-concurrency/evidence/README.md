# Evidence record

Evidence is tied to the exact tested commit and source hashes, not merely to a
branch name or the presence of test code. The driver creates receipts only from
actual commands and refuses to reuse an output directory. Retained CI artifacts
include the component, extracted WIT, logs and measured runtime JSON.

## Initial qualification attempt

- Actions run: `36701705299` (2026-09-30).
- PR head: `2c12233398e9af7a6e104ac9433013c7aaf40bae`.
- Actual tested merge commit: `8a8d2f8f95b0982d6fb952e719a08d0e97c4d756`.
- Artifact SHA-256: `e1c0321f5919ec156366858466f47420016db9328e86457140d0dd79e501d167`,
  independently checked after download.
- Eight Python receipt tests passed. No component result was produced: the
  driver rejected wasm-tools' version string because it included a build hash.
- Observed tools: Rust `1.97.1 (8bab26f4f 2026-07-14)`, Cargo
  `1.97.1 (c980f4866 2026-06-30)`, wasm-tools
  `1.254.0 (bb58fdf91 2026-07-20)`.

This failed attempt is not runtime qualification. The version check is corrected
to compare the tool name and exact version token while retaining the full build
identity. Successful measurements, when retained, must come from a fresh run;
there are no estimated or manufactured performance numbers in this record.

## Actual-component qualification attempt

Run `36702760256` built and validated the guest component and native host on the
pinned toolchain. All four native scope tests and eight Python receipt tests
passed. Component SHA-256 was
`8ffce3461ae9d3a9eaec8656628e1d39e3f31cbfe921a5e196ac303c89a84a3a`.
The actual-component executable then rejected an incorrect fixture assumption:
it observed six live host operations after a terminal call returned, before Store
destruction. Returning a trap is not itself physical retirement. The fixture now
requires normal joins to drain before return, records outstanding owners after
terminal calls, and requires actual owner count zero after Store destruction.

The failed artifact digest was
`4f436e2beb82400f68b56ec9a4e03f0b5b1bf231e2714389753fb89206e72785`,
independently checked after download. The tested merge was
`c1b66438ca6ceaf475ef9aaee577ef7bf5b09bbf`. The failed run is retained as an
ownership finding, not promoted to a passing performance result.

## Passing actual-component execution

[Run 36704342082](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36704342082)
executed all twelve component cases, the four native scope tests and all seven
retained equal-work sample pairs successfully. The separate eight-test Python
receipt suite also passed. The driver receipt is retained in
[2026-09-30-receipt.json](2026-09-30-receipt.json): it is the complete original
JSON value with whitespace compacted, not a synthetic fixture or edited result.

- PR head: `1ecb96eb432e8ee5e7c2b604e7dc96ea281d4950`.
- Actual tested merge: `6e5796516cc035dd7fd8027110e0acdc590c499c`; clean checkout.
- Artifact: `11091427074`; SHA-256
  `1f0bad2c83fb74176c9c5bda1ff461d199d38827670a9d327bdb98b81b78bc8f`,
  independently checked after download.
- Original receipt bytes SHA-256:
  `44d8de160390c30e34b0ce35200645a1ed470e998c0e5082197bd51cdf032c3e`.
- Compacted committed receipt SHA-256:
  `7ed8691dd8e0f42236866f6231cb28248e7587138ad429967985763bbc438583`.
- Component SHA-256:
  `327dba8a59a8c8cb816f3ca785edc95ffb2151e531bb38c3a72f2e8c02a71f6a`.

The workflow's subsequent formatting check failed on a three-line expansion of
one assertion; the retained rustfmt output supplies that formatting-only fix.
This record claims passing execution, not an all-green workflow for that revision.
Later commits/runs must retain their own actual identities rather than relabel
these measurements as newly executed.

### Observations and interpretation

The sequential scope had one live host-operation owner; the cooperative scope
had eight simultaneously pending owners in the same Store. Both returned 36.
Cancellation was observed by all eight operations while their owners and Store
remained live; normal cancellation then drained all eight before return. Denied
authority and task overflow dispatched no host operations. A partial error was
retained while the other seven operations completed. Fresh-Store recovery passed.

Actual `std::thread::spawn` trapped. The inline-start rendezvous exhausted the
entire 50,000,000-unit shared fuel budget; explicit cooperative rendezvous
completed. Root epoch interruption left **six live host operations after the
call returned**, and **zero after Store destruction**. None of the eight guest
frame destructors ran on that trap path. Thus neither a terminal call result nor
guest destructors are sufficient physical-retirement evidence. The measured
Store-drop interval for that case was 34,042 ns; it describes this private
embedding, not production provider retirement or an external-effect rollback.

Seven samples per CPU variant, after one discarded warmup pair:

| Measure | Sequential arithmetic | Cooperative arithmetic plus checkpoints |
| --- | ---: | ---: |
| Arithmetic result (each sample) | 9,216 | 9,216 |
| Median call duration | 17,476 ns | 218,781 ns |
| Observed call-duration range | 16,935–20,151 ns | 218,180–232,261 ns |
| Fuel used (each sample) | 22,605 | 372,564 |
| Peak linear memory | 1,179,648 bytes | 1,179,648 bytes |
| Median Store-drop duration | 30,616 ns | 33,891 ns |

The deliberately frequent checkpoints add substantial work for this tiny CPU
kernel; they do not create parallel computation. Equal linear-memory page peaks
do **not** mean free task frames or equal allocator use: sub-page guest allocation,
code generation, runtime work and native fibers are not separately attributed.
The host-wait gates are readiness controls, not realistic network latency, so
the fan-out case proves concurrent pending work but not a production speedup.
These are bounded descriptive observations from one runner, not a statistical
performance qualification. Native allocator peak/RSS, signed-node execution,
production cell reservations and other language compiler profiles remain outside
this receipt, as recorded by `productionQualified: false` and the ADR gates.
