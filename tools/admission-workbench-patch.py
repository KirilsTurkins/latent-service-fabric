"""One-shot feature edits; removed after successful application."""
from pathlib import Path


def replace(path, old, new, count=1):
    file = Path(path)
    source = file.read_text()
    assert source.count(old) == count, (path, old, source.count(old))
    file.write_text(source.replace(old, new))


root = 'crates/latent-admission/src/'
controller = root + 'controller.rs'
quota = root + 'quota.rs'
permit = root + 'permit.rs'
tests = root + 'tests.rs'
replace(root + 'lib.rs', 'mod quota;', 'mod quota;\nmod timing;')
for file in [root + 'lib.rs', controller]:
    replace(file, "fn admit<'a>(\n        &'a self,", 'fn admit(\n        &self,')
    replace(file, "BoxFuture<'a, Result<AdmissionPermit, PlatformError>>", "BoxFuture<'_, Result<AdmissionPermit, PlatformError>>")
replace(controller, 'use crate::policy::cell_rank;', 'use crate::policy::cell_rank;\nuse crate::timing::{AdmissionClock, ReservationTiming};')
replace(controller, 'self.admit_observed_at(request, load, ClockSample::system_now())', 'self.admit_observed_at(request, load, ClockSample::system_now(), AdmissionClock::Live)')
replace(controller, 'self.admit_observed_at(request, load, sample)', 'self.admit_observed_at(request, load, sample, AdmissionClock::Fixed(sample.monotonic()))')
replace(controller, '        load: NodeLoadSnapshot,\n        sample: ClockSample,', '        load: NodeLoadSnapshot,\n        sample: ClockSample,\n        clock: AdmissionClock,')
replace(controller, '            load.queue_delay_millis,\n            sample.monotonic(),', '            ReservationTiming { clock, observed_queue_delay_millis: load.queue_delay_millis, load_observed_at: load.observed_at },')
replace(controller, '    let mut entries = 0_usize;', '    validate_metadata(request, node)?;\n    Ok(tenant)\n}\n\nfn validate_metadata(request: &AdmissionRequest, node: &NodeAdmissionPolicy) -> Result<(), PlatformError> {\n    let principal = &request.principal;\n    let mut entries = 0_usize;')
replace(controller, '    Ok(tenant)\n}\n\nfn validate_revision_policy', '    Ok(())\n}\n\nfn validate_revision_policy')
replace(controller, 'fn budget_rejection(error: BudgetError)', 'fn budget_rejection(error: &BudgetError)')
replace(controller, '.map_err(budget_rejection)', '.map_err(|error| budget_rejection(&error))', 2)
replace(permit, '        observed_queue_delay_millis: u64,\n        now: Instant,', '        timing: crate::timing::ReservationTiming,')
replace(permit, '            observed_queue_delay_millis,\n            now,', '            timing,')
replace(permit, '    #[must_use]\n    pub fn admission(&self)', '    pub fn admission(&self)')
replace(quota, 'use std::time::{Duration, Instant};\n', '')
replace(quota, "pub(crate) struct ReservationSpec<'a>", "#[derive(Clone, Copy)]\npub(crate) struct ReservationSpec<'a>")
replace(quota, '    pub observed_queue_delay_millis: u64,\n    pub now: Instant,', '    pub timing: crate::timing::ReservationTiming,')
file = Path(quota)
source = file.read_text()
start = source.index('        let waves = ')
end = source.index('        let record = Reservation {', start)
source = source[:start] + '        spec.timing.validate(policy, spec.grant, current_cell, class.parallelism)?;\n' + source[end:]
file.write_text(source)
replace(tests, 'use super::*;', 'use super::*;\n\nmod stress;\ntype PolicyMutation = (fn(&mut RevisionAdmissionPolicy), &\'static str);')
replace(tests, '    fn request(&self, id: &str)', '    fn request(id: &str)')
file = Path(tests)
source = file.read_text().replace('h.request(', 'Harness::request(').replace('self.request(', 'Self::request(')
# Never strand worker threads behind a barrier when the controlling assertion fails.
old = '            assert_eq!(winners.load(Ordering::SeqCst), 4, "{dimension}");\n            let usage = h.quotas.usage().unwrap();'
new = '            let winner_count = winners.load(Ordering::SeqCst);\n            let usage = h.quotas.usage().unwrap();\n            release.wait();\n            assert_eq!(winner_count, 4, "{dimension}");'
assert source.count(old) == 1
source = source.replace(old, new)
old = '            assert_eq!(usage.reserved_memory_bytes, 4 * 65_536);\n            release.wait();'
assert source.count(old) == 1
source = source.replace(old, '            assert_eq!(usage.reserved_memory_bytes, 4 * 65_536);')
file.write_text(source)
replace(tests, 'original_deadline - Duration::from_nanos(1)', 'original_deadline.checked_sub(Duration::from_nanos(1)).unwrap()')
replace(tests, 'h.sample.monotonic() - Duration::from_millis(1)', 'h.sample.monotonic().checked_sub(Duration::from_millis(1)).unwrap()')
replace(tests, '[(fn(&mut RevisionAdmissionPolicy), &str); 6]', '[PolicyMutation; 6]')
replace(tests, '.maximum_memory_bytes = 1\n', '.maximum_memory_bytes = 1;\n')
replace(permit, 'use latent_routing::ResolvedRevision;', 'use latent_routing::ResolvedRevision;\nuse latent_routing::revision_policy::{ExecutionBackendKind, StateModel, ThreadingModel};')
replace(permit, '    pub priority: u8,', '    pub priority: u8,\n    pub backend: ExecutionBackendKind,\n    pub threading: ThreadingModel,\n    pub state_model: StateModel,')
replace(controller, '            priority: request.priority,', '            priority: request.priority,\n            backend: policy.execution.backend,\n            threading: policy.execution.threading,\n            state_model: policy.execution.state_model,')
replace(root + 'lib.rs', '        retryable: matches!(\n            code,\n            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::Unavailable\n        ) || reason == "queue-deadline-infeasible",', '        retryable: code == PlatformErrorCode::Unavailable || matches!(reason, "capacity-exhausted" | "node-overloaded" | "queue-deadline-infeasible"),')
with Path(root + 'tests/stress.rs').open('a') as file:
    file.write('''
#[test]
fn permanent_input_failures_are_not_retryable_and_execution_obligations_are_pinned() {
    let h = Harness::standard();
    let permit = h.admit("obligations").unwrap();
    assert_eq!(permit.obligations().backend, ExecutionBackendKind::WasmComponent);
    assert_eq!(permit.obligations().threading, ThreadingModel::SingleThreaded);
    assert_eq!(permit.obligations().state_model, StateModel::Stateless);
    drop(permit);
    let mut oversized = Harness::request("oversized");
    oversized.payload_bytes = 4096;
    assert!(!h.controller.admit_at(oversized, h.sample).unwrap_err().retryable);
    let mut no_capacity = Harness::request("zero");
    no_capacity.requested_budget.cpu_fuel = 0;
    assert!(!h.controller.admit_at(no_capacity, h.sample).unwrap_err().retryable);
    let mut load = h.load.snapshot().unwrap();
    load.cpu_pressure_milli = 900;
    h.load.publish(load).unwrap();
    assert!(h.admit("overloaded").unwrap_err().retryable);
    h.assert_empty();
}
''')
replace('crates/latent-admission/Cargo.toml', 'description = "Interface contracts for latent-admission."', 'description = "Bounded single-node admission, local quotas, and affine execution permits."')
ci = '.github/workflows/ci.yml'
replace(ci, 'cargo clippy -p latentd --all-targets', 'cargo clippy -p latentd -p latent-admission --all-targets')
replace(ci, '        run: cargo test --workspace --all-targets --all-features --locked', '        run: |\n          cargo test --workspace --all-targets --all-features --locked\n          cargo test -p latent-admission --doc --locked')
Path(__file__).unlink()
