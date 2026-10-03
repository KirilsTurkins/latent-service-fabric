//! Hold the actual signed authority after activation-start authorization, at
//! the original capability session's plan lookup. No guest work is replayed.
#![cfg(target_os = "linux")]
#[path = "broker/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "broker/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "clock_admission/signed.rs"]
#[allow(dead_code)]
mod signed;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::*;
use latent_artifacts::{ArtifactRepository, ReleaseUseEligibility};
use latent_core::PlatformErrorCode;
use std::{
    future::Future,
    pin::Pin,
    sync::{mpsc, Mutex},
    task::Poll,
};

struct Fence {
    release: Option<mpsc::SyncSender<()>>,
    worker: Option<std::thread::JoinHandle<Result<(), PlatformError>>>,
}
impl Fence {
    fn hold(eligibility: &ReleaseUseEligibility) -> Self {
        let grant = eligibility.admission().unwrap().clone();
        let (entered_send, entered) = mpsc::sync_channel(1);
        let (release, released) = mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || {
            grant.with_current(&mut |_| {
                entered_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(10)).unwrap();
                Ok(())
            })
        });
        let fence = Self {
            release: Some(release),
            worker: Some(worker),
        };
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        fence
    }
    fn release(mut self) {
        self.release.take().unwrap().send(()).unwrap();
        self.worker.take().unwrap().join().unwrap().unwrap();
    }
}
impl Drop for Fence {
    fn drop(&mut self) {
        if let Some(release) = self.release.take() {
            let _ = release.send(());
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn hold_at_session_lookup(f: &Fixture) -> Arc<Mutex<Option<Fence>>> {
    let eligibility = f
        .catalog
        .execution_eligibility_selected(&f.revision.release, f.revision.publication.as_ref())
        .unwrap()
        .unwrap();
    let held = Arc::new(Mutex::new(None));
    let keep = Arc::clone(&held);
    *f.plan_lookup_hook.lock().unwrap() = Some(Box::new(move || {
        *keep.lock().unwrap() = Some(Fence::hold(&eligibility));
    }));
    held
}

async fn pending_at_session(
    mut invocation: Pin<&mut impl Future<Output = latent_executor::ExecutionReport>>,
    held: &Arc<Mutex<Option<Fence>>>,
) {
    tokio::time::timeout(
        Duration::from_secs(5),
        std::future::poll_fn(|context| match invocation.as_mut().poll(context) {
            Poll::Ready(report) => {
                panic!("original session must wait before allocation: {report:?}")
            }
            Poll::Pending if held.lock().unwrap().is_some() => Poll::Ready(()),
            Poll::Pending => Poll::Pending,
        }),
    )
    .await
    .expect("bounded original session fence observation");
}

fn untouched(f: &Fixture, control: &fixture::Control, metadata: usize) {
    assert_eq!(f.backend.active_instance_reservations(), 1);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    let snapshot = f.broker.snapshot();
    assert_eq!(
        (snapshot.sessions, snapshot.calls, snapshot.handles),
        (0, 0, 0)
    );
    assert_eq!(snapshot.metadata_bytes, metadata);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn session_authority_wait_opens_once_and_executes_each_original_import_once() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = hold_at_session_lookup(f);
    let (request, control) = f.request("session-authority-contention");
    let metadata = f.broker.snapshot().metadata_bytes;
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let reads = f.catalog.verification_snapshot();
    let observed = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let keep = Arc::clone(&observed);
    let broker = Arc::clone(&f.broker);
    *f.clock.hook.lock().unwrap() = Some(Box::new(move || {
        keep.store(broker.snapshot().sessions, Ordering::Release);
    }));
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_session(invocation.as_mut(), &held).await;
    untouched(f, &control, metadata);
    held.lock().unwrap().take().unwrap().release();
    let report = invocation.await;
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let GuestOutcome::Returned { consumption, .. } = report.outcome.unwrap() else {
        panic!("one actual component invocation must finish");
    };
    assert_eq!(observed.load(Ordering::Acquire), 1);
    assert_eq!(f.backend.resource_snapshot().stores_created, 1);
    // This actual component contains exactly two clock imports. Both dispatch
    // once, and the original activation ledger owns both 100-fuel charges.
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 2);
    let finalized = control
        .budget
        .finalize_at(Some(&consumption), Instant::now());
    assert!(finalized.violation().is_none());
    assert_eq!(finalized.consumption().cpu_fuel, consumption.cpu_fuel + 200);
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    assert_eq!(f.catalog.verification_snapshot(), reads);
    f.idle();
}

#[tokio::test]
async fn session_authority_wait_observes_original_cancellation_and_deadline() {
    for cancelled in [true, false] {
        let signed = signed::Fixture::new(true).await;
        let f = &signed.guest;
        let held = hold_at_session_lookup(f);
        let (mut request, mut control) = f.request("session-authority-stop");
        request.budget.wall_time_limit_millis = Some(100);
        request.activation.budget = request.budget.clone();
        control.budget = latent_core::ActivationBudget::new(
            latent_core::EffectiveActivationBudget::admit_at(
                &request.budget,
                &request.budget,
                &request.budget,
                None,
                ClockSample::system_now(),
            )
            .unwrap(),
        );
        request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
        let metadata = f.broker.snapshot().metadata_bytes;
        let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
        pending_at_session(invocation.as_mut(), &held).await;
        untouched(f, &control, metadata);
        if cancelled {
            control.probe.0.store(true, Ordering::Release);
        }
        let report = tokio::time::timeout(Duration::from_secs(1), invocation)
            .await
            .unwrap();
        let GuestOutcome::Interrupted {
            kind, consumption, ..
        } = report.outcome.unwrap()
        else {
            panic!("original stop must precede session and Store allocation");
        };
        assert_eq!(
            kind,
            if cancelled {
                latent_executor::GuestInterruptionKind::Cancelled
            } else {
                latent_executor::GuestInterruptionKind::DeadlineExceeded
            }
        );
        assert_eq!(
            (consumption.cpu_fuel, consumption.peak_memory_bytes),
            (0, 0)
        );
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        held.lock().unwrap().take().unwrap().release();
        assert_eq!(f.backend.resource_snapshot().stores_created, 0);
        f.idle();
    }
}

#[tokio::test]
async fn session_authority_wait_never_replaces_revoked_original_publication() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let eligibility = f
        .catalog
        .execution_eligibility_selected(&f.revision.release, f.revision.publication.as_ref())
        .unwrap()
        .unwrap();
    let held = hold_at_session_lookup(f);
    let (request, control) = f.request("session-authority-revoked");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_session(invocation.as_mut(), &held).await;
    held.lock().unwrap().take().unwrap().release();
    f.catalog
        .change_publication_lifecycle(
            latent_artifacts::ReleaseMutationContext {
                scope: eligibility.scope().clone(),
                actor: latent_artifacts::ReleaseActor {
                    subject: "session-revocation-control".into(),
                    kind: latent_artifacts::ReleaseActorKind::Host,
                },
                operation: Some(latent_artifacts::ReleaseOperationPrecondition {
                    operation_id: "revoke-session-original".into(),
                    expected_generation: eligibility.generation(),
                }),
            },
            &latent_artifacts::PublicationRef {
                id: eligibility.publication().clone(),
                scope: eligibility.scope().clone(),
            },
            latent_artifacts::ReleaseLifecycleAction::Revoke,
            latent_artifacts::ReleaseLifecycleReason::SecurityIncident,
            &mut |_| Ok(()),
        )
        .unwrap();
    let report = invocation.await;
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert!(eligibility.check_current().is_err());
    f.idle();
}

#[tokio::test]
async fn session_authority_wait_preserves_expired_original_lease() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = hold_at_session_lookup(f);
    let (request, control) = f.request("session-authority-expired");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_session(invocation.as_mut(), &held).await;
    signed.expire_original_lease();
    held.lock().unwrap().take().unwrap().release();
    let report = invocation.await;
    let error = report.outcome.unwrap_err();
    assert_eq!(
        error.details[0].fields.get("reason").map(String::as_str),
        Some("admission-clock-lease-uncovered")
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    f.idle();
}

#[tokio::test]
async fn dropping_session_authority_wait_reclaims_original_owner_without_allocating_session() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = hold_at_session_lookup(f);
    let (request, control) = f.request("session-authority-dropped");
    let metadata = f.broker.snapshot().metadata_bytes;
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_session(invocation.as_mut(), &held).await;
    untouched(f, &control, metadata);
    drop(invocation);
    held.lock().unwrap().take().unwrap().release();
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    f.idle();
}

#[tokio::test]
async fn timerless_session_authority_and_actual_session_capacity_remain_immediate() {
    let signed = signed::Fixture::new(false).await;
    let f = &signed.guest;
    let held = hold_at_session_lookup(f);
    let (request, control) = f.request("session-authority-timerless");
    let report = f.backend.invoke_contained(request, &control).await;
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::Unavailable
    );
    held.lock().unwrap().take().unwrap().release();
    f.idle();
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);

    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let publication = f
        .catalog
        .execution_eligibility_selected(&f.revision.release, f.revision.publication.as_ref())
        .unwrap()
        .unwrap();
    let mut sessions = Vec::new();
    for index in 0..CapabilityBrokerLimits::default().maximum_sessions {
        let (request, control) = f.request(&format!("session-capacity-{index}"));
        sessions.push(
            f.runtime
                .open_session(&request, &control, &publication, control.budget.deadline())
                .unwrap(),
        );
    }
    let (request, control) = f.request("session-capacity-rejection");
    let started = Instant::now();
    let report = f.backend.invoke_contained(request, &control).await;
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(started.elapsed() < Duration::from_secs(1));
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    drop(sessions);
    f.idle();
}
