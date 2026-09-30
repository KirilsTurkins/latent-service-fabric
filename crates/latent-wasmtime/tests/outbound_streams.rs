//! Executed canonical resource guests and real TCP peers. These tests qualify
//! the shared transport ABI; they do not claim a standard-language library port.
#![cfg(target_os = "linux")]
#[path = "outbound_streams/component.rs"]
mod component;
#[path = "outbound_streams/fixture.rs"]
mod fixture;
#[path = "outbound_streams/packages.rs"]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_capabilities::broker::io::IoSnapshot;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn closure(socket: &mut tokio::net::TcpStream) {
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
        .await
        .expect("physical socket must close")
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        other => panic!("expected actual TCP retirement, got {other:?}"),
    }
}
async fn clean(fixture: &Fixture, control: &Control) {
    fixture.idle();
    assert_eq!(fixture.io.snapshot(), IoSnapshot::default());
    assert_eq!(control.budget.host_memory_bytes(), 0);
    let snapshot = fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(snapshot.is_clean(), "{snapshot:?}");
}

#[tokio::test]
async fn canonical_guest_reads_partial_chunks_eof_and_reuses_no_authenticated_socket() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let peer = tokio::spawn(async move {
        for _ in 0..3 {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut input = Vec::new();
            socket.read_to_end(&mut input).await.unwrap();
            assert_eq!(input, b"PING");
            socket.write_all(b"PONG").await.unwrap();
            socket.shutdown().await.unwrap();
        }
    });
    let fixture = Fixture::new(port).await;
    for _ in 0..3 {
        let (request, control) = fixture.request("same-cell-stream", 0);
        let report = fixture.backend.invoke_contained(request, &control).await;
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("real stream guest must return")
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
            serde_json::json!([4])
        );
        let final_budget = control
            .budget
            .finalize_at(Some(&consumption), Instant::now());
        assert!(final_budget.violation().is_none(), "{final_budget:?}");
        assert_eq!(final_budget.consumption().outbound_requests, 1);
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        fixture.idle();
        assert_eq!(fixture.io.snapshot(), IoSnapshot::default());
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    }
    peer.await.unwrap();
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn traps_wrong_kind_stale_resources_and_oversized_write_retire_actual_owners() {
    for scenario in [1, 4, 5, 6] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let peer = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            if scenario == 1 || scenario == 4 {
                closure(&mut socket).await;
            } else {
                let mut input = Vec::new();
                socket.read_to_end(&mut input).await.unwrap();
                assert_eq!(input, b"PING");
                socket.write_all(b"PONG").await.unwrap();
                socket.shutdown().await.unwrap();
            }
        });
        let fixture = Fixture::new(port).await;
        let (request, control) = fixture.request("resource-errors", scenario);
        let report = fixture.backend.invoke_contained(request, &control).await;
        if scenario == 4 {
            let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
                panic!("oversized byte list must return invalid-input")
            };
            assert_eq!(
                serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
                serde_json::json!([0])
            );
        } else {
            assert!(
                matches!(report.outcome, Ok(GuestOutcome::Trapped { .. })),
                "{report:?}"
            );
        }
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        peer.await.unwrap();
        clean(&fixture, &control).await;
    }
}

#[tokio::test]
async fn cancelling_a_suspended_canonical_read_closes_socket_before_reuse() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (sent, received) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = [0; 4];
        socket.read_exact(&mut input).await.unwrap();
        assert_eq!(&input, b"PING");
        socket.write_all(b"P").await.unwrap();
        sent.send(()).unwrap();
        closure(&mut socket).await;
    });
    let fixture = Fixture::new(port).await;
    let (request, control) = fixture.request("cancel-read", 2);
    let invocation = fixture.backend.invoke_contained(request, &control);
    tokio::pin!(invocation);
    tokio::select! { _ = &mut invocation => panic!("read must wait for further peer bytes"), _ = received => {} }
    control.probe.0.store(true, Ordering::Release);
    let report = tokio::time::timeout(Duration::from_secs(2), &mut invocation)
        .await
        .unwrap();
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    peer.await.unwrap();
    clean(&fixture, &control).await;
}

#[tokio::test]
async fn dormant_stream_deployments_create_no_activation_or_socket_owners() {
    let fixture = Fixture::new(12345).await;
    fixture.dormant_deployments().await;
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn revoking_a_policy_during_canonical_read_closes_the_real_socket() {
    use latent_policy::capability::{MutationRequest, RecordKind};
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (sent, received) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = [0; 4];
        socket.read_exact(&mut input).await.unwrap();
        assert_eq!(&input, b"PING");
        socket.write_all(b"P").await.unwrap();
        sent.send(()).unwrap();
        closure(&mut socket).await;
    });
    let fixture = Fixture::new(port).await;
    let (request, control) = fixture.request("revoked-read", 2);
    let invocation = fixture.backend.invoke_contained(request, &control);
    tokio::pin!(invocation);
    tokio::select! { _ = &mut invocation => panic!("read must wait"), _ = received => {} }
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "tests",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "stream-read-revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    let report = tokio::time::timeout(Duration::from_secs(2), &mut invocation)
        .await
        .unwrap();
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    peer.await.unwrap();
    clean(&fixture, &control).await;
}

#[test]
fn stream_package_preserves_exact_owned_resources_and_async_signatures() {
    let package = packages::capsule(12345);
    latent_packaging::compile_host_binding(
        &package,
        component::CAP,
        latent_packaging::PackageComparisonLimits::default(),
    )
    .unwrap();
    let artifact = packages::artifact(&package);
    assert!(artifact.contracts[0].interfaces[0].functions[0].asynchronous);
    assert_eq!(artifact.manifest.imports[0].contract.0, component::CAP);
}
