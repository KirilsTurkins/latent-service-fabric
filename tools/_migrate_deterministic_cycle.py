"""One-shot, branch-local move; removed after the committed fix is validated."""
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from tools import validate_foundation as foundation


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one replacement in {path}: {old!r}")
    file.write_text(text.replace(old, new))


# Demonstrate the actual CI failure before altering either manifest edge.
foundation.validate_workspace_dependency_graph(ROOT)
original_errors = foundation.ERRORS[:]
assert len(original_errors) == 3, original_errors
assert all("workspace dependency cycle" in value and "latent-testkit" in value for value in original_errors)
for value in original_errors:
    print(f"reproduced before fix: {value}", flush=True)
foundation.ERRORS.clear()

support = ROOT / "crates/latent-core/src/test_support"
support.mkdir()
for name in ("clocks.rs", "clocks", "coordination.rs", "coordination", "deterministic.rs"):
    (ROOT / "crates/latent-testkit/src" / name).rename(support / name)
(support / "mod.rs").write_text('''//! Neutral test-only clocks, identities and owner-lifetime coordination.
//!
//! Enable `latent-core/test-support` only for test infrastructure. Implementations
//! use only the standard library and never depend on node/runtime harnesses.
//! `latent-testkit` re-exports these same modules for existing harness callers.

#![deny(clippy::all, clippy::pedantic)]

pub mod clocks;
pub mod coordination;
pub mod deterministic;

pub use clocks::TestClock;
pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};
''')
replace("crates/latent-core/src/lib.rs", "pub mod publication;\n", 'pub mod publication;\n#[cfg(feature = "test-support")]\npub mod test_support;\n')
with (ROOT / "crates/latent-core/Cargo.toml").open("a") as file:
    file.write('''
[features]
# Opt-in neutral helpers; no production dependencies or runtime scheduling hooks.
test-support = []

[dev-dependencies]
tempfile.workspace = true
tokio = { workspace = true, features = ["rt-multi-thread", "test-util"] }
''')
replace("crates/latent-core/src/test_support/clocks.rs", "use latent_core::{ActivationClock, ClockSample};", "use crate::{ActivationClock, ClockSample};")
replace("crates/latent-core/src/test_support/clocks/tests.rs", "use crate::coordination::{with_watchdog, PollProbe, WATCHDOG};\nuse crate::DeterministicIds;", "use crate::test_support::coordination::{with_watchdog, PollProbe, WATCHDOG};\nuse crate::test_support::DeterministicIds;")
replace("crates/latent-core/src/test_support/clocks/tests.rs", "latent_core::SystemActivationClock", "crate::SystemActivationClock")
replace("crates/latent-testkit/src/lib.rs", "pub mod clocks;\n", "")
replace("crates/latent-testkit/src/lib.rs", "pub mod coordination;\npub mod deterministic;\n", "")
replace("crates/latent-testkit/src/lib.rs", "pub use async_runtime::AsyncTestRuntime;", "pub use latent_core::test_support::{clocks, coordination, deterministic};\n\npub use async_runtime::AsyncTestRuntime;")
replace("crates/latent-testkit/src/lib.rs", "//! Use `default-features = false` for clocks and coordination without the node harness.", "//! Use `default-features = false` for clocks and coordination without the node harness.\n//! Upstream crates use `latent-core/test-support` directly to keep the workspace acyclic.")
replace("crates/latent-testkit/Cargo.toml", 'latent-core = { path = "../latent-core" }', 'latent-core = { path = "../latent-core", features = ["test-support"] }')
for package in ("latent-admission", "latent-scheduler"):
    replace(f"crates/{package}/Cargo.toml", 'latent-testkit = { path = "../latent-testkit", default-features = false }', 'latent-core = { path = "../latent-core", features = ["test-support"] }')
for relative in ("crates/latent-admission/src/tests/stress.rs", "crates/latent-scheduler/src/fixed_pool/tests/races.rs"):
    file = ROOT / relative
    text = file.read_text()
    assert "latent_testkit::" in text, relative
    file.write_text(text.replace("latent_testkit::", "latent_core::test_support::"))

# Re-exports must refer to the very same types, not copied helpers with new state.
compatibility = ROOT / "crates/latent-testkit/tests/test_support_compatibility.rs"
compatibility.parent.mkdir(exist_ok=True)
compatibility.write_text('''use std::time::{Duration, Instant};

use latent_core::ActivationClock;
use latent_testkit::coordination::{PollProbe, Stage};

#[test]
fn clock_and_rendezvous_reexports_preserve_type_and_state_identity() {
    let clock: latent_core::test_support::TestClock =
        latent_testkit::TestClock::new(433, Instant::now(), 1);
    let alias: latent_testkit::clocks::TestClock = clock.clone();
    let deadline = clock.monotonic_now() + Duration::from_nanos(1);
    let mut timer = Box::pin(alias.sleep_until(deadline));
    let probe = PollProbe::default();
    probe.pending(timer.as_mut());
    clock.advance(Duration::from_nanos(1));
    probe.ready(timer.as_mut());
    assert_eq!(alias.pending_waiters(), 0);
    let gate: latent_core::test_support::coordination::Rendezvous =
        latent_testkit::coordination::Rendezvous::new(1);
    let (id, mut owner) = gate.track(()).unwrap();
    owner.commit(Stage::Entered).unwrap();
    drop(owner);
    gate.require_retired(id).unwrap();
}

#[test]
fn deterministic_module_and_root_reexports_remain_compatible() {
    let mut ids: latent_core::test_support::DeterministicIds =
        latent_testkit::deterministic::DeterministicIds::new("compatible");
    assert_eq!(ids.next_id(), "compatible-0000000000000000");
    assert_eq!(latent_testkit::block_on(async { 433 }), 433);
    let clock: latent_core::test_support::ManualClock = latent_testkit::ManualClock::default();
    assert_eq!(clock.advance_nanos(1), 1);
    let parent = tempfile::tempdir().unwrap();
    let workspace: latent_core::test_support::TempWorkspace =
        latent_testkit::TempWorkspace::create_under(parent.path(), "compatibility").unwrap();
    assert!(workspace.path().is_dir());
}
''')

replace(".github/workflows/ci.yml", "python3 -m unittest tools.tests.test_ci_profile tools.tests.test_validate_docs", "python3 -m unittest tools.tests.test_ci_profile tools.tests.test_validate_docs tools.tests.test_deterministic_tests tools.tests.test_testkit_dependencies")
replace(".github/workflows/ci.yml", "      - name: Check workspace\n", '''      - name: Check deterministic helper dependency boundaries
        timeout-minutes: 5
        run: |
          python3 tools/check_testkit_dependencies.py
          cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=1
          cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=4
          cargo test -p latent-admission -p latent-scheduler --lib --locked
          cargo test -p latent-testkit --no-default-features --lib --test test_support_compatibility --locked
          cargo run -p latent-testkit --no-default-features --example deadline --locked
          cargo run -p latent-testkit --no-default-features --example cancellation --locked
      - name: Check workspace
''')

doc = ROOT / "docs/development/deterministic-tests.md"
text = doc.read_text()
start = text.index("Low-level dev-dependencies select:")
end = text.index("## Before/after execution evidence", start)
text = text[:start] + '''Low-level admission/scheduler tests select the neutral implementation directly:

```toml
[dev-dependencies]
latent-core = { path = "../latent-core", features = ["test-support"] }
```

Use `latent_core::test_support::{TestClock, DeterministicIds}` and
`latent_core::test_support::coordination::{Rendezvous, PollProbe, Stage}` there.
The standard-library-only helpers and their 21 unit tests live together under
`latent-core/src/test_support/`. The feature is opt-in. Tokio and tempfile are
**dev-dependencies only** of core, used to run the relocated tests; core has no
production dependencies and no back edge into a workspace crate. No new crate,
production clock hook or scheduling semantics are introduced.

`latent-testkit` re-exports those exact modules and types, including its existing
root-level exports. Existing harness users and the executable examples retain
their import paths. Its default `runtime` feature still gates the optional
activation/executor/node/telemetry harness dependencies, but **feature gating is
not an exception to the workspace acyclicity rule**. Upstream crates must not add
a testkit dependency, even with `default-features = false`.

```sh
python3 tools/validate_foundation.py
python3 tools/check_testkit_dependencies.py
python3 -m unittest tools.tests.test_deterministic_tests tools.tests.test_testkit_dependencies
cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=1
cargo test -p latent-core --features test-support --lib --locked test_support:: -- --test-threads=4
cargo test -p latent-admission -p latent-scheduler --lib --locked
cargo test -p latent-testkit --no-default-features --lib --test test_support_compatibility --locked
cargo test -p latent-testkit --lib --test test_support_compatibility --locked
```

The guard first invokes the existing foundation validator over **all** workspace
manifest edges, including optional, development, build and target-specific edges.
Only then does it inspect independently selected Cargo graphs, including their
test dependencies. The Python regressions reconstruct the originally missed
admission/testkit/node and scheduler/testkit/node cycles and require failure
before Cargo is invoked. They also cover aliases, optional/target/build edges,
missing feature selection, empty graphs and heavyweight dependencies. CI runs
these regressions and the guard before the expensive workspace build; it does
not weaken or bypass the foundation validator.

The relocated tests retain fixed IDs, explicit wakeups, missing readiness,
stale/recycled/foreign tickets, premature retirement, buffer ownership, capacity
limits, abort, panic and real watchdog expiry. Both current-thread and
multi-thread Tokio runtimes exercise the controlled scripts. Re-export tests
ensure both import surfaces use identical types and shared clock state. Existing
ignored resource/qualification tests keep their separate explicit entrypoints.

''' + text[end:]
text += '''
### Dependency-cycle correction

The initial `b6ae23b` publication failed the unconditional foundation graph:
`latent-admission -> latent-testkit -> latent-node -> latent-admission`, with
corresponding scheduler cycles. The earlier feature-selected 21/33/35-node graph
observations below were not evidence of workspace acyclicity. The retained
receipt is historical execution evidence for its named revisions, not a passing
foundation result or a measurement of this corrected revision. The correction
moves the shared implementation and all 21 helper tests into feature-gated core,
removes both upstream testkit edges, and preserves the measured admission and
scheduler case bodies apart from import paths. Testkit's remaining library counts
therefore change; the original receipt and its source identities are not rewritten.
'''
doc.write_text(text)
foundation.validate_workspace_dependency_graph(ROOT)
assert not foundation.ERRORS, foundation.ERRORS
print("unconditional workspace graph passes after moving the neutral owners", flush=True)
