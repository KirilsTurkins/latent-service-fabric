//! These tests execute the maintained provider against actual TCP peers and
//! sealed broker sessions. They are native-provider evidence, separate from
//! the component and standard-library qualification gate.
use super::{config, fixture::Fixture};
use crate::StreamErrorCode;
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamInterest, StreamShutdown, StreamState,
};
use latent_policy::capability::{MutationRequest, RecordKind};
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn fixture() -> (Fixture, TcpListener) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    (Fixture::new(config), listener)
}
fn request(fixture: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: fixture.provider.inner.config.destinations[0]
            .endpoint
            .clone(),
        timeout_millis: None,
    }
}

struct ConnectBusyFence {
    busy: std::sync::atomic::AtomicBool,
    observations: std::sync::atomic::AtomicUsize,
    allow_once: std::sync::atomic::AtomicBool,
    successes: std::sync::atomic::AtomicUsize,
}

impl latent_capabilities::broker::CapabilityRouteFence for ConnectBusyFence {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), latent_core::PlatformError>,
    ) -> Result<(), latent_core::PlatformError> {
        use std::sync::atomic::Ordering;
        if self.busy.load(Ordering::Acquire) && !self.allow_once.swap(false, Ordering::AcqRel) {
            self.observations.fetch_add(1, Ordering::AcqRel);
            return Err(latent_core::PlatformError {
                code: latent_core::PlatformErrorCode::ResourceExhausted,
                message: "capability-busy".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        let result = action();
        if result.is_ok() {
            self.successes.fetch_add(1, Ordering::AcqRel);
        }
        result
    }
}

fn install_connect_busy_fence(fixture: &mut Fixture, fence: std::sync::Arc<ConnectBusyFence>) {
    use latent_capabilities::broker::CapabilityBindingSpec;

    let reference = fixture.provider.reference();
    let definition = latent_artifacts::package::artifact_blob_digest(b"stream-fixture-binding-v1");
    let operations = super::fixture::OPERATIONS.map(str::to_owned);
    let policies = ["p".to_owned()];
    let deployment = latent_core::DeploymentId("stream-deployment".into());
    fixture.plan = fixture
        .broker
        .compile_invocation_plan(
            &fixture.revision,
            Some(&deployment),
            &[CapabilityBindingSpec {
                definition_digest: Some(&definition),
                provider: &reference,
                imported_operations: &operations,
                policy_ids: &policies,
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &fixture.publication,
            &[],
            &[],
            &[],
            Some(fence),
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap();
}

async fn reach_handoff_audit<F: std::future::Future + Unpin>(
    future: &mut F,
    reached: tokio::sync::oneshot::Receiver<()>,
) {
    tokio::select! {
        _ = future => panic!("operation completed before the audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), reached) => reached.unwrap().unwrap(),
    }
}

async fn hold_handoff_busy<F: std::future::Future + Unpin>(
    future: &mut F,
    release: tokio::sync::oneshot::Sender<()>,
    fence: &ConnectBusyFence,
) {
    use std::sync::atomic::Ordering;
    fence.busy.store(true, Ordering::Release);
    release.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            tokio::select! {
                _ = &mut *future => panic!("bookkeeping contention prematurely settled handoff"),
                () = tokio::task::yield_now() => {}
            }
            if fence.observations.load(Ordering::Acquire) != 0 {
                break;
            }
        }
    })
    .await
    .unwrap();
}

async fn handoff_busy_fixture() -> (Fixture, TcpListener, std::sync::Arc<ConnectBusyFence>) {
    let (mut fixture, listener) = fixture().await;
    let fence = std::sync::Arc::new(ConnectBusyFence {
        busy: std::sync::atomic::AtomicBool::new(false),
        observations: std::sync::atomic::AtomicUsize::new(0),
        allow_once: std::sync::atomic::AtomicBool::new(false),
        successes: std::sync::atomic::AtomicUsize::new(0),
    });
    install_connect_busy_fence(&mut fixture, fence.clone());
    (fixture, listener, fence)
}

#[tokio::test]
async fn write_handoff_retries_bookkeeping_busy_without_replay() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (mut fixture, listener) = fixture().await;
    let fence = std::sync::Arc::new(ConnectBusyFence {
        busy: std::sync::atomic::AtomicBool::new(false),
        observations: std::sync::atomic::AtomicUsize::new(0),
        allow_once: std::sync::atomic::AtomicBool::new(false),
        successes: std::sync::atomic::AtomicUsize::new(0),
    });
    install_connect_busy_fence(&mut fixture, fence.clone());
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let mut write = stream.write(b"ONCE".to_vec(), None).unwrap();
    reach_handoff_audit(&mut write, entered).await;
    let mut bytes = [0; 4];
    peer.read_exact(&mut bytes).await.unwrap();
    assert_eq!(&bytes, b"ONCE");
    let before_checks = fence.successes.load(Ordering::Acquire);
    fence.allow_once.store(true, Ordering::Release);
    hold_handoff_busy(&mut write, release, &fence).await;
    // The original connect check passed; the operation check is busy.
    assert_eq!(fence.successes.load(Ordering::Acquire), before_checks + 1);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    fence.busy.store(false, Ordering::Release);
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), write)
            .await
            .unwrap()
            .unwrap(),
        4
    );
    // Retry must check both original authorities, not just the busy one.
    assert_eq!(fence.successes.load(Ordering::Acquire), before_checks + 3);
    assert_eq!(stream.inspect().state, StreamState::Open);
    drop(held_read);
    stream.close().await.unwrap();
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((owner, peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_eof_read_during_handoff_busy_fences_original_owner() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (mut fixture, listener) = fixture().await;
    let fence = std::sync::Arc::new(ConnectBusyFence {
        busy: std::sync::atomic::AtomicBool::new(false),
        observations: std::sync::atomic::AtomicUsize::new(0),
        allow_once: std::sync::atomic::AtomicBool::new(false),
        successes: std::sync::atomic::AtomicUsize::new(0),
    });
    install_connect_busy_fence(&mut fixture, fence.clone());
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    peer.shutdown().await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    reach_handoff_audit(&mut read, entered).await;
    assert_eq!(stream.inspect().state, StreamState::ReadEof);
    hold_handoff_busy(&mut read, release, &fence).await;
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    drop(read);
    fence.busy.store(false, Ordering::Release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert_eq!(
        stream.read(1, None).err().unwrap().code,
        StreamErrorCode::Cancelled
    );
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_during_handoff_busy_keeps_accepted_prefix() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (fixture, listener, fence) = handoff_busy_fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let mut write = stream.write(b"ONCE".to_vec(), None).unwrap();
    reach_handoff_audit(&mut write, entered).await;
    let mut bytes = [0; 4];
    peer.read_exact(&mut bytes).await.unwrap();
    assert_eq!(&bytes, b"ONCE");
    hold_handoff_busy(&mut write, release, &fence).await;
    drop(write);
    fence.busy.store(false, Ordering::Release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let failure = stream.write(b"retry".to_vec(), None).err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(failure.may_have_applied);
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn write_handoff_busy_deadline_reports_accepted_prefix() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (fixture, listener, fence) = handoff_busy_fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let mut write = stream.write(b"ONCE".to_vec(), Some(1000)).unwrap();
    reach_handoff_audit(&mut write, entered).await;
    let mut bytes = [0; 4];
    peer.read_exact(&mut bytes).await.unwrap();
    assert_eq!(&bytes, b"ONCE");
    hold_handoff_busy(&mut write, release, &fence).await;
    let failure = tokio::time::timeout(Duration::from_secs(2), write)
        .await
        .unwrap()
        .unwrap_err();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert_eq!(failure.accepted_prefix_bytes, 4);
    assert!(failure.may_have_applied);
    fence.busy.store(false, Ordering::Release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_send_shutdown_during_handoff_busy_fences_original_owner() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (fixture, listener, fence) = handoff_busy_fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let mut shutdown = stream.shutdown(StreamShutdown::Send).unwrap();
    reach_handoff_audit(&mut shutdown, entered).await;
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    hold_handoff_busy(&mut shutdown, release, &fence).await;
    drop(shutdown);
    fence.busy.store(false, Ordering::Release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    drop(held_read);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[derive(Clone, Copy)]
enum BusyCompletion {
    Resume,
    Abandon,
    Expire,
}

#[expect(
    clippy::too_many_lines,
    reason = "One original connected owner through busy currentness and retirement."
)]
async fn connect_final_busy_case(completion: BusyCompletion) {
    use std::sync::atomic::Ordering;

    let (mut fixture, listener) = fixture().await;
    let fence = std::sync::Arc::new(ConnectBusyFence {
        busy: std::sync::atomic::AtomicBool::new(false),
        observations: std::sync::atomic::AtomicUsize::new(0),
        allow_once: std::sync::atomic::AtomicBool::new(false),
        successes: std::sync::atomic::AtomicUsize::new(0),
    });
    install_connect_busy_fence(&mut fixture, fence.clone());
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let (entered, reached) = tokio::sync::oneshot::channel();
    let (release, resume) = tokio::sync::oneshot::channel();
    assert!(fixture
        .provider
        .inner
        .connect_audit_gate
        .lock()
        .unwrap()
        .replace((entered, resume))
        .is_none());
    let mut requested = request(&fixture);
    if matches!(completion, BusyCompletion::Expire) {
        requested.timeout_millis = Some(1000);
    }
    let mut connecting = fixture.provider.start(&session, requested).unwrap();
    tokio::select! {
        _ = &mut connecting => panic!("connect completed before the audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), reached) => reached.unwrap().unwrap(),
    }
    let (mut peer, _) = listener.accept().await.unwrap();
    fence.busy.store(true, Ordering::Release);
    release.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            tokio::select! {
                _ = &mut connecting => panic!("bookkeeping contention prematurely settled connect"),
                () = tokio::task::yield_now() => {}
            }
            if fence.observations.load(Ordering::Acquire) != 0 {
                break;
            }
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let retained = if matches!(completion, BusyCompletion::Abandon) {
        Some(
            fixture
                .provider
                .inner
                .connections
                .snapshot(0)
                .unwrap()
                .expect("original registered connection"),
        )
    } else {
        None
    };
    match completion {
        BusyCompletion::Abandon => {
            drop(connecting);
            fence.busy.store(false, Ordering::Release);
        }
        BusyCompletion::Resume => {
            fence.busy.store(false, Ordering::Release);
            let stream = tokio::time::timeout(Duration::from_secs(1), connecting)
                .await
                .unwrap()
                .unwrap();
            assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
            let mut byte = [0];
            peer.read_exact(&mut byte).await.unwrap();
            assert_eq!(&byte, b"X");
            stream.close().await.unwrap();
        }
        BusyCompletion::Expire => {
            let failure = tokio::time::timeout(Duration::from_secs(2), connecting)
                .await
                .unwrap()
                .err()
                .expect("busy connect exceeded its original deadline");
            assert_eq!(failure.code, StreamErrorCode::Timeout);
            assert!(!failure.may_have_applied);
            fence.busy.store(false, Ordering::Release);
        }
    }
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    if let Some(retained) = retained {
        let held_bytes = control.budget.host_memory_bytes();
        assert!(held_bytes > baseline);
        drop(retained);
        assert!(control.budget.host_memory_bytes() < held_bytes);
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(20), listener.accept())
            .await
            .is_err()
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn connect_final_bookkeeping_contention_reuses_original_connection() {
    connect_final_busy_case(BusyCompletion::Resume).await;
}

#[tokio::test]
async fn connect_final_bookkeeping_contention_respects_original_deadline() {
    connect_final_busy_case(BusyCompletion::Expire).await;
}

#[tokio::test]
async fn dropped_connect_while_final_bookkeeping_busy_retires_original_connection() {
    connect_final_busy_case(BusyCompletion::Abandon).await;
}

#[derive(Clone, Copy)]
enum ConnectAuditInterruption {
    Revoked,
    Cancelled,
    Expired,
    Abandoned,
}

async fn connect_audit_interrupted(interruption: ConnectAuditInterruption) {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let (entered, reached) = tokio::sync::oneshot::channel();
    let (release, resume) = tokio::sync::oneshot::channel();
    assert!(fixture
        .provider
        .inner
        .connect_audit_gate
        .lock()
        .unwrap()
        .replace((entered, resume))
        .is_none());
    let mut requested = request(&fixture);
    if matches!(interruption, ConnectAuditInterruption::Expired) {
        requested.timeout_millis = Some(1000);
    }
    let mut connecting = fixture.provider.start(&session, requested).unwrap();
    tokio::select! {
        _ = &mut connecting => panic!("connect completed before the audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), reached) => reached.unwrap().unwrap(),
    }
    let (mut peer, _) = tokio::time::timeout(Duration::from_secs(1), listener.accept())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let expected = match interruption {
        ConnectAuditInterruption::Revoked => {
            fixture
                .policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id: "p",
                        kind: RecordKind::Policy,
                        operation_id: "revoke-connect-during-audit",
                        expected_revision: 2,
                        document: None,
                    },
                    Instant::now() + Duration::from_secs(1),
                    |_| Ok(()),
                )
                .unwrap();
            Some(StreamErrorCode::Denied)
        }
        ConnectAuditInterruption::Cancelled => {
            control
                .probe
                .0
                .store(true, std::sync::atomic::Ordering::Release);
            Some(StreamErrorCode::Cancelled)
        }
        ConnectAuditInterruption::Expired => {
            tokio::time::sleep(Duration::from_millis(1100)).await;
            Some(StreamErrorCode::Timeout)
        }
        ConnectAuditInterruption::Abandoned => None,
    };
    if let Some(expected) = expected {
        release.send(()).unwrap();
        let failure = tokio::time::timeout(Duration::from_secs(1), connecting)
            .await
            .unwrap()
            .err()
            .expect("stale connect returned a handle");
        assert_eq!(failure.code, expected);
        assert_eq!(failure.accepted_prefix_bytes, 0);
        assert!(!failure.may_have_applied);
    } else {
        drop(connecting);
        drop(release);
    }
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn connect_revocation_during_audit_refuses_handoff() {
    connect_audit_interrupted(ConnectAuditInterruption::Revoked).await;
}

#[tokio::test]
async fn connect_cancellation_during_audit_refuses_handoff() {
    connect_audit_interrupted(ConnectAuditInterruption::Cancelled).await;
}

#[tokio::test]
async fn connect_deadline_during_audit_refuses_handoff() {
    connect_audit_interrupted(ConnectAuditInterruption::Expired).await;
}

#[tokio::test]
async fn connect_dropped_during_audit_retires_original_socket() {
    connect_audit_interrupted(ConnectAuditInterruption::Abandoned).await;
}

async fn connect_registration_interrupted(interruption: ConnectAuditInterruption) {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let (reached, resume) = fixture.provider.inner.connections.pause_next_registration();
    let mut requested = request(&fixture);
    if matches!(interruption, ConnectAuditInterruption::Expired) {
        requested.timeout_millis = Some(1000);
    }
    let connecting = tokio::spawn(fixture.provider.start(&session, requested).unwrap());
    let (mut peer, _) = tokio::time::timeout(Duration::from_secs(1), listener.accept())
        .await
        .unwrap()
        .unwrap();
    tokio::task::spawn_blocking(move || reached.recv_timeout(Duration::from_secs(3)))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let expected = match interruption {
        ConnectAuditInterruption::Revoked => {
            fixture
                .policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id: "p",
                        kind: RecordKind::Policy,
                        operation_id: "revoke-connect-before-registration",
                        expected_revision: 2,
                        document: None,
                    },
                    Instant::now() + Duration::from_secs(1),
                    |_| Ok(()),
                )
                .unwrap();
            StreamErrorCode::Denied
        }
        ConnectAuditInterruption::Cancelled => {
            control
                .probe
                .0
                .store(true, std::sync::atomic::Ordering::Release);
            StreamErrorCode::Cancelled
        }
        ConnectAuditInterruption::Expired => {
            // The existing registration gate blocks a runtime worker. Wait on
            // this test thread so the deadline does not depend on that driver.
            std::thread::sleep(Duration::from_millis(1100));
            StreamErrorCode::Timeout
        }
        ConnectAuditInterruption::Abandoned => unreachable!(),
    };
    resume.send(()).unwrap();
    let failure = tokio::time::timeout(Duration::from_secs(1), connecting)
        .await
        .unwrap()
        .unwrap()
        .err()
        .expect("stale connect returned a handle");
    assert_eq!(failure.code, expected);
    assert!(!failure.may_have_applied);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connect_policy_revocation_before_registration_refuses_handoff() {
    connect_registration_interrupted(ConnectAuditInterruption::Revoked).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connect_cancellation_before_registration_refuses_handoff() {
    connect_registration_interrupted(ConnectAuditInterruption::Cancelled).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connect_deadline_before_registration_refuses_handoff() {
    connect_registration_interrupted(ConnectAuditInterruption::Expired).await;
}

#[tokio::test]
async fn actual_tcp_partial_reads_eof_and_send_half_close() {
    let (fixture, listener) = fixture().await;
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut message = Vec::new();
        socket.read_to_end(&mut message).await.unwrap();
        assert_eq!(message, b"PING");
        socket.write_all(b"one").await.unwrap();
        socket.write_all(b"two").await.unwrap();
        socket.shutdown().await.unwrap();
    });
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert!(control.budget.host_memory_bytes() > 0);
    assert_eq!(
        stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Send)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::WriteShut
    );
    let mut received = Vec::new();
    while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
        let bytes = chunk.copy_bytes().unwrap();
        assert!(!bytes.is_empty() && bytes.len() <= 2);
        received.extend_from_slice(&bytes);
    }
    assert_eq!(received, b"onetwo");
    assert_eq!(stream.inspect().state, StreamState::ReadEofWriteShut);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().delivered_read_bytes, 6);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.close().await.unwrap().state, StreamState::Closed);
    peer.await.unwrap();
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn retained_chunks_keep_original_charges_after_socket_close() {
    let (fixture, listener) = fixture().await;
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        socket.write_all(&vec![0x5a; 32 * 1024]).await.unwrap();
        let mut eof = [0u8; 1];
        assert_eq!(socket.read(&mut eof).await.unwrap(), 0);
    });
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let mut first = stream
        .read(16 * 1024, None)
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let mut second = stream
        .read(16 * 1024, None)
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        stream.read(16 * 1024, None).err().unwrap().code,
        StreamErrorCode::Exhausted
    );
    let mut produced = false;
    assert_eq!(
        stream
            .write_from(1, None, &mut || {
                produced = true;
                Ok(vec![0x5a])
            })
            .err()
            .unwrap()
            .code,
        StreamErrorCode::Exhausted
    );
    assert!(
        !produced,
        "the full window denies before canonical host copying"
    );
    let before = control.budget.host_memory_bytes();
    assert!(before >= 64 * 1024);
    stream.close().await.unwrap();
    peer.await.unwrap();
    let usage = fixture.provider.usage().unwrap();
    assert_eq!(usage.connections, 0);
    assert_eq!(usage.retained_chunks, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    assert!(control.budget.host_memory_bytes() >= 64 * 1024);
    let first_bytes = first.copy_bytes().unwrap();
    let second_bytes = second.copy_bytes().unwrap();
    assert!(first_bytes
        .iter()
        .chain(second_bytes.iter())
        .all(|b| *b == 0x5a));
    drop(first_bytes);
    drop(second_bytes);
    drop(first);
    drop(second);
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_facade_does_not_refund_an_unpolled_pending_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let pending = stream.read(16 * 1024, None).unwrap();
    drop(stream);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    drop(pending);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_before_dispatch_keeps_the_same_connection_usable() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::BeforeDispatch);
    drop(owner);
    let mut write = stream.write(b"NEVER".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before the pre-dispatch gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert_eq!(
        stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"LIVE");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_after_synthetic_no_progress_keeps_the_same_connection_usable() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_write_none_once();
    let (entered, release) = owner.test_write_gate(TestWritePoint::NoProgress);
    drop(owner);
    let mut write = stream.write(b"NEVER".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before no-progress gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert_eq!(
        stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"LIVE");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_during_synthetic_audit_wait_keeps_original_owners_and_never_replays() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut write = stream.write(b"ONCE".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before the audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"ONCE");
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let mut copied = false;
    let failure = stream
        .write_from(1, None, &mut || {
            copied = true;
            Ok(vec![0])
        })
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(failure.may_have_applied);
    assert!(!copied);
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), listener.accept())
            .await
            .is_err()
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[derive(Clone, Copy)]
enum WriteAuditInterruption {
    Revoked,
    Cancelled,
    Expired,
}

#[expect(
    clippy::too_many_lines,
    reason = "One original TCP connection and accepted write through retirement."
)]
async fn write_audit_interrupted(interruption: WriteAuditInterruption) {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let timeout = matches!(interruption, WriteAuditInterruption::Expired).then_some(1000);
    let mut write = stream.write(b"ONCE".to_vec(), timeout).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before the audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(&bytes, b"ONCE");
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let expected = match interruption {
        WriteAuditInterruption::Revoked => {
            fixture
                .policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id: "p",
                        kind: RecordKind::Policy,
                        operation_id: "revoke-write-during-audit",
                        expected_revision: 2,
                        document: None,
                    },
                    Instant::now() + Duration::from_secs(1),
                    |_| Ok(()),
                )
                .unwrap();
            StreamErrorCode::Denied
        }
        WriteAuditInterruption::Cancelled => {
            control
                .probe
                .0
                .store(true, std::sync::atomic::Ordering::Release);
            StreamErrorCode::Cancelled
        }
        WriteAuditInterruption::Expired => {
            tokio::time::sleep(Duration::from_millis(1100)).await;
            StreamErrorCode::Timeout
        }
    };
    release.send(()).unwrap();
    let failure = tokio::time::timeout(Duration::from_secs(1), write)
        .await
        .unwrap()
        .err()
        .expect("interrupted write returned a successful count");
    assert_eq!(failure.code, expected);
    assert_eq!(failure.accepted_prefix_bytes, 4);
    assert!(failure.may_have_applied);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let mut copied = false;
    let failure = stream
        .write_from(1, None, &mut || {
            copied = true;
            Ok(vec![0])
        })
        .err()
        .expect("stopped connection admitted another write");
    assert_eq!(failure.code, expected);
    assert!(failure.may_have_applied);
    assert!(!copied);
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), listener.accept())
            .await
            .is_err()
    );
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn write_revocation_during_successful_audit_preserves_accepted_prefix() {
    write_audit_interrupted(WriteAuditInterruption::Revoked).await;
}

#[tokio::test]
async fn write_cancellation_during_successful_audit_preserves_accepted_prefix() {
    write_audit_interrupted(WriteAuditInterruption::Cancelled).await;
}

#[tokio::test]
async fn write_deadline_during_successful_audit_preserves_accepted_prefix() {
    write_audit_interrupted(WriteAuditInterruption::Expired).await;
}

#[tokio::test]
async fn synthetic_audit_failure_reports_the_accepted_prefix_once_and_fences_reuse() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    let failure = stream
        .write(b"ONCE".to_vec(), None)
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Uncertain);
    assert_eq!(failure.accepted_prefix_bytes, 4);
    assert!(failure.may_have_applied);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"ONCE");
    assert!(stream.write(b"RETRY".to_vec(), None).is_err());
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn wrong_endpoint_is_denied_before_network_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let mut request = request(&fixture);
    request.endpoint.port = request.endpoint.port.saturating_add(1);
    let failure = fixture.provider.start(&session, request).err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn revoking_policy_prevents_application_write_on_existing_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    assert!(stream
        .write(b"NEVER".to_vec(), None)
        .unwrap()
        .await
        .is_err());
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    drop(stream);
    let mut bytes = Vec::new();
    peer.read_to_end(&mut bytes).await.unwrap();
    assert!(bytes.is_empty());
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_wakes_read_and_keeps_the_held_write_owner_until_drop() {
    use std::{
        future::{poll_fn, Future},
        pin::Pin,
        task::Poll,
    };

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream.write(b"PAID".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut received = [0; 4];
    peer.read_exact(&mut received).await.unwrap();
    assert_eq!(&received, b"PAID");
    let mut read = stream.read(1, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(Pin::new(&mut read).poll(cx)))
        .await
        .is_pending());
    // The accepted but unpolled write owns its input and the original socket;
    // it never reaches the peer and holds the ordinary write slot.
    let write = stream.write(b"NEVER".to_vec(), None).unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 3);
    assert_eq!(
        stream.shutdown(StreamShutdown::Both).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    assert_eq!(abort.await.unwrap().state, StreamState::Stopping);
    let failure = tokio::time::timeout(Duration::from_secs(1), read)
        .await
        .expect("local abort must wake the original read")
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(failure.may_have_applied);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    drop(write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .expect("the original socket must close after its last owner")
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_is_available_after_the_send_half_was_closed() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Send)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::WriteShut
    );
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Both)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::Closed
    );
    let mut byte = [0];
    assert_eq!(peer.read(&mut byte).await.unwrap(), 0);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream));
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn failed_send_shutdown_audit_fences_reuse_and_keeps_the_original_owner() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
    let mut sent = [0];
    peer.read_exact(&mut sent).await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    let failure = stream
        .shutdown(StreamShutdown::Send)
        .unwrap()
        .await
        .err()
        .unwrap();
    let state = stream.inspect().state;
    let readiness = stream.ready(StreamInterest::Readable, Some(1));
    let accepted_again = readiness.is_ok();
    drop(readiness);
    let pending = fixture.provider.usage().unwrap().pending_operations;
    let held_connection = fixture.pools.snapshot().unwrap().connections;
    let paid = control.budget.host_memory_bytes() > baseline;
    drop(held_read);
    let connections_after_drop = fixture.pools.snapshot().unwrap().connections;
    let mut eof = [0];
    let peer_eof = tokio::time::timeout(Duration::from_secs(1), peer.read(&mut eof))
        .await
        .unwrap();
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert_eq!(sent, *b"X");
    assert_eq!(failure.code, StreamErrorCode::Uncertain);
    assert!(failure.may_have_applied);
    assert_eq!(state, StreamState::Stopping);
    assert!(!accepted_again);
    assert_eq!((pending, held_connection), (1, 1));
    assert!(paid);
    assert_eq!(connections_after_drop, 0);
    assert_eq!(peer_eof.unwrap(), 0);
}

#[tokio::test]
async fn cancelled_send_shutdown_audit_fences_reuse_and_keeps_the_original_owner() {
    use crate::connection::TestWritePoint;
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut shutdown = stream.shutdown(StreamShutdown::Send).unwrap();
    tokio::select! {
        result = &mut shutdown => panic!("shutdown completed before the audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    let mut eof = [0];
    let peer_eof = tokio::time::timeout(Duration::from_secs(1), peer.read(&mut eof))
        .await
        .unwrap();
    drop(shutdown);
    drop(release);
    let state = stream.inspect().state;
    let readiness = stream.ready(StreamInterest::Readable, Some(1));
    let accepted_again = readiness.is_ok();
    drop(readiness);
    let pending = fixture.provider.usage().unwrap().pending_operations;
    let held_connection = fixture.pools.snapshot().unwrap().connections;
    let paid = control.budget.host_memory_bytes() > baseline;
    drop(held_read);
    let connections_after_drop = fixture.pools.snapshot().unwrap().connections;
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert_eq!(peer_eof.unwrap(), 0);
    assert_eq!(state, StreamState::Stopping);
    assert!(!accepted_again);
    assert_eq!((pending, held_connection), (1, 1));
    assert!(paid);
    assert_eq!(connections_after_drop, 0);
}

#[tokio::test]
async fn send_shutdown_rechecks_original_authority_after_audit() {
    use crate::connection::TestWritePoint;
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut shutdown = stream.shutdown(StreamShutdown::Send).unwrap();
    tokio::select! {
        result = &mut shutdown => panic!("shutdown completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    let mut eof = [0];
    let peer_eof = tokio::time::timeout(Duration::from_secs(1), peer.read(&mut eof))
        .await
        .unwrap();
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-send-shutdown-after-fin",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    release.send(()).unwrap();
    let result = shutdown.await;
    let state = stream.inspect().state;
    let pending = fixture.provider.usage().unwrap().pending_operations;
    let held_connection = fixture.pools.snapshot().unwrap().connections;
    let paid = control.budget.host_memory_bytes() > baseline;
    drop(held_read);
    let connections_after_drop = fixture.pools.snapshot().unwrap().connections;
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert_eq!(peer_eof.unwrap(), 0);
    let failure = result
        .err()
        .expect("revocation must reject the late completion");
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert!(!failure.may_have_applied); // This connection attempted no application write.
    assert_eq!(state, StreamState::Stopping);
    assert_eq!((pending, held_connection), (1, 1));
    assert!(paid);
    assert_eq!(connections_after_drop, 0);
}

#[tokio::test]
async fn send_shutdown_future_uses_the_original_budget_before_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let before = control.budget.host_memory_bytes();
    let future = stream.shutdown(StreamShutdown::Send).unwrap();
    let charged = control.budget.host_memory_bytes();
    drop(future);
    let after_drop = control.budget.host_memory_bytes();

    let remaining = control.budget.granted().memory_bytes - after_drop;
    let padding = control.budget.reserve_host_memory(remaining).unwrap();
    let failure = stream.shutdown(StreamShutdown::Send).err().unwrap();
    let pending = fixture.provider.usage().unwrap().pending_operations;
    let state = stream.inspect().state;
    drop(padding);
    assert_eq!(
        stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut bytes = [0; 4];
    peer.read_exact(&mut bytes).await.unwrap();
    stream.close().await.unwrap();
    drop(peer);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert!(charged > before);
    assert_eq!(after_drop, before);
    assert_eq!(failure.code, StreamErrorCode::Exhausted);
    assert_eq!(pending, 0);
    assert_eq!(state, StreamState::Open);
    assert_eq!(&bytes, b"LIVE");
}

#[tokio::test(flavor = "current_thread")]
async fn send_shutdown_abort_wake_panic_keeps_the_original_owner_fenced() {
    use std::{
        future::{poll_fn, Future},
        panic::{catch_unwind, AssertUnwindSafe},
        pin::Pin,
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc,
        },
        task::{Context, Poll, Wake, Waker},
    };

    struct PanicWake {
        armed: AtomicBool,
        woke: AtomicBool,
    }
    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            if self.armed.swap(false, Ordering::AcqRel) {
                self.woke.store(true, Ordering::Release);
                panic!("send shutdown abort wake failed");
            }
        }
    }

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let witness = Arc::new(PanicWake {
        armed: AtomicBool::new(false),
        woke: AtomicBool::new(false),
    });
    let wake = Waker::from(witness.clone());
    let mut read = Box::pin(stream.read(1, None).unwrap());
    assert!(matches!(
        read.as_mut().poll(&mut Context::from_waker(&wake)),
        Poll::Pending
    ));
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    witness.armed.store(true, Ordering::Release);
    let mut shutdown = stream.shutdown(StreamShutdown::Send).unwrap();
    let outcome =
        poll_fn(
            |cx| match catch_unwind(AssertUnwindSafe(|| Pin::new(&mut shutdown).poll(cx))) {
                Ok(Poll::Ready(result)) => Poll::Ready(Ok(result)),
                Ok(Poll::Pending) => Poll::Pending,
                Err(panic) => Poll::Ready(Err(panic)),
            },
        )
        .await;
    let first_panic = outcome
        .err()
        .and_then(|value| value.downcast_ref::<&str>().copied());
    let state = stream.inspect().state;
    let retained = fixture.provider.usage().unwrap();
    let paid = control.budget.host_memory_bytes() > baseline;
    drop((shutdown, read));
    let physical_after_drop = fixture.pools.snapshot().unwrap().connections;
    let mut byte = [0];
    let eof = tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap();
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert!(witness.woke.load(Ordering::Acquire));
    assert_eq!(first_panic, Some("send shutdown abort wake failed"));
    assert_eq!(state, StreamState::Stopping);
    assert_eq!((retained.pending_operations, retained.connections), (1, 1));
    assert!(paid);
    assert_eq!(physical_after_drop, 0);
    assert_eq!(eof.unwrap(), 0);
}

#[tokio::test]
async fn abort_both_unpolled_reserves_control_and_blocks_new_send_without_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(
        stream.write(b"X".to_vec(), None).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    assert_eq!(
        stream.shutdown(StreamShutdown::Send).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    drop(abort);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
    let mut byte = [0];
    peer.read_exact(&mut byte).await.unwrap();
    assert_eq!(byte, *b"X");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_cancels_an_accepted_send_shutdown_owner() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    // Acceptance owns the send slot and original transport before polling;
    // no kernel send-shutdown has been dispatched by this owner yet.
    let send = stream.shutdown(StreamShutdown::Send).unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(abort.await.unwrap().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let failure = tokio::time::timeout(Duration::from_secs(1), send)
        .await
        .expect("the accepted send owner must retire after local abort")
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(!failure.may_have_applied);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .expect("the original socket must close after the send owner")
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_read_after_consumption_fences_reuse_and_retains_pending_owner() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    tokio::select! {
        _ = &mut read => panic!("read completed before audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    assert_eq!(stream.inspect().delivered_read_bytes, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    drop(read);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert_eq!(
        stream.read(1, None).err().unwrap().code,
        StreamErrorCode::Cancelled
    );
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn failed_read_audit_fences_reuse_after_consuming_bytes() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let failure = stream.read(1, None).unwrap().await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Uncertain);
    assert_eq!(stream.inspect().delivered_read_bytes, 1);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert!(stream.read(1, None).is_err());
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[derive(Clone, Copy)]
enum ReadAuditInterruption {
    Revoked,
    Cancelled,
    ExpiredEof,
}

#[expect(
    clippy::too_many_lines,
    reason = "One original TCP connection and audit boundary through retirement."
)]
async fn read_audit_interrupted(interruption: ReadAuditInterruption) {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let prior_write = matches!(interruption, ReadAuditInterruption::Revoked);
    if prior_write {
        assert_eq!(stream.write(b"P".to_vec(), None).unwrap().await.unwrap(), 1);
        let mut sent = [0];
        peer.read_exact(&mut sent).await.unwrap();
        assert_eq!(&sent, b"P");
    }
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let eof = matches!(interruption, ReadAuditInterruption::ExpiredEof);
    if eof {
        peer.shutdown().await.unwrap();
    } else {
        peer.write_all(b"X").await.unwrap();
    }
    let mut read = stream.read(1, if eof { Some(1000) } else { None }).unwrap();
    tokio::select! {
        _ = &mut read => panic!("read completed before the audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    assert_eq!(stream.inspect().delivered_read_bytes, u64::from(!eof));
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let expected = match interruption {
        ReadAuditInterruption::Revoked => {
            fixture
                .policies
                .mutate(
                    MutationRequest {
                        tenant: "a",
                        actor: "operator",
                        id: "p",
                        kind: RecordKind::Policy,
                        operation_id: "revoke-read-during-audit",
                        expected_revision: 2,
                        document: None,
                    },
                    Instant::now() + Duration::from_secs(1),
                    |_| Ok(()),
                )
                .unwrap();
            StreamErrorCode::Denied
        }
        ReadAuditInterruption::Cancelled => {
            control
                .probe
                .0
                .store(true, std::sync::atomic::Ordering::Release);
            StreamErrorCode::Cancelled
        }
        ReadAuditInterruption::ExpiredEof => {
            tokio::time::sleep(Duration::from_millis(1100)).await;
            StreamErrorCode::Timeout
        }
    };
    release.send(()).unwrap();
    let failure = tokio::time::timeout(Duration::from_secs(1), read)
        .await
        .unwrap()
        .err()
        .expect("interrupted read returned bytes or EOF");
    assert_eq!(failure.code, expected);
    assert_eq!(failure.may_have_applied, prior_write);
    assert_eq!(failure.accepted_prefix_bytes, 0);
    assert_eq!(
        stream.inspect().accepted_write_bytes,
        u64::from(prior_write)
    );
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert!(stream.read(1, None).is_err());
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((owner, peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn read_revocation_during_successful_audit_refuses_handoff() {
    read_audit_interrupted(ReadAuditInterruption::Revoked).await;
}

#[tokio::test]
async fn read_cancellation_during_successful_audit_refuses_handoff() {
    read_audit_interrupted(ReadAuditInterruption::Cancelled).await;
}

#[tokio::test]
async fn read_deadline_during_successful_eof_audit_refuses_handoff() {
    read_audit_interrupted(ReadAuditInterruption::ExpiredEof).await;
}

#[tokio::test]
async fn dropped_read_before_consumption_keeps_connection_usable() {
    use std::{
        future::{poll_fn, Future},
        pin::Pin,
        task::Poll,
    };

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(Pin::new(&mut read).poll(cx)))
        .await
        .is_pending());
    drop(read);
    assert_eq!(stream.inspect().state, StreamState::Open);
    peer.write_all(b"X").await.unwrap();
    let mut output = stream.read(1, None).unwrap().await.unwrap().unwrap();
    let bytes = output.copy_bytes().unwrap();
    assert_eq!(bytes.as_ref(), b"X");
    drop(bytes);
    drop(output);
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_read_after_socket_consumption_fences_before_currentness_return() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::ReadConsumed);
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    tokio::select! {
        _ = &mut read => panic!("read completed before consumption gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    assert_eq!(stream.inspect().delivered_read_bytes, 0);
    drop(read);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert!(stream.read(1, None).is_err());
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_timeout_keeps_the_same_plain_tcp_owner() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();

    // A prior write remains a real possible external effect, even though the
    // subsequent readiness observation does not consume or submit bytes.
    assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
    let mut sent = [0];
    peer.read_exact(&mut sent).await.unwrap();
    assert_eq!(&sent, b"X");
    let failure = stream
        .ready(StreamInterest::Readable, Some(30))
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(failure.may_have_applied);
    assert_eq!(failure.accepted_prefix_bytes, 0);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(fixture.provider.usage().unwrap().connections, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert!(control.budget.host_memory_bytes() > baseline);

    peer.write_all(b"Y").await.unwrap();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    assert_eq!(chunk.copy_bytes().unwrap().as_ref(), b"Y");
    drop(chunk);
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn readiness_observation_zero_checks_real_socket_without_closing_it() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();

    let failure = stream
        .ready(StreamInterest::Readable, Some(0))
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(!failure.may_have_applied);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(fixture.provider.usage().unwrap().connections, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert!(control.budget.host_memory_bytes() > baseline);

    assert!(
        stream
            .ready(StreamInterest::Writable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .writable
    );
    peer.write_all(b"Z").await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(
        stream
            .ready(StreamInterest::Readable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    assert_eq!(chunk.copy_bytes().unwrap().as_ref(), b"Z");
    drop(chunk);
    peer.shutdown().await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(
        stream
            .ready(StreamInterest::Readable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(stream.read(1, None).unwrap().await.unwrap().is_none());
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_revocation_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-ready",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    release.send(()).unwrap();
    let failure = ready.await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_root_cancel_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    control.probe.0.store(true, Ordering::Release);
    release.send(()).unwrap();
    let failure = ready.await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn readiness_observation_zero_success_revoked_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"Z").await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(0)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("zero observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-zero-ready",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    release.send(()).unwrap();
    assert_eq!(ready.await.err().unwrap().code, StreamErrorCode::Denied);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_dropped_during_audit_fences_original_owner() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    drop(ready);
    drop(release);
    assert_ne!(stream.inspect().state, StreamState::Open);
    assert!(stream.ready(StreamInterest::Readable, None).is_err());
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}
