//! Fixed, source-selected observations of the original host register refusal.
//! No owner, error, request, callback or arbitrary identity is retained.
use latent_core::activation_runtime::{OwnerKind, RuntimeLimits, RuntimePhase, RuntimeSnapshot};
use latent_core::{BudgetDimension, PlatformError, PlatformErrorCode, ResourceBudget};

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentBorrowAdmissionSnapshot {
    pub case: u8,
    pub refusals: u32,
    pub ambiguous: bool,
    pub kind: u8,
    pub error: u8,
    /// 0 unknown; 1 original owner limit; 2 token exhaustion; 3 record allocation;
    /// 4 original memory budget; 5 original CPU budget. No private text is copied.
    pub cause: u8,
    pub runtime_present: bool,
    pub owners: [u32; 7],
    pub parked_tasks: u32,
    pub managed_idle_workers: u32,
    pub phase: u8,
    pub runtime_memory_bytes: u64,
    pub admission_failures: u64,
    pub limits_present: bool,
    pub limits: [u32; 7],
    pub granted_cpu_fuel: u64,
    pub remaining_cpu_fuel: u64,
    pub granted_memory_bytes: u64,
    pub remaining_memory_bytes: u64,
}

pub(crate) fn case_index(label: &str) -> Option<u8> {
    match label {
        "normal-copy-dispose" => Some(0),
        "logical-cancel-before-borrow-release" => Some(1),
        "root-trap-with-held-borrow" => Some(2),
        "fresh-after-trap" => Some(3),
        "root-deadline-with-held-borrow" => Some(4),
        "fresh-after-deadline" => Some(5),
        "node-net-echo" => Some(6),
        "node-net-sibling" => Some(7),
        "node-net-denied" => Some(8),
        "node-net-destroy" => Some(9),
        "node-net-unclosed" => Some(10),
        "node-net-fresh" => Some(11),
        "node-net-published-granted" => Some(12),
        "node-net-published-denied" => Some(13),
        _ => None,
    }
}

fn kind_index(kind: OwnerKind) -> u8 {
    match kind {
        OwnerKind::Task => 0,
        OwnerKind::ManagedIdleWorker => 1,
        OwnerKind::Executor => 2,
        OwnerKind::QueuedWork => 3,
        OwnerKind::Wait => 4,
        OwnerKind::Timer => 5,
        OwnerKind::Result => 6,
        OwnerKind::Native => 7,
    }
}

fn error_index(error: &PlatformError) -> u8 {
    match error.code {
        PlatformErrorCode::Unavailable => 0,
        PlatformErrorCode::PermissionDenied | PlatformErrorCode::AdmissionRejected => 1,
        PlatformErrorCode::ResourceExhausted => 2,
        PlatformErrorCode::Cancelled => 3,
        PlatformErrorCode::DeadlineExceeded => 4,
        PlatformErrorCode::InvalidArgument => 6,
        _ => 5,
    }
}

fn cause_index(error: &PlatformError) -> u8 {
    match error.message.as_str() {
        "runtime-owner-limit" => return 1,
        "runtime-token-exhausted" => return 2,
        "runtime-record-allocation" => return 3,
        _ => (),
    }
    for detail in error.details.iter().take(8) {
        if detail.kind == "activation.resource-exhausted" {
            match detail.fields.get("dimension").map(String::as_str) {
                Some(value) if value == BudgetDimension::MemoryBytes.wire_name() => return 4,
                Some(value) if value == BudgetDimension::CpuFuel.wire_name() => return 5,
                _ => (),
            }
        }
    }
    0
}

#[derive(Debug)]
pub(crate) struct Observer {
    case: u8,
    kind: Option<u8>,
    first: Option<DevelopmentBorrowAdmissionSnapshot>,
}
impl Observer {
    pub(crate) fn for_activation(label: &str, numeric_observer_configured: bool) -> Option<Self> {
        if !numeric_observer_configured {
            return None; // Ordinary execution does not even inspect the fixture environment.
        }
        Self::select(
            label,
            std::env::var_os("LSF_TYPESCRIPT_BORROW_FIXTURE")
                .is_some_and(|value| !value.is_empty()),
            std::env::var_os("LSF_GUEST_SDK_LANGUAGE").is_some_and(|value| value == "typescript"),
        )
    }

    fn select(label: &str, fixture: bool, typescript: bool) -> Option<Self> {
        if !fixture || !typescript {
            return None;
        }
        Some(Self {
            case: case_index(label)?,
            kind: None,
            first: None,
        })
    }

    pub(crate) fn prepare_register(&mut self, kind: OwnerKind) {
        self.kind = Some(kind_index(kind));
    }

    pub(crate) fn refused(
        &mut self,
        error: &PlatformError,
        runtime: Option<RuntimeSnapshot>,
        limits: Option<RuntimeLimits>,
        granted: &ResourceBudget,
        remaining: &ResourceBudget,
    ) {
        if let Some(first) = &mut self.first {
            first.refusals = first.refusals.saturating_add(1);
            first.ambiguous = true;
            return; // First original counts/cause never get replaced by cleanup/later failure.
        }
        let snapshot = DevelopmentBorrowAdmissionSnapshot {
            case: self.case,
            refusals: 1,
            ambiguous: self.kind.is_none(),
            kind: self.kind.unwrap_or(u8::MAX),
            error: error_index(error),
            cause: cause_index(error),
            runtime_present: runtime.is_some(),
            owners: runtime.map_or([0; 7], |value| value.owners),
            parked_tasks: runtime.map_or(0, |value| value.parked_tasks),
            managed_idle_workers: runtime.map_or(0, |value| value.managed_idle_workers),
            phase: runtime.map_or(u8::MAX, |value| match value.phase {
                RuntimePhase::Running => 0,
                RuntimePhase::Waiting => 1,
                RuntimePhase::Closing => 2,
                RuntimePhase::Draining => 3,
                RuntimePhase::Cancelling => 4,
                RuntimePhase::Retired => 5,
            }),
            runtime_memory_bytes: runtime.map_or(0, |value| value.host_memory_bytes),
            admission_failures: runtime.map_or(0, |value| value.admission_failures),
            limits_present: limits.is_some(),
            limits: limits.map_or([0; 7], |value| {
                [
                    value.tasks,
                    value.executors,
                    value.queued_work,
                    value.waits,
                    value.timers,
                    value.results,
                    value.native_owners,
                ]
            }),
            granted_cpu_fuel: granted.cpu_fuel,
            remaining_cpu_fuel: remaining.cpu_fuel,
            granted_memory_bytes: granted.memory_bytes,
            remaining_memory_bytes: remaining.memory_bytes,
        };
        self.first = Some(snapshot);
    }

    pub(crate) fn snapshot(&self) -> Option<DevelopmentBorrowAdmissionSnapshot> {
        self.first
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normal_socket_cases_keep_distinct_closed_indices_and_original_opt_in() {
        for (index, label) in [
            "node-net-echo",
            "node-net-sibling",
            "node-net-denied",
            "node-net-destroy",
            "node-net-unclosed",
            "node-net-fresh",
            "node-net-published-granted",
            "node-net-published-denied",
        ]
        .into_iter()
        .enumerate()
        {
            assert_eq!(case_index(label), Some(u8::try_from(index + 6).unwrap()));
            assert!(Observer::select(label, false, true).is_none());
            assert!(Observer::select(label, true, false).is_none());
            assert!(Observer::select(label, true, true)
                .unwrap()
                .snapshot()
                .is_none());
        }
        assert!(case_index("node-net-unknown").is_none());
        assert_eq!(case_index("normal-copy-dispose"), Some(0));
        assert_eq!(case_index("fresh-after-deadline"), Some(5));
    }

    #[test]
    fn only_existing_typescript_borrow_fixture_and_closed_case_select() {
        assert!(Observer::for_activation("normal-copy-dispose", false).is_none());
        for (fixture, typescript) in [(false, false), (false, true), (true, false)] {
            assert!(Observer::select("normal-copy-dispose", fixture, typescript).is_none());
        }
        assert!(Observer::select("foreign-activation", true, true).is_none());
        assert!(Observer::select("normal-copy-dispose", true, true)
            .unwrap()
            .snapshot()
            .is_none());
    }

    #[test]
    fn first_refusal_preserves_original_counts_and_later_failure_marks_ambiguity() {
        let mut observer = Observer::select("normal-copy-dispose", true, true).unwrap();
        observer.prepare_register(OwnerKind::Task);
        let budget = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 128,
            wall_time_limit_millis: None,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let original = RuntimeSnapshot {
            phase: RuntimePhase::Waiting,
            owners: [16, 0, 15, 0, 0, 1, 31],
            parked_tasks: 15,
            managed_idle_workers: 0,
            host_memory_bytes: 64,
            admission_failures: 1,
            stale_wakes: 0,
        };
        let error = PlatformError {
            code: PlatformErrorCode::ResourceExhausted,
            message: "runtime-owner-limit".into(),
            details: Vec::new(),
            retryable: false,
        };
        observer.refused(&error, Some(original), None, &budget, &budget);
        let first = observer.snapshot().unwrap();
        assert_eq!(first.kind, 0);
        assert_eq!(first.error, 2);
        assert_eq!(first.cause, 1);
        assert_eq!(first.owners, original.owners);
        assert!(!first.ambiguous);
        observer.prepare_register(OwnerKind::Native);
        observer.refused(&error, None, None, &budget, &budget);
        let mut expected = first;
        expected.refusals = 2;
        expected.ambiguous = true;
        assert_eq!(observer.snapshot(), Some(expected));
        assert!(serde_json::to_vec(&expected).unwrap().len() <= 2048);
        let backend =
            crate::development_trap_observer::DevelopmentTrapObserver::for_engine_configuration(
                true,
            );
        backend.capture_borrow_admission(Some(first)); // Unarmed capture cannot create evidence.
        let guard = backend.arm().unwrap();
        assert!(guard.snapshot().unwrap().borrow_admission_refusal.is_none());
        backend.capture_borrow_admission(Some(first));
        assert_eq!(
            guard.snapshot().unwrap().borrow_admission_refusal,
            Some(first)
        );
        let mut foreign = first;
        foreign.case = 5;
        foreign.owners = [0; 7];
        backend.capture_borrow_admission(Some(foreign));
        assert_eq!(
            guard.snapshot().unwrap().borrow_admission_refusal,
            Some(expected)
        );
        assert!(std::mem::size_of::<Observer>() <= 512);
        println!(
            "TYPESCRIPT_BORROW_ADMISSION_ABI {{\"observerBytes\":{},\"snapshotBytes\":{}}}",
            std::mem::size_of::<Observer>(),
            std::mem::size_of::<DevelopmentBorrowAdmissionSnapshot>()
        );
    }
}
