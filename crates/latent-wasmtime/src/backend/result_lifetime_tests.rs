use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crate::cache::{ActiveInstanceGate, PreparedCache, PreparedRuntimeCharge, PreparedRuntimeCost};
use crate::{PreparedRuntimeObserver, PreparedRuntimeSnapshot, WasmtimeConfig};

use super::{
    classify_call_result, platform_error, reclamation, BudgetConsumption, GuestOutcome,
    Phase0InvocationTiming, PlatformErrorCode, StopControl,
};

struct RuntimeOwner {
    gate: Arc<ActiveInstanceGate>,
    // Its actual ledger charge refunds after the native-owner Drop assertion.
    _charge: PreparedRuntimeCharge,
}

impl Drop for RuntimeOwner {
    fn drop(&mut self) {
        assert_eq!(
            self.gate.active(),
            1,
            "runtime must retire before its permit"
        );
    }
}

// Independent observers only: this error cannot keep the runtime alive itself.
struct NativeErrorOwner {
    observer: PreparedRuntimeObserver,
    gate: Arc<ActiveInstanceGate>,
    destroyed: Arc<AtomicBool>,
}

impl std::fmt::Debug for NativeErrorOwner {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("NativeErrorOwner")
    }
}

impl std::fmt::Display for NativeErrorOwner {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("bounded native error owner")
    }
}

impl std::error::Error for NativeErrorOwner {}

impl Drop for NativeErrorOwner {
    fn drop(&mut self) {
        assert_eq!(self.observer.snapshot().unwrap().live.runtimes, 1);
        assert_eq!(self.gate.active(), 1);
        self.destroyed.store(true, Ordering::SeqCst);
    }
}

#[test]
fn native_errors_release_while_the_actual_cleanup_helper_still_owns_runtime_and_permit() {
    for accounting_failed in [false, true] {
        let (owner, observer, gate) = ownership();
        let permit = gate.try_acquire().unwrap();
        let destroyed = Arc::new(AtomicBool::new(false));
        let error = wasmtime::Error::new(wasmtime::Trap::UnreachableCodeReached).context(
            NativeErrorOwner {
                observer: observer.clone(),
                gate: Arc::clone(&gate),
                destroyed: Arc::clone(&destroyed),
            },
        );
        let accounting_error = accounting_failed.then(|| {
            platform_error(
                PlatformErrorCode::Internal,
                "bounded accounting failure",
                false,
            )
        });
        let result = reclamation::finish(
            owner,
            permit,
            &mut Phase0InvocationTiming::default(),
            || {
                classify_call_result(
                    Err(error),
                    None,
                    &StopControl::new(None, None),
                    false,
                    BudgetConsumption::default(),
                    accounting_error,
                )
            },
        )
        .unwrap();
        assert!(destroyed.load(Ordering::SeqCst));
        let GuestOutcome::Trapped { trap, .. } = result else {
            panic!("native error must become a bounded trap");
        };
        assert_eq!(
            trap.code,
            if accounting_failed {
                "budget-accounting-failed"
            } else {
                "guest-trap"
            }
        );
        assert_retired(&observer, &gate);
    }
}

#[test]
fn successful_classification_and_unwind_keep_the_same_final_drop_order() {
    for unwinds in [false, true] {
        let (owner, observer, gate) = ownership();
        let permit = gate.try_acquire().unwrap();
        let destroyed = Arc::new(AtomicBool::new(false));
        let probe = NativeErrorOwner {
            observer: observer.clone(),
            gate: Arc::clone(&gate),
            destroyed: Arc::clone(&destroyed),
        };
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            reclamation::finish(
                owner,
                permit,
                &mut Phase0InvocationTiming::default(),
                || {
                    let _probe = probe;
                    assert!(!unwinds, "bounded classification unwind");
                    classify_call_result(
                        Ok(()),
                        Some(Ok(crate::values::EncodedResult::Returned(b"[]".to_vec()))),
                        &StopControl::new(None, None),
                        false,
                        BudgetConsumption::default(),
                        None,
                    )
                    .unwrap()
                },
            )
        }));
        assert_eq!(result.is_err(), unwinds);
        if let Ok(outcome) = result {
            assert!(matches!(outcome, GuestOutcome::Returned { .. }));
        }
        assert!(destroyed.load(Ordering::SeqCst));
        assert_retired(&observer, &gate);
    }
}

fn ownership() -> (
    RuntimeOwner,
    PreparedRuntimeObserver,
    Arc<ActiveInstanceGate>,
) {
    let cache = PreparedCache::<u8>::new_tracked(WasmtimeConfig::default().cache_limits()).unwrap();
    let observer = cache.prepared_runtime_observer();
    let gate = Arc::new(ActiveInstanceGate::new(1).unwrap());
    let owner = RuntimeOwner {
        gate: Arc::clone(&gate),
        _charge: cache
            .runtime_ledger()
            .unwrap()
            .register(PreparedRuntimeCost {
                source_bytes: 7,
                metadata_bytes: 5,
                compiled_image_bytes: 13,
            })
            .unwrap(),
    };
    (owner, observer, gate)
}

fn assert_retired(observer: &PreparedRuntimeObserver, gate: &ActiveInstanceGate) {
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
    assert_eq!(gate.active(), 0);
}
