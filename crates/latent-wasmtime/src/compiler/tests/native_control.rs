use super::support::{complete, config, idle, pool, waiting};
use crate::aot::supervisor::{AotPreparedInput, InputFixture};
use crate::compiler::{CoalescingKey, CompilationResult, CompilerPool, PreparationWait};
use latent_core::PlatformErrorCode;
use latent_executor::PreparationKey;
use std::sync::{mpsc, Arc};
use std::time::Duration;

fn identity(input: &AotPreparedInput) -> CoalescingKey {
    CoalescingKey {
        key: PreparationKey {
            release: input.artifact().descriptor.release_digest.clone(),
            engine_version: "native-control-test".into(),
            engine_configuration_digest: "native-control-test".into(),
            target_triple: "native-control-test".into(),
            cpu_feature_set: "native-control-test".into(),
        },
        source: input.preparation_identity().unwrap().clone(),
        eligibility: Some(input.eligibility().clone()),
    }
}

/// Unblocks the worker even when a parent-side assertion unwinds.
struct Release(Option<mpsc::SyncSender<()>>);
impl Release {
    fn now(mut self) {
        self.0.take().unwrap().send(()).unwrap();
    }
}
impl Drop for Release {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

fn blocked_native(
    pool: &CompilerPool<u8>,
    waiter: &PreparationWait<u8>,
    input: Arc<AotPreparedInput>,
) -> Release {
    waiter.reserve_documents(64).unwrap();
    let observer = pool.core.observer.clone();
    let (started_send, started) = mpsc::sync_channel(1);
    let (release, released) = mpsc::sync_channel(1);
    let release = Release(Some(release));
    waiter
        .start_with_control(Some(input.control()), move |reservation| {
            Box::new(move |queue| {
                input.check()?;
                let observation = observer.begin(&input.artifact().descriptor.release_digest);
                observation.record_queue_wait(queue.started_nanos, queue.finished_nanos);
                started_send.send(()).unwrap();
                released
                    .recv_timeout(Duration::from_secs(5))
                    .expect("bounded test release");
                // Cancellation is inspected only after the deliberate blocking
                // rendezvous: signaling must not refund the still-owned task early.
                input.check()?;
                drop(input);
                Ok(CompilationResult {
                    runtime: Arc::new(7),
                    reservation: Some(reservation),
                    observation,
                })
            })
        })
        .unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    release
}

fn assert_held(pool: &CompilerPool<u8>) {
    let snapshot = pool.observer().snapshot();
    assert_eq!(snapshot.running_jobs, 1);
    assert_eq!(snapshot.reserved_document_bytes, 64);
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
}

fn assert_retired(pool: &CompilerPool<u8>) {
    idle(pool);
    let snapshot = pool.observer().snapshot();
    assert_eq!(snapshot.running_jobs, 0);
    assert_eq!(snapshot.reserved_document_bytes, 0);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
}

#[test]
fn cancelling_one_coalesced_waiter_preserves_native_input_and_surviving_result() {
    let fixture = InputFixture::new();
    let input = Arc::new(fixture.read());
    let pool = pool(&config());
    let identity = identity(&input);
    let (first, owner) = waiting(&pool, "shared-native", Some(identity.clone()));
    assert!(owner);
    let release = blocked_native(&pool, &first, Arc::clone(&input));
    let (second, owner) = waiting(&pool, "shared-native", Some(identity));
    assert!(!owner);
    drop(first);
    assert!(input.check().is_ok());
    assert_held(&pool);
    release.now();
    drop(complete(second).unwrap());
    assert_retired(&pool);
    assert!(input.check().is_ok());
    assert_eq!(Arc::strong_count(&input), 1);
    assert_eq!(pool.observer().snapshot().jobs_completed, 1);
}

#[test]
fn last_coalesced_waiter_cancellation_signals_but_retains_running_reservations() {
    let fixture = InputFixture::new();
    let input = Arc::new(fixture.read());
    let pool = pool(&config());
    let identity = identity(&input);
    let (first, _) = waiting(&pool, "cancel-native", Some(identity.clone()));
    let release = blocked_native(&pool, &first, Arc::clone(&input));
    let (second, owner) = waiting(&pool, "cancel-native", Some(identity));
    assert!(!owner);
    drop(first);
    assert!(input.check().is_ok());
    drop(second);
    assert_eq!(
        input.check().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert_held(&pool);
    assert_eq!(Arc::strong_count(&input), 2);
    release.now();
    assert_retired(&pool);
    assert_eq!(Arc::strong_count(&input), 1);
    assert_eq!(pool.observer().snapshot().discarded_results, 1);
    assert_eq!(pool.core.cache.snapshot().entries, 0);
}

#[test]
fn pool_stop_signals_native_control_before_actual_task_retirement() {
    let fixture = InputFixture::new();
    let input = Arc::new(fixture.read());
    let mut pool = pool(&config());
    let (waiter, _) = waiting(&pool, "stop-native", Some(identity(&input)));
    let release = blocked_native(&pool, &waiter, Arc::clone(&input));
    let shutdown = pool.quiesce();
    assert_eq!(
        input.check().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert_held(&pool);
    assert!(complete(waiter).is_err());
    assert_held(&pool);
    release.now();
    complete(shutdown).unwrap();
    assert_retired(&pool);
    assert_eq!(Arc::strong_count(&input), 1);
    pool.stop_and_join().unwrap();
    assert_eq!(pool.observer().snapshot().workers_joined, 2);
    assert_eq!(pool.core.cache.snapshot().entries, 0);
}
