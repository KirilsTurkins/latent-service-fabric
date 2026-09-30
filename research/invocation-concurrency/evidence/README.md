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
