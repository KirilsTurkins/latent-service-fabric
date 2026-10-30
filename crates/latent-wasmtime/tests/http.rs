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

// Isolated API fixture: these limits are NOT an ActivationBudget or RSS claim.
fn utf8_view_store(engine: &wasmtime::Engine) -> wasmtime::Store<wasmtime::StoreLimits> {
    let limits = wasmtime::StoreLimitsBuilder::new()
        .memory_size(65536)
        .instances(1)
        .memories(1)
        .build();
    let mut store = wasmtime::Store::new(engine, limits);
    store.limiter(|limits| limits);
    store.set_fuel(100_000).unwrap();
    store.set_hostcall_fuel(65536);
    store
}
fn utf8_view_component() -> (wasmtime::Engine, wasmtime::component::Component) {
    let mut config = wasmtime::Config::new();
    config.wasm_component_model(true).consume_fuel(true);
    let engine = wasmtime::Engine::new(&config).unwrap();
    let component =
        wasmtime::component::Component::new(&engine, component::utf8_view_bytes()).unwrap();
    (engine, component)
}
#[test]
fn canonical_utf8_view_uses_same_store_for_all_encodings_and_exact_destinations() {
    use wasmtime::component::{Linker, WasmStr};
    let (engine, component) = utf8_view_component();
    let mut store = utf8_view_store(&engine);
    let instance = Linker::new(&engine)
        .instantiate(&mut store, &component)
        .unwrap();
    for (name, expected) in [
        ("utf8", "a\u{e9}\u{1d11e}"),
        ("utf16", "\u{e9}\u{1d11e}"),
        ("latin1", "\u{e9}\u{ff}"),
        ("tagged-utf16", "\u{e9}\u{1d11e}"),
    ] {
        let function = instance
            .get_typed_func::<(), (WasmStr,)>(&mut store, name)
            .unwrap();
        let (value,) = function.call(&mut store, ()).unwrap();
        let view = value.utf8_view(&store).unwrap();
        assert_eq!(view.len(), expected.len());
        let mut output = [0x55u8; 16];
        assert!(view.write_into(&mut output[..view.len() - 1]).is_err());
        assert_eq!(output, [0x55; 16]);
        assert!(view.write_into(&mut output[..view.len() + 1]).is_err());
        assert_eq!(output, [0x55; 16]);
        view.write_into(&mut output[..view.len()]).unwrap();
        assert_eq!(&output[..view.len()], expected.as_bytes());
    }
    let empty = instance
        .get_typed_func::<(), (WasmStr,)>(&mut store, "empty")
        .unwrap();
    let (value,) = empty.call(&mut store, ()).unwrap();
    {
        let view = value.utf8_view(&store).unwrap();
        assert!(view.is_empty());
        view.write_into(&mut []).unwrap();
    }
    let malformed = instance
        .get_typed_func::<(), (WasmStr,)>(&mut store, "malformed")
        .unwrap();
    let (value,) = malformed.call(&mut store, ()).unwrap();
    assert!(value.utf8_view(&store).is_err());
    let fresh = instance
        .get_typed_func::<(), (WasmStr,)>(&mut store, "utf8")
        .unwrap();
    let (value,) = fresh.call(&mut store, ()).unwrap();
    let mut output = [0; 7];
    value
        .utf8_view(&store)
        .unwrap()
        .write_into(&mut output)
        .unwrap();
    assert_eq!(&output, b"a\xc3\xa9\xf0\x9d\x84\x9e");
    // A view-only decode error occurs after a successful canonical call.
    // A result-Lift error instead skips pinned call_raw/post_return exit;
    // never require recovery or a second call in that terminal instance.
    for name in ["unaligned", "out-of-bounds"] {
        let mut terminal_store = utf8_view_store(&engine);
        let terminal_instance = Linker::new(&engine)
            .instantiate(&mut terminal_store, &component)
            .unwrap();
        let function = terminal_instance
            .get_typed_func::<(), (WasmStr,)>(&mut terminal_store, name)
            .unwrap();
        let error = function
            .call(&mut terminal_store, ())
            .err()
            .expect("terminal canonical lift must fail");
        let chain = format!("{error:#}");
        let expected = if name == "unaligned" {
            "string pointer not aligned to 2"
        } else {
            "string pointer/length out of bounds of memory"
        };
        assert!(chain.contains(expected), "expected {expected}: {chain}");
        assert!(!matches!(
            error.downcast_ref::<wasmtime::Trap>(),
            Some(&wasmtime::Trap::CannotEnterComponent)
        ));
    }
    println!("http-utf8-view forms=4 empty=1 malformed=1 unaligned=1 oob=1 exact=4 short=4 long=4 fresh=1");
}
#[test]
fn canonical_utf8_view_rejects_foreign_store_without_poisoning_original() {
    use wasmtime::component::{Linker, WasmStr};
    let (engine, component) = utf8_view_component();
    let mut store = utf8_view_store(&engine);
    let instance = Linker::new(&engine)
        .instantiate(&mut store, &component)
        .unwrap();
    let function = instance
        .get_typed_func::<(), (WasmStr,)>(&mut store, "utf8")
        .unwrap();
    let (value,) = function.call(&mut store, ()).unwrap();
    let foreign = utf8_view_store(&engine);
    let rejected = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        value.utf8_view(&foreign).map(|view| view.len())
    }));
    assert!(rejected.is_err());
    let mut output = [0; 7];
    value
        .utf8_view(&store)
        .unwrap()
        .write_into(&mut output)
        .unwrap();
    assert_eq!(&output, b"a\xc3\xa9\xf0\x9d\x84\x9e");
    let (fresh,) = function.call(&mut store, ()).unwrap();
    assert_eq!(fresh.utf8_view(&store).unwrap().len(), 7);
    println!("http-utf8-view wrong-store=refused original-store=fresh");
}
