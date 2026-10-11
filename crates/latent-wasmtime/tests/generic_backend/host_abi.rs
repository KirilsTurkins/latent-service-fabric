use super::support::{artifact_bytes, budget, config, idle, request, run, Cancellation};
use latent_core::{ContractId, HostInterfaceBinding, PlatformErrorCode, PHASE3_HOST_ABI_V2};
use latent_executor::ExecutionBackend;
use latent_manifest::ContractImport;
use latent_wasmtime::WasmtimeComponentEngineFactory;

#[path = "../../../latent-packaging/tests/fixtures/component.rs"]
mod fixture;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host_fixture;

fn artifact(spec: &latent_core::HostInterfaceSpec) -> latent_artifacts::CapsuleArtifact {
    let bytes = fixture::with_host(
        fixture::Options::default(),
        spec.interface,
        &host_fixture::interface(spec.wit, spec.interface, None),
    );
    let mut artifact = artifact_bytes(bytes, &[fixture::CONTRACT]);
    artifact.manifest.imports = vec![ContractImport {
        contract: ContractId(spec.interface.into()),
        optional: false,
    }];
    artifact
}

#[tokio::test(flavor = "current_thread")]
async fn outbound_proposal_and_wasi_sockets_are_not_ambient_authority() {
    const STREAMS: &str = "latent:network/streams@0.1.0";
    const WIT: &str = include_str!("../../../../wit/platform/network/package.wit");
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let streams = host_fixture::interface(WIT, STREAMS, None);
    // An uninstalled stream interface remains denied. An unknown standard
    // socket namespace stays unknown even with an empty imported instance.
    let wasi = wasm_encoder::InstanceType::new();
    for (name, interface) in [(STREAMS, &streams), ("wasi:sockets/tcp@0.2.0", &wasi)] {
        let bytes = fixture::with_host(fixture::Options::default(), name, interface);
        let mut artifact = artifact_bytes(bytes, &[fixture::CONTRACT]);
        artifact.manifest.imports = vec![ContractImport {
            contract: ContractId(name.into()),
            optional: false,
        }];
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let error = backend.prepare(&artifact, &key).await.unwrap_err();
        assert_eq!(
            error.code,
            PlatformErrorCode::IncompatibleContract,
            "{name}"
        );
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        assert_eq!(backend.cache_snapshot().entries, 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn exact_wasi_tcp_poll_and_stream_resource_types_do_not_install_ambient_ports() {
    let directory = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../research/standard-outbound/wasi-sockets-v0.2.0/wit");
    let mut resolve = wit_parser::Resolve::default();
    resolve.push_dir(&directory).unwrap();
    // These are the original upstream methods/resources, not an empty namespace
    // or a renamed LSF interface. No adaptation or socket execution is claimed.
    let (_, tcp) = resolve
        .interfaces
        .iter()
        .find(|(id, _)| resolve.id_of(*id).as_deref() == Some("wasi:sockets/tcp@0.2.0"))
        .unwrap();
    for name in [
        "[method]tcp-socket.start-connect",
        "[method]tcp-socket.finish-connect",
        "[method]tcp-socket.subscribe",
        "[method]tcp-socket.shutdown",
    ] {
        assert!(tcp.functions.contains_key(name), "{name}");
    }
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    for name in [
        "wasi:sockets/tcp@0.2.0",
        "wasi:sockets/network@0.2.0",
        "wasi:sockets/ip-name-lookup@0.2.0",
        "wasi:io/streams@0.2.0",
        "wasi:io/poll@0.2.0",
    ] {
        let interface = host_fixture::interface_from_directory(&directory, name, None);
        let bytes = fixture::with_host(fixture::Options::default(), name, &interface);
        let mut artifact = artifact_bytes(bytes, &[fixture::CONTRACT]);
        artifact.manifest.imports = vec![ContractImport {
            contract: ContractId(name.into()),
            optional: false,
        }];
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let error = backend.prepare(&artifact, &key).await.unwrap_err();
        assert_eq!(
            error.code,
            PlatformErrorCode::IncompatibleContract,
            "{name}"
        );
        assert_eq!(backend.resource_snapshot().stores_created, 0, "{name}");
        assert_eq!(backend.cache_snapshot().entries, 0, "{name}");
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn recognized_provider_imports_fail_preparation_without_installed_owners() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    for spec in PHASE3_HOST_ABI_V2
        .interfaces()
        .iter()
        .filter(|s| s.binding == HostInterfaceBinding::Provider)
    {
        let artifact = artifact(spec);
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let error = backend.prepare(&artifact, &key).await.unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert_eq!(
            error.message, "required host capability provider is unavailable",
            "{}",
            spec.interface
        );
        assert_eq!(backend.cache_snapshot().entries, 0);
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn forged_or_stale_host_profile_descriptors_cannot_reuse_preparation() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = artifact(PHASE3_HOST_ABI_V2.interface(fixture::CLOCK).unwrap());
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let prepared = backend.prepare(&artifact, &key).await.unwrap();
    let mut stale = key.clone();
    stale.engine_configuration_digest = "blake3:".to_owned() + &"0".repeat(64);
    assert_eq!(
        backend.prepare(&artifact, &stale).await.unwrap_err().code,
        PlatformErrorCode::IncompatibleContract
    );
    let cancellation = Cancellation::new("host-abi-forgery");
    let mut forged = prepared.clone();
    forged.key = stale;
    let error = run(
        &backend,
        request(
            forged,
            &cancellation.id,
            fixture::CONTRACT,
            "inspect",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(error.message, "prepared-admission-descriptor-mismatch");
    // Even an authentic cached descriptor cannot stand in for current activation
    // bindings. This fails before value lifting or Store creation.
    let error = run(
        &backend,
        request(
            prepared,
            &cancellation.id,
            fixture::CONTRACT,
            "inspect",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
}
