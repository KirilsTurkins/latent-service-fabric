//! Executed owned-resource guests against a real bounded HTTP transport.
#![cfg(target_os = "linux")]
#[path = "streaming_http/component.rs"]
mod component;
#[path = "streaming_http/fixture.rs"]
mod fixture;
#[path = "streaming_http/packages.rs"]
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
async fn request(stream: &mut tokio::net::TcpStream) {
    let mut bytes = Vec::new();
    let mut b = [0];
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 8192);
        assert_eq!(stream.read(&mut b).await.unwrap(), 1);
        bytes.push(b[0]);
    }
    let mut body = [0; 8];
    stream.read_exact(&mut body).await.unwrap();
    assert_eq!(&body, b"abcdefgh");
}
#[tokio::test]
async fn guest_reads_before_full_body_and_store_drop_closes_the_stream() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().await.unwrap();
            request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
                .await
                .unwrap();
            let mut b = [0];
            assert_eq!(stream.read(&mut b).await.unwrap(), 0);
        }
    });
    let f = Fixture::new(port, "/allowed").await;
    for _ in 0..3 {
        let (request, control) = f.request("same-cell-stream", 0);
        let report = tokio::time::timeout(
            Duration::from_secs(2),
            f.backend.invoke_contained(request, &control),
        )
        .await
        .unwrap();
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("streaming guest must return before EOF")
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
            serde_json::json!([4200])
        );
        let final_budget = control
            .budget
            .finalize_at(Some(&consumption), Instant::now());
        assert!(final_budget.violation().is_none());
        assert_eq!(final_budget.consumption().outbound_requests, 1);
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
        assert_eq!(f.io.snapshot(), IoSnapshot::default());
    }
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
#[tokio::test]
async fn resource_guest_drains_chunks_and_trailers_then_reclaims_all_owners() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        request(&mut stream).await;
        stream.write_all(b"HTTP/1.1 201 Created\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n8\r\nabcdefgh\r\n0\r\nx-trailer: complete\r\n\r\n").await.unwrap();
    });
    let f = Fixture::new(port, "/allowed").await;
    let (request, control) = f.request("drain", 2);
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
        panic!("streaming drain")
    };
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
        serde_json::json!([8201])
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    assert_eq!(f.io.snapshot(), IoSnapshot::default());
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn traps_wrong_kind_stale_handles_and_abort_close_real_owners() {
    for which in [1, 3, 5, 6, 7] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
                .await
                .unwrap();
            let mut b = [0];
            assert_eq!(stream.read(&mut b).await.unwrap(), 0);
        });
        let f = Fixture::new(port, "/allowed").await;
        let (request, control) = f.request("resource-errors", which);
        let report = f.backend.invoke_contained(request, &control).await;
        match report.outcome.unwrap() {
            GuestOutcome::Trapped { .. } => assert_ne!(which, 3),
            GuestOutcome::Returned { output, .. } => {
                assert_eq!(which, 3);
                assert_eq!(
                    serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
                    serde_json::json!([4200])
                );
            }
            _ => panic!("unexpected resource outcome"),
        }
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
        assert_eq!(f.io.snapshot(), IoSnapshot::default());
        server.await.unwrap();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}
#[tokio::test]
async fn abort_or_trap_before_upload_finishes_reclaims_the_connection() {
    for which in [4, 9] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut b = [0];
            assert_eq!(stream.read(&mut b).await.unwrap(), 0);
        });
        let f = Fixture::new(port, "/allowed").await;
        let (request, control) = f.request("abort-upload", which);
        let report = f.backend.invoke_contained(request, &control).await;
        if which == 4 {
            assert!(matches!(
                report.outcome.unwrap(),
                GuestOutcome::Returned { .. }
            ));
        } else {
            assert!(matches!(
                report.outcome.unwrap(),
                GuestOutcome::Trapped { .. }
            ));
        }
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
        assert_eq!(f.io.snapshot(), IoSnapshot::default());
        server.await.unwrap();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}
#[tokio::test]
async fn cancellation_of_a_suspended_guest_read_closes_socket_and_all_resources() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (sent, received) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nabcd")
            .await
            .unwrap();
        sent.send(()).unwrap();
        let mut b = [0];
        // Cancelling with unread response bytes may close TCP with FIN or RST.
        // Both prove physical closure; data, another error, or a stalled peer do not.
        match tokio::time::timeout(Duration::from_secs(2), stream.read(&mut b))
            .await
            .expect("cancelled guest must close its socket")
        {
            Ok(0) => {}
            Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
            other => panic!("expected socket closure after cancellation, got {other:?}"),
        }
    });
    let f = Fixture::new(port, "/allowed").await;
    let (request, control) = f.request("cancel-read", 2);
    let invocation = f.backend.invoke_contained(request, &control);
    tokio::pin!(invocation);
    tokio::select! {_ = &mut invocation=>panic!("peer has not completed the body"),_=received=>{}}
    control.probe.0.store(true, Ordering::Release);
    let report = tokio::time::timeout(Duration::from_secs(2), &mut invocation)
        .await
        .unwrap();
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    assert_eq!(f.io.snapshot(), IoSnapshot::default());
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
#[tokio::test]
async fn a_revoked_grant_blocks_a_new_stream_before_any_network_work() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let f = Fixture::new(port, "/allowed").await;
    f.policies
        .mutate(
            latent_policy::capability::MutationRequest {
                tenant: "tests",
                actor: "operator",
                id: "p",
                kind: latent_policy::capability::RecordKind::Policy,
                operation_id: "revoke-stream",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    let (request, control) = f.request("revoked-stream", 0);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    assert_eq!(f.io.snapshot(), IoSnapshot::default());
    assert!(
        tokio::time::timeout(Duration::from_millis(30), listener.accept())
            .await
            .is_err()
    );
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[test]
fn streaming_package_preserves_exact_owned_resources_and_value_only_exports() {
    let package = packages::capsule("http://localhost:8080/allowed");
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
#[tokio::test]
async fn no_streaming_provider_means_no_prepared_stream_import() {
    let factory = WasmtimeComponentEngineFactory::new(support::config()).unwrap();
    let backend = factory.create_backend_instance();
    let mut artifact = support::artifact_bytes(
        component::bytes("http://localhost:12345/allowed"),
        &[component::CONTRACT],
    );
    artifact
        .manifest
        .imports
        .push(latent_manifest::ContractImport {
            contract: ContractId(component::CAP.into()),
            optional: false,
        });
    let error = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap_err();
    assert_eq!(
        error.code,
        latent_core::PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
}

#[tokio::test]
async fn dormant_streaming_deployments_create_no_provider_or_activation_owners() {
    let f = Fixture::new(12345, "/allowed").await;
    f.dormant_deployments().await;
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
