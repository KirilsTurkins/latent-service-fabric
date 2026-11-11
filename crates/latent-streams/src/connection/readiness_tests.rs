//! Real TCP readiness with deterministic audit-boundary injection. The gate
//! and audit failure are test doubles, not durable-journal or guest evidence.
use super::{Connection, TestWritePoint};
use crate::{
    tests::{config, fixture::Fixture},
    StreamErrorCode,
};
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamInterest, StreamState,
};
use latent_policy::capability::{MutationRequest, RecordKind};
use std::{sync::Arc, time::Duration};
use tokio::{io::AsyncReadExt, net::TcpListener};

async fn fixture() -> (Fixture, TcpListener) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    (Fixture::new(configuration), listener)
}

fn request(fixture: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: fixture.provider.inner.config.destinations[0]
            .endpoint
            .clone(),
        timeout_millis: None,
    }
}

fn owner(fixture: &Fixture) -> Arc<Connection> {
    fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap()
}

async fn closed(peer: &mut tokio::net::TcpStream) {
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .expect("bounded physical socket retirement")
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        other => panic!("expected actual TCP retirement: {other:?}"),
    }
}

#[derive(Clone, Copy, Debug)]
enum Completion {
    Current,
    Revoked,
    Abandoned,
    AuditFailed,
    Expired,
}

fn revoke(fixture: &Fixture) {
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "ready-completion-revoke",
                expected_revision: 2,
                document: None,
            },
            std::time::Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
}

#[expect(
    clippy::too_many_lines,
    reason = "One original TCP connection and audit boundary through physical retirement."
)]
async fn completion_case(completion: Completion, timeout: Option<u32>) {
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
    let owner = owner(&fixture);
    let last_progress = owner.state.lock().unwrap().last_progress;
    let expiry = owner.deadline.min(last_progress + owner.idle);
    let held_read = stream.read(1, None).unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    let mut ready = stream.ready(StreamInterest::Writable, timeout).unwrap();
    tokio::select! {
        result = &mut ready => panic!("readiness escaped the audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => {
            reached.expect("bounded audit gate").unwrap();
        }
    }
    // Observing writability neither transfers bytes nor frees the paid waiter.
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(stream.inspect().delivered_read_bytes, 0);
    assert!(stream.ready(StreamInterest::Writable, None).is_err());
    match completion {
        Completion::Current | Completion::Abandoned => {}
        Completion::Revoked => revoke(&fixture),
        Completion::AuditFailed => owner.test_fail_audit_once(),
        Completion::Expired => tokio::time::sleep_until(expiry.into()).await,
    }
    if matches!(completion, Completion::Abandoned) {
        drop(ready);
        drop(release);
    } else {
        release.send(()).unwrap();
        let result = tokio::time::timeout(Duration::from_secs(1), ready)
            .await
            .expect("bounded readiness completion");
        match completion {
            Completion::Current => {
                let result = result.unwrap();
                assert!(result.writable);
                assert!(!result.readable);
            }
            Completion::Revoked => assert!(result.is_err(), "revocation became readiness"),
            Completion::AuditFailed => {
                let failure = result.unwrap_err();
                assert_eq!(failure.code, StreamErrorCode::Uncertain);
                assert_eq!(failure.accepted_prefix_bytes, 0);
                assert!(!failure.may_have_applied);
            }
            Completion::Expired => {
                assert_eq!(result.unwrap_err().code, StreamErrorCode::Timeout);
            }
            Completion::Abandoned => unreachable!(),
        }
    }
    assert_eq!(owner.state.lock().unwrap().last_progress, last_progress);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    if matches!(completion, Completion::Current) {
        assert_eq!(stream.inspect().state, StreamState::Open);
        // A later observation reuses the same connection, not a new dial.
        assert!(stream
            .ready(StreamInterest::Writable, None)
            .unwrap()
            .await
            .unwrap()
            .writable);
        drop(held_read);
        stream.close().await.unwrap();
    } else {
        assert_eq!(stream.inspect().state, StreamState::Stopping);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
        assert!(control.budget.host_memory_bytes() > baseline);
        let mut copied = false;
        assert!(stream
            .write_from(1, None, &mut || {
                copied = true;
                Ok(vec![0])
            })
            .is_err());
        assert!(!copied, "terminal readiness allowed another input copy");
        drop(held_read);
        assert_eq!(stream.inspect().state, StreamState::Failed);
        drop(stream);
    }
    closed(&mut peer).await;
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .outbound_requests,
        1
    );
    drop((owner, peer, session, listener));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

async fn bounded(completion: Completion) {
    tokio::time::timeout(Duration::from_secs(12), async {
        // None follows the original wait path; a finite timeout selects the
        // plain-TCP observation branch. Linux also supports a physical snapshot.
        completion_case(completion, None).await;
        completion_case(completion, Some(1000)).await;
        #[cfg(target_os = "linux")]
        completion_case(completion, Some(0)).await;
    })
    .await
    .expect("bounded readiness audit-boundary control");
}

#[tokio::test]
async fn successful_readiness_releases_only_its_waiter_and_never_renews_idle() {
    bounded(Completion::Current).await;
}

#[tokio::test]
async fn revocation_during_successful_readiness_audit_prevents_handoff() {
    bounded(Completion::Revoked).await;
}

#[tokio::test]
async fn dropped_successful_readiness_audit_retains_original_socket_until_read_drop() {
    bounded(Completion::Abandoned).await;
}

#[tokio::test]
async fn failed_successful_readiness_audit_fences_connection_without_claiming_io() {
    bounded(Completion::AuditFailed).await;
}

#[tokio::test]
async fn original_expiry_during_readiness_audit_wins_over_ready_result() {
    bounded(Completion::Expired).await;
}
