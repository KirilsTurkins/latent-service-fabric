"""One-shot integration edits; removed after application."""
from pathlib import Path


def replace(path, old, new):
    path = Path(path)
    source = path.read_text()
    assert source.count(old) == 1, (path, old, source.count(old))
    path.write_text(source.replace(old, new))


path = Path('crates/latent-control-store/src/deployments/tests/admission.rs')
source = path.read_text()
assert 'mod execution;' not in source
path.write_text('mod execution;\n\n' + source)
path = Path('crates/latent-control-store/Cargo.toml')
source = path.read_text()
assert '[dev-dependencies]' in source
for name in ['latent-activation', 'latent-executor', 'latent-scheduler']:
    source += f'{name} = {{ path = "../{name}" }}\n'
source += 'tokio.workspace = true\n'
path.write_text(source)
# Existing locked packages only; no registry resolution or version changes.
path = Path('Cargo.lock')
source = path.read_text()
start = source.index('name = "latent-control-store"\n')
end = source.index('\n[[package]]', start)
block = source[start:end]
begin = block.index('dependencies = [\n') + len('dependencies = [\n')
finish = block.index('\n]', begin)
lines = block[begin:finish].splitlines()
lines += [f' "{name}",' for name in ['latent-activation', 'latent-executor', 'latent-scheduler', 'tokio']]
block = block[:begin] + '\n'.join(sorted(set(lines))) + block[finish:]
path.write_text(source[:start] + block + source[end:])
replace('crates/latent-admission/src/tests.rs', 'fn all_terminal_outcomes_release_reserved_capacity_after_accounting()', 'fn reservation_guard_is_outcome_agnostic_and_outlives_accounting()')
replace('crates/latent-admission/src/timing.rs', '    fn now(self) -> Instant {', '    pub(crate) fn now(self) -> Instant {')
quota = 'crates/latent-admission/src/quota.rs'
replace(quota, 'use std::collections::BTreeMap;', 'use std::collections::BTreeMap;\nuse latent_core::EffectiveDeadline;\nuse crate::timing::AdmissionClock;')
replace(quota, '    pub(crate) fn start(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {\n        let mut state = self.lock()?;', '''    pub(crate) fn start(&self, activation_id: &ActivationId, deadline: &EffectiveDeadline, clock: AdmissionClock) -> Result<(), PlatformError> {
        let mut state = self.lock()?;
        // Check after lock contention, before returning queue capacity or
        // authorizing execution. A live caller never reuses an earlier sample.
        if deadline.is_expired_at(clock.now()) {
            return Err(rejection(PlatformErrorCode::DeadlineExceeded, "request", "deadline", "deadline-exceeded"));
        }''')
permit = 'crates/latent-admission/src/permit.rs'
replace(permit, '''        self.ensure_schedulable_at(now)?;
        self.quotas.start(&self.activation_id)?;
        Ok(ExecutionPermit { admission: self })''', '''        self.start_execution_with_clock(crate::timing::AdmissionClock::Fixed(now))''')
replace(permit, '''        self.start_execution_at(Instant::now())
    }
}''', '''        self.start_execution_with_clock(crate::timing::AdmissionClock::Live)
    }

    fn start_execution_with_clock(self, clock: crate::timing::AdmissionClock) -> Result<ExecutionPermit, PlatformError> {
        self.quotas.start(&self.activation_id, &self.grant.deadline, clock)?;
        Ok(ExecutionPermit { admission: self })
    }
}''')
Path(__file__).unlink()
