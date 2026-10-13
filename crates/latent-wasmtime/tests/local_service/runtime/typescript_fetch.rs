//! Actual protected-compiler packages through original signing and node owners.
use super::{package, packages, Fixture};
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::{
    activation_runtime::RuntimeLimits, ActivationId, ContractId, PlatformErrorCode, ServiceId,
    TenantId,
};
use latent_executor::ExecutionBackend;
use serde_json::{json, Value};
use std::time::Duration;

fn limits() -> RuntimeLimits {
    RuntimeLimits {
        tasks: 16,
        executors: 2,
        queued_work: 16,
        waits: 8,
        timers: 8,
        results: 8,
        native_owners: 64,
    }
}

async fn fixture(
    name: &str,
    root: &std::path::Path,
    http: Option<super::super::fixture::http::Configuration>,
) -> Fixture {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("typescript")
    );
    let caller = package::bundle(&package::input(name));
    let observed = package::observation(name);
    let callee = package::bundle(&package::input("typescript-service-callee"));
    let tenant = TenantId("examples".into());
    let signers = package::Signers::for_tenant(&observed.build_type, &tenant);
    let caller_upload = signers.upload_for_tenant(&caller, &observed, &tenant);
    let callee_upload = signers.upload_for_tenant(
        &callee,
        &package::observation("typescript-service-callee"),
        &tenant,
    );
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in [caller_upload, callee_upload] {
        catalog
            .admit_package(&tenant, upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    eprintln!("signed fetch fixture={name} actual signed caller/callee admitted");
    let release = packages::release(&caller);
    let identities = super::super::fixture::RuntimeIdentities {
        tenant,
        caller: ServiceId(
            serde_json::from_slice::<Value>(caller.blob("capsule.json").unwrap()).unwrap()
                ["metadata"]["name"]
                .as_str()
                .unwrap()
                .into(),
        ),
        callee: ServiceId("examples/typescript-runtime-callee".into()),
    };
    let fixture = if let Some(configuration) = http {
        Box::pin(Fixture::with_named_runtime_http(
            (catalog, caller, callee),
            limits(),
            identities,
            configuration,
        ))
        .await
    } else {
        Box::pin(Fixture::with_named_activation_runtime(
            2,
            (catalog, caller, callee),
            limits(),
            120_000,
            identities,
        ))
        .await
    };
    eprintln!("signed fetch fixture={name} node/runtime/provider bindings prepared");
    let publication = fixture
        .catalog
        .execution_eligibility_selected(&release, None)
        .unwrap()
        .unwrap()
        .publication()
        .clone();
    let mut key = fixture.backend.preparation_key(&release).unwrap();
    key.publication = Some(publication);
    let ready = tokio::time::timeout(
        Duration::from_mins(10),
        fixture
            .backend
            .prepare_ready_from_repository(fixture.catalog.clone(), key),
    )
    .await
    .expect("bounded actual signed fetch component preparation")
    .unwrap();
    eprintln!("signed fetch fixture={name} actual component readiness prepared");
    drop(fixture.backend.materialize_ready(ready).unwrap());
    fixture.idle().await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 0);
    fixture
}

async fn output(fixture: &Fixture, id: &str, contract: &str, mode: u32) -> Value {
    let mut request = fixture.request(id, mode);
    request.target.contract = ContractId(contract.into());
    let receipt = fixture.manager.start(request).unwrap().await;
    eprintln!(
        "signed URL selector={mode} native outcome={:?}",
        receipt.outcome
    );
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("{id}: {:?}", receipt.outcome)
    };
    assert!(success.consumption.cpu_fuel > 0);
    assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    let values: Vec<String> = serde_json::from_slice(&success.output).unwrap();
    assert_eq!(values.len(), 1);
    fixture.idle().await;
    serde_json::from_str(&values[0]).unwrap()
}

#[tokio::test]
#[ignore = "requires current source-bound protected-compiler URL output and exact build observations"]
async fn signed_native_url_reference_rejected_mutation_and_fresh_state_preserve_linked_owners() {
    let root = tempfile::tempdir().unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let fixture = Box::pin(fixture(
        "typescript-fetch-url",
        root.path(),
        Some(super::super::fixture::http::Configuration {
            port: listener.local_addr().unwrap().port(),
            permit: false,
        }),
    ))
    .await;
    let expected = json!({
        "linked":["https://example.invalid/caf%C3%A9?a=2&a=1&q=updated+value&snow=%E2%98%83#part",
            [["a","2"],["a","1"],["q","updated value"],["snow","\u{2603}"]],true],
        "mutated":["https://example.invalid/caf%C3%A9?x=8",[["x","8"]],true],
        "empty":"","standalone":["a=1&a=3&b=2",true,["1","3"]],"invalidSetters":true,"invalid":true
    });
    for id in ["url-reference", "url-reference-fresh"] {
        assert_eq!(
            output(&fixture, id, "examples:fetch-url/api@1.0.0", 0).await,
            expected
        );
    }
    assert_eq!(
        output(
            &fixture,
            "url-rejected-mutations",
            "examples:fetch-url/api@1.0.0",
            1
        )
        .await,
        json!({"refused":[true,true,true,true,true,true],"fresh":"fresh","identity":true})
    );
    assert_eq!(
        output(
            &fixture,
            "url-origin-Rust-owned-output",
            "examples:fetch-url/api@1.0.0",
            2
        )
        .await,
        json!([
            "https://example.invalid",
            "http://[::1]",
            "ftp://example.invalid",
            "null",
            "null",
            "https://example.invalid"
        ])
    );
    assert_eq!(
        output(
            &fixture,
            "url-linked-href-mutation",
            "examples:fetch-url/api@1.0.0",
            3
        )
        .await,
        json!([
            "https://another.invalid/next?b=2&c=3",
            true,
            [["b", "2"], ["c", "3"]]
        ])
    );
    assert_eq!(
        output(
            &fixture,
            "url-fresh-after-refusals",
            "examples:fetch-url/api@1.0.0",
            0
        )
        .await,
        expected
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    fixture.http.as_ref().unwrap().shutdown().await;
}

async fn read_request(socket: &mut tokio::net::TcpStream, mode: u32) {
    use tokio::io::AsyncReadExt;
    let mut header = Vec::new();
    let mut byte = [0];
    while !header.ends_with(b"\r\n\r\n") {
        assert!(header.len() < 8192);
        assert_eq!(socket.read(&mut byte).await.unwrap(), 1);
        header.push(byte[0]);
    }
    let header = String::from_utf8(header).unwrap().to_ascii_lowercase();
    assert!(header.starts_with("post /allowed http/1.1\r\n"));
    assert!(header.contains(&format!("\r\nx-fetch-control: {mode}\r\n")));
    let mut bytes = [0; 8];
    socket.read_exact(&mut bytes).await.unwrap();
    assert_eq!(&bytes, b"abcdefgh");
}

async fn closed_socket(socket: &mut tokio::net::TcpStream) {
    use tokio::io::AsyncReadExt;
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
            .await
            .expect("actual guest body cancellation/drop must close its TCP socket")
            .unwrap(),
        0
    );
}

fn fetch_request(
    fixture: &Fixture,
    id: &str,
    port: u16,
    mode: u32,
) -> latent_activation::ActivationRequest {
    let mut request = fixture.request(id, mode);
    request.target.contract = ContractId("examples:fetch-runtime/api@1.0.0".into());
    request.input = format!("[{port},{mode}]").into_bytes();
    request
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires current source-bound protected-compiler default fetch output and exact build observations"]
async fn signed_default_fetch_borrowed_read_abort_drop_trap_and_reuse_retire_real_native_owners() {
    use tokio::{io::AsyncWriteExt, net::TcpListener};
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let root = tempfile::tempdir().unwrap();
    let fixture = Box::pin(fixture(
        "typescript-fetch-runtime",
        root.path(),
        Some(super::super::fixture::http::Configuration { port, permit: true }),
    ))
    .await;
    eprintln!("signed fetch fixture ready; no activation Store exists");
    for (index, mode) in [0, 1, 2, 5, 6, 0].into_iter().enumerate() {
        let peer = async {
            let (mut socket, _) = listener.accept().await.unwrap();
            eprintln!("signed fetch mode={mode} actual TCP accepted");
            read_request(&mut socket, mode).await;
            eprintln!("signed fetch mode={mode} actual request/body parsed");
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\nx-fetch-response: native\r\n\r\n").await.unwrap();
            if mode == 0 {
                socket.write_all(b"abcdefgh").await.unwrap();
            } else if mode != 1 && mode != 6 {
                socket.write_all(b"abcd").await.unwrap();
            }
            closed_socket(&mut socket).await;
            eprintln!("signed fetch mode={mode} physical TCP EOF");
        };
        let invocation = fixture
            .manager
            .start(fetch_request(
                &fixture,
                &format!("fetch-{index}-{mode}"),
                port,
                mode,
            ))
            .unwrap();
        let invocation = async {
            let receipt = invocation.await;
            eprintln!(
                "signed fetch mode={mode} native activation outcome={:?}",
                receipt.outcome
            );
            receipt
        };
        let result = tokio::time::timeout(Duration::from_mins(2), async {
            tokio::join!(peer, invocation)
        })
        .await;
        if result.is_err() {
            eprintln!(
                "signed fetch mode={mode} timeout nativeIO={:?} broker={:?} stores={:?}",
                fixture.http.as_ref().unwrap().io.snapshot(),
                fixture.broker.snapshot(),
                fixture.backend.resource_snapshot()
            );
        }
        let ((), receipt) = result.expect("original finite fetch activation deadline");
        if mode == 5 || mode == 6 {
            assert!(
                matches!(receipt.outcome, ActivationOutcome::Failed {error, ..}if error.code==PlatformErrorCode::GuestTrap)
            );
        } else {
            assert_eq!(super::value(receipt), 42);
        }
        fixture.idle().await;
        fixture.http.as_ref().unwrap().idle();
    }
    fixture.http.as_ref().unwrap().shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires current source-bound protected-compiler default fetch output and exact build observations"]
async fn signed_default_fetch_host_cancellation_retires_original_borrow_before_fresh_work() {
    use tokio::{io::AsyncWriteExt, net::TcpListener};
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let root = tempfile::tempdir().unwrap();
    let fixture = Box::pin(fixture(
        "typescript-fetch-runtime",
        root.path(),
        Some(super::super::fixture::http::Configuration { port, permit: true }),
    ))
    .await;
    let id = ActivationId("fetch-host-cancel".into());
    let mut invocation = Box::pin(
        fixture
            .manager
            .start(fetch_request(&fixture, &id.0, port, 3))
            .unwrap(),
    );
    let (mut socket, _) = tokio::select! {
        accepted = listener.accept() => accepted.unwrap(),
        result = &mut invocation => panic!("fetch did not suspend: {:?}", result.outcome),
    };
    tokio::select! {
        () = read_request(&mut socket, 3) => {},
        result = &mut invocation => panic!("upload did not finish: {:?}", result.outcome),
    }
    socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\nx-fetch-response: native\r\n\r\n").await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if fixture.http.as_ref().unwrap().io.snapshot().calls > 0 {
                break;
            }
            tokio::select! {
                () = tokio::task::yield_now() => {},
                result = &mut invocation => panic!("borrowed read did not park: {:?}", result.outcome),
            }
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.backend.resource_snapshot().live_stores, 1);
    assert_eq!(
        fixture
            .manager
            .cancel_for(&TenantId("examples".into()), &id, "fetch-read-cancel")
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    let receipt = tokio::time::timeout(Duration::from_mins(2), invocation)
        .await
        .expect("original finite cancelled activation deadline");
    assert!(
        matches!(receipt.outcome, ActivationOutcome::Failed {error, ..}if error.code==PlatformErrorCode::Cancelled)
    );
    closed_socket(&mut socket).await;
    fixture.idle().await;
    let peer = async {
        let (mut socket, _) = listener.accept().await.unwrap();
        read_request(&mut socket, 0).await;
        socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\nx-fetch-response: native\r\n\r\nabcdefgh").await.unwrap();
        closed_socket(&mut socket).await;
    };
    let invocation = fixture
        .manager
        .start(fetch_request(
            &fixture,
            "fetch-fresh-after-host-cancel",
            port,
            0,
        ))
        .unwrap();
    let ((), receipt) = tokio::time::timeout(Duration::from_mins(2), async {
        tokio::join!(peer, invocation)
    })
    .await
    .expect("original finite fetch activation deadline");
    assert_eq!(super::value(receipt), 42);
    fixture.idle().await;
    fixture.http.as_ref().unwrap().shutdown().await;
}

#[tokio::test]
#[ignore = "requires current source-bound protected-compiler default fetch output and exact build observations"]
async fn signed_default_fetch_denied_native_provider_has_no_socket_contact() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let root = tempfile::tempdir().unwrap();
    let fixture = Box::pin(fixture(
        "typescript-fetch-runtime",
        root.path(),
        Some(super::super::fixture::http::Configuration {
            port,
            permit: false,
        }),
    ))
    .await;
    let receipt = fixture
        .manager
        .start(fetch_request(&fixture, "fetch-denied-no-contact", port, 4))
        .unwrap()
        .await;
    assert_eq!(super::value(receipt), 42);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    fixture.idle().await;
    fixture.http.as_ref().unwrap().shutdown().await;
}

#[tokio::test]
#[ignore = "requires exact current protected-compiler finite phase diagnostic output"]
async fn signed_fetch_phase_diagnostic_retains_actual_js_errors_and_native_consumption() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let fixture = Box::pin(fixture(
        "typescript-fetch-phase",
        root.path(),
        Some(super::super::fixture::http::Configuration {
            port: listener.local_addr().unwrap().port(),
            permit: false,
        }),
    ))
    .await;
    for mode in 0..4 {
        let mut request = fixture.request(&format!("fetch-phase-{mode}"), mode);
        request.target.contract = ContractId("examples:fetch-url/api@1.0.0".into());
        let receipt = fixture.manager.start(request).unwrap().await;
        eprintln!("source diagnostic phase={mode} native receipt={receipt:?}");
        fixture.idle().await;
    }
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    fixture.http.as_ref().unwrap().shutdown().await;
}
