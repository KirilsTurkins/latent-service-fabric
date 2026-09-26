//! Executed HTTP guest, real provider, actual TCP peer and original Store ledger.
#![cfg(target_os = "linux")]
#[path = "http/component.rs"]
mod component;
#[path = "http/fixture.rs"]
mod fixture;
#[path = "http/packages.rs"]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_capabilities::broker::io::IoSnapshot;
use latent_policy::capability::{MutationRequest, RecordKind};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
#[tokio::test]
async fn real_guest_executes_every_method_and_reclaims_the_same_warm_cell() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for method in ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] {
            let (mut stream, _) = listener.accept().await.unwrap();
            let wire = read_request(&mut stream).await;
            assert!(wire.starts_with(format!("{method} /allowed HTTP/1.1").as_bytes()));
            assert!(wire.ends_with(b"payload"));
            stream.write_all(b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n").await.unwrap();
            if method != "HEAD" {
                stream.write_all(b"ok").await.unwrap();
            }
        }
    });
    let f = Fixture::new(port, "/allowed").await;
    for method in 0..7 {
        let (request, control) = f.request("warm-http", method);
        let report = f.backend.invoke_contained(request, &control).await;
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("guest must return HTTP status and body length");
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
            serde_json::json!([if method == 1 { 201 } else { 2201 }])
        );
        let finalized = control
            .budget
            .finalize_at(Some(&consumption), Instant::now());
        assert!(finalized.violation().is_none());
        assert_eq!(finalized.consumption().outbound_requests, 1);
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
async fn guest_denial_and_trap_preserve_transport_and_store_cleanup() {
    for trap in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            if trap {
                let (mut stream, _) = listener.accept().await.unwrap();
                read_request(&mut stream).await;
                stream
                    .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    .await
                    .unwrap();
            } else {
                assert!(
                    tokio::time::timeout(Duration::from_millis(300), listener.accept())
                        .await
                        .is_err()
                );
            }
        });
        let f = Fixture::new(port, if trap { "/allowed" } else { "/forbidden" }).await;
        let (request, control) = f.request("denied-or-trapped", if trap { 8 } else { 0 });
        let report = f.backend.invoke_contained(request, &control).await;
        if trap {
            assert!(matches!(
                report.outcome.unwrap(),
                GuestOutcome::Trapped { .. }
            ));
        } else {
            let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
                panic!("typed denial")
            };
            assert_eq!(
                serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
                serde_json::json!([1002])
            );
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
async fn read_request(stream: &mut tokio::net::TcpStream) -> Vec<u8> {
    let mut bytes = Vec::new();
    let mut byte = [0];
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 8192);
        assert_eq!(stream.read(&mut byte).await.unwrap(), 1);
        bytes.push(byte[0]);
    }
    let text = std::str::from_utf8(&bytes).unwrap();
    let length = text
        .lines()
        .find_map(|l| l.strip_prefix("content-length: "))
        .unwrap_or("0")
        .parse::<usize>()
        .unwrap();
    assert!(length < 8192);
    let start = bytes.len();
    bytes.resize(start + length, 0);
    stream.read_exact(&mut bytes[start..]).await.unwrap();
    bytes
}

#[tokio::test]
async fn guest_cancellation_closes_inflight_io_and_reclaims_store() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (started, received) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        started.send(()).unwrap();
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), stream.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    });
    let f = Fixture::new(port, "/allowed").await;
    let (request, control) = f.request("cancelled-http", 0);
    let invocation = f.backend.invoke_contained(request, &control);
    tokio::pin!(invocation);
    tokio::select! {_=&mut invocation=>panic!("peer is waiting"),_=received=>{}}
    control.probe.0.store(true, Ordering::Release);
    let report = invocation.await;
    assert!(matches!(
        report.outcome.unwrap(),
        GuestOutcome::Interrupted {
            kind: latent_executor::GuestInterruptionKind::Cancelled,
            ..
        }
    ));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
    server.await.unwrap();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
#[tokio::test]
async fn revoked_policy_and_missing_provider_cannot_use_prepared_http_imports() {
    let f = Fixture::new(12345, "/allowed").await;
    f.policies
        .mutate(
            MutationRequest {
                tenant: "tests",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    let (request, control) = f.request("revoked", 0);
    assert!(f
        .backend
        .invoke_contained(request, &control)
        .await
        .outcome
        .is_err());
    f.idle();
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
    let failure = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap_err();
    assert_eq!(
        failure.code,
        latent_core::PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[test]
fn maintained_http_capsule_has_exact_wit_package_and_async_metadata() {
    let package = packages::capsule("http://localhost:8080/allowed");
    latent_packaging::compile_host_binding(
        &package,
        component::CAP,
        latent_packaging::PackageComparisonLimits::default(),
    )
    .unwrap();
    let artifact = packages::artifact(&package);
    assert_eq!(artifact.contracts[0].interfaces[0].functions[0].name, "run");
    assert!(artifact.contracts[0].interfaces[0].functions[0].asynchronous);
}
