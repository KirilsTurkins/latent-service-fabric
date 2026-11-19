# Original Java fiber fault observation

PR #2156 retains an unresolved signed Java failure: run `44518163237`, job
`135539652265`, passed component preparation and mode 0, then mode 1 failed with
`GuestTrap: unreachable-code`. The compiler/model receipts passed before that
failure; they are not evidence that the signed programme passed.

The branch-scoped `java-fiber-fault.yml` workflow observes this exact retained
component without rerunning javac, TeaVM, compiler-model controls or an emitter.
It accepts only PR #2156 from the same repository and its existing
`fix/sdk-java-model-counts-20261118` branch. The ordinary Java authoring workflow,
Rust test harness, guest sources, admission, grants and resource ceilings remain
unchanged.

`tools/java_fiber_fault_inputs.py` verifies the original run, failed job and its
successful preparation step, artifact identity, whole-archive SHA-256, and the
sizes and hashes of four selected files. It stages only the component, source,
WIT and original compiler receipt. The source must still equal the checked-in
thread fixture. Missing, changed, duplicated or symlinked inputs are errors;
there is no latest-artifact lookup, dependency substitution or compiler fallback.
The retained compiler receipt is not rewritten into a runtime qualification.

The native build explicitly selects the existing
`java-checkpoint-gc-trap-diagnostic` feature, not `--all-features`. Its existing
emitter retains at most eight numeric function indexes and offsets, with the
historical `LSF-JAVA-GC-FAULT` prefix. Names, guest messages and native addresses
are not added to production error reporting. This diagnostic does not establish
GC as the cause of the fiber failure; the feature name identifies the reused
observer only.

The original twelve-call signed test still expects successful results and
physical retirement. A reproduced trap therefore remains a failing job; pipefail
preserves the test status through log capture. Retained numeric frames locate a
failure but do not establish its cause or qualify a runtime fix. A repaired
component still needs the ordinary pinned-toolchain and signed execution lanes.

The fixed artifact expires on December 3, 2026. An expired artifact must fail
closed and requires a separately reviewed replacement, not relaxed hashes or
bounds. This observation neither lifts the development merge hold nor enables or
dispatches the separately stopped scheduled compiler-model qualification.
