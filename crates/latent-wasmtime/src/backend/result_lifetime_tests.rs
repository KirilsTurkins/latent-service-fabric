use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::{
    classify_call_result, platform_error, BudgetConsumption, GuestOutcome, PlatformErrorCode,
    StopControl,
};

#[derive(Debug)]
struct NativeErrorOwner(Arc<AtomicBool>);

impl std::fmt::Display for NativeErrorOwner {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("bounded native error owner")
    }
}

impl std::error::Error for NativeErrorOwner {}

impl Drop for NativeErrorOwner {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[test]
fn normal_and_accounting_override_classification_destroy_the_native_error_before_return() {
    for accounting_failed in [false, true] {
        let destroyed = Arc::new(AtomicBool::new(false));
        let error = wasmtime::Error::new(NativeErrorOwner(Arc::clone(&destroyed)));
        let accounting_error = accounting_failed.then(|| {
            platform_error(
                PlatformErrorCode::Internal,
                "bounded accounting failure",
                false,
            )
        });
        let result = classify_call_result(
            Err(error),
            None,
            &StopControl::new(None, None),
            false,
            BudgetConsumption::default(),
            accounting_error,
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
        assert!(trap.guest_backtrace.is_empty());
    }
}
