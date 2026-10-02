//! The original host binds one observer before any guest access. This slot is
//! descriptive; it supplies no state, effect, cancellation or commit authority.
use latent_executor::transaction::{StateFailure, TransactionStagingObserver};
use std::sync::{
    atomic::{AtomicBool, AtomicU8, Ordering},
    Arc, Mutex,
};

pub(super) fn bind(
    slot: &Mutex<Option<Arc<dyn TransactionStagingObserver>>>,
    acquired: &AtomicU8,
    guest_closed: &AtomicBool,
    released: &AtomicBool,
    observer: Arc<dyn TransactionStagingObserver>,
) -> Result<(), StateFailure> {
    let mut original = slot.lock().map_err(|_| StateFailure::Unavailable)?;
    if original.is_some()
        || acquired.load(Ordering::Acquire) != 0
        || guest_closed.load(Ordering::Acquire)
        || released.load(Ordering::Acquire)
    {
        return Err(StateFailure::HandleClosed);
    }
    *original = Some(observer);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_executor::transaction::TransactionStagingProgress;

    struct Observer;
    impl TransactionStagingObserver for Observer {
        fn observe(&self, _: TransactionStagingProgress) {}
    }

    #[test]
    fn staging_observer_binding_refuses_closed_released_and_reused_guest_access() {
        for (acquired, closed, released) in [
            (1, false, false),
            (2, false, false),
            (0, true, false),
            (0, false, true),
        ] {
            let slot = Mutex::new(None);
            assert_eq!(
                bind(
                    &slot,
                    &AtomicU8::new(acquired),
                    &AtomicBool::new(closed),
                    &AtomicBool::new(released),
                    Arc::new(Observer)
                ),
                Err(StateFailure::HandleClosed)
            );
            assert!(slot.lock().unwrap().is_none());
        }
        let slot = Mutex::new(None);
        let flags = (
            AtomicU8::new(0),
            AtomicBool::new(false),
            AtomicBool::new(false),
        );
        bind(&slot, &flags.0, &flags.1, &flags.2, Arc::new(Observer)).unwrap();
        assert_eq!(
            bind(&slot, &flags.0, &flags.1, &flags.2, Arc::new(Observer)),
            Err(StateFailure::HandleClosed)
        );
    }

    #[test]
    fn competing_trusted_staging_observers_bind_exactly_one_original_slot() {
        let slot = Arc::new(Mutex::new(None));
        let flags = Arc::new((
            AtomicU8::new(0),
            AtomicBool::new(false),
            AtomicBool::new(false),
        ));
        let barrier = Arc::new(std::sync::Barrier::new(3));
        let threads = (0..2)
            .map(|_| {
                let slot = Arc::clone(&slot);
                let flags = Arc::clone(&flags);
                let barrier = Arc::clone(&barrier);
                std::thread::spawn(move || {
                    barrier.wait();
                    bind(&slot, &flags.0, &flags.1, &flags.2, Arc::new(Observer))
                })
            })
            .collect::<Vec<_>>();
        barrier.wait();
        let results = threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(
            results
                .iter()
                .filter(|result| **result == Err(StateFailure::HandleClosed))
                .count(),
            1
        );
        assert!(slot.lock().unwrap().is_some());
    }
}
