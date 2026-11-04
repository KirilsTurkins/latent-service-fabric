# Rust ThreadPool integration blocker repairs

This correction is based on PR #1371 head
`381c4e42dae5b7c6e59b08e4b201812fa3c4d708`. It does not change guest runtime
code, the compiler catalogue, component bytes, capabilities, the 32 MiB memory
ceiling, the five-second deadline or the eight Native-owner limit. It is not
fresh signed-runtime qualification or a security-gate waiver.

## Keep immutable native origins independent

Java checkpoint/GC, TypeScript private-removal and Audit consumers select the
193-control producer `b422af24d86344ac7abb8b8fa56c3782aab63915`. Moving their
shared reader to the Rust ThreadPool's 200-control producer changed actual
artifact acquisition while their workflows still fetched the historical source.

`tools/rust_thread_native_products.py` is restored byte-for-byte to development's
193-control reader, Git blob `d402f90c175afcf42a22cd868589ec192aebd02c`.
Its run, job, `workflow_dispatch` event, archive/member identities and refusal
gates are unchanged. Existing Java, TypeScript and Audit imports and material
lists keep their original meaning.

The Rust ThreadPool's 200-control reader moves unchanged to
`tools/rust_thread_runtime_native_products.py`. Only its Rust consumer, signed
workflow and recipe-material selection use the new name. It still authenticates
`cddfb5d016a6311ed0db4673e490dc9caad917dd` and the exact `push` event; it does
not accept either origin or either event interchangeably. The existing Rust
regression checks that the two campaigns retain distinct immutable selections.

## Repair integration inputs rather than weaken checks

The shallow shared Python lane fetches the exact `cddfb5d` producer before test
discovery, retaining every previous history input. The signed Rust lane fetches
both exact origins because its regression verifies that historical selection
remains independent. Compiler artifact retention now matches the native
producer's seven-day evidence window; build commands, permissions and runtime
limits are unchanged.

Synthetic runner inventories copy both `.d` suites and `.cases.d` cases. The
regression detects silent case loss when only the fragments are omitted. Java
capture controls use the reviewed 9,248-file, 4 MiB-per-file and 77 MiB-total
limits, including a genuinely overflowing byte fixture. Audit controls preserve
the original six cases and account for exactly the two added envelope controls.
C preservation tests authenticate and invert only the reviewed outside-client
additions before their existing historical comparisons. The C authoring selector
expectation matches its already-present outside-client branch exclusion.

The temporary `rust-thread-integration-review.yml` and
`rust-thread-contract-review.yml` workflows are removed. Their absence restores
the existing workflow/action policy; the policy itself is not relaxed.

## Evidence and remaining obligations

Hosted review run `41810469335`, job `126508142454`, retained 21 corrected files
with individual Git and SHA-256 identities. Its 180-test affected suite passed
with one existing skip, and the complete CI inventory reported `passed` against
the modified `0ef909f` checkout. The overall workflow failed after validation;
it is not a successful integrated PR or native execution run. The retained ZIP
artifact is `13311722294`, SHA-256
`5312d67dfa0a7b152fa061f4e4e24c7888851bff441594f82002a12cc4d487d4`.
The 21 correction files are retained exactly; workflow removal and this
explanation are separate changes.

A complete checkout with the history fetched by `.github/workflows/ci.yml` is
required for preservation tests. An offline source export can exercise frozen
reader imports with authenticated producer fixtures, but that is unit-fixture
replay, not Git-history verification or signed guest execution.

The last inspected hosted security scan, run `41422894374`, reported unresolved
dependency findings. This patch does not suppress or remediate them. Security
remediation, full final-head CI and fresh merged-host signed qualification remain
required. The broader #743/#689 qualification flags and shipping-builder gate
remain false. Historical signed success is not relabeled as evidence for a newly
built host.
