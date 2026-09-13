use super::*;
use latent_component_bindings::host::phase3::latent::http::client as http;
use latent_core::{HostInterfaceBinding, PHASE3_HOST_ABI_V2};
use wasmtime::component::Component;
use wasmtime::{Config, Engine};

#[path = "../../../latent-packaging/tests/fixtures/component.rs"]
mod fixture;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host_fixture;

fn engine() -> Engine {
    let mut config = Config::new();
    crate::WasmtimeConfig::default()
        .apply_engine(&mut config)
        .unwrap();
    Engine::new(&config).unwrap()
}

#[test]
fn generated_builtin_linker_matches_every_exact_pinned_shape() {
    let engine = engine();
    let mut linker = Linker::<HostState>::new(&engine);
    install_context_log_clock(&mut linker).unwrap();
    for spec in PHASE3_HOST_ABI_V2.interfaces() {
        let bytes = fixture::with_host(
            fixture::Options::default(),
            spec.interface,
            &host_fixture::interface(spec.wit, spec.interface, None),
        );
        let component = Component::new(&engine, bytes).unwrap();
        let preparation = linker.instantiate_pre(&component);
        if spec.binding == HostInterfaceBinding::BuiltIn {
            preparation.unwrap_or_else(|error| panic!("{}: {error:?}", spec.interface));
        } else {
            assert!(
                preparation.is_err(),
                "{} must require an actual provider",
                spec.interface
            );
        }
    }
    let spec = PHASE3_HOST_ABI_V2.interface(fixture::CLOCK).unwrap();
    let changed = spec
        .wit
        .replace("now-nanos: func() -> u64", "now-nanos: func() -> u32");
    let wrong_shape = fixture::with_host(
        fixture::Options::default(),
        spec.interface,
        &host_fixture::interface(&changed, spec.interface, None),
    );
    assert!(linker
        .instantiate_pre(&Component::new(&engine, wrong_shape).unwrap())
        .is_err());
    let wrong_version = spec.interface.replace("0.1.0", "0.2.0");
    let bytes = fixture::with_host(
        fixture::Options::default(),
        &wrong_version,
        &host_fixture::interface(spec.wit, spec.interface, None),
    );
    assert!(linker
        .instantiate_pre(&Component::new(&engine, bytes).unwrap())
        .is_err());
}

// Only a test provider: no endpoint, credential, pool or production registration.
struct TestHttp;
impl http::Host for TestHttp {}
impl http::HostWithStore<TestHttp> for HasSelf<TestHttp> {
    async fn send(
        _accessor: &wasmtime::component::Accessor<TestHttp, Self>,
        _request: http::Request,
    ) -> Result<http::Response, http::HttpError> {
        tokio::task::yield_now().await;
        Err(http::HttpError::Unavailable)
    }
}

#[test]
fn generated_async_provider_binding_accepts_only_its_exact_interface() {
    let engine = engine();
    let spec = PHASE3_HOST_ABI_V2
        .interface("latent:http/client@0.2.0")
        .unwrap();
    let bytes = fixture::with_host(
        fixture::Options::default(),
        spec.interface,
        &host_fixture::interface(spec.wit, spec.interface, None),
    );
    let component = Component::new(&engine, bytes).unwrap();
    let mut linker = Linker::<TestHttp>::new(&engine);
    assert!(linker.instantiate_pre(&component).is_err());
    http::add_to_linker::<TestHttp, HasSelf<TestHttp>>(&mut linker, |state| state).unwrap();
    linker.instantiate_pre(&component).unwrap();
    let source = spec.wit.replace("status: u16", "status: u32");
    let forged = fixture::with_host(
        fixture::Options::default(),
        spec.interface,
        &host_fixture::interface(&source, spec.interface, None),
    );
    assert!(linker
        .instantiate_pre(&Component::new(&engine, forged).unwrap())
        .is_err());
}

#[test]
fn frozen_schema_matrix_matches_host_shapes_identity_and_generated_sdk_baseline() {
    use sha2::{Digest, Sha256};
    let matrix: serde_json::Value =
        serde_json::from_str(include_str!("../../../../wit/host-abi-phase3-v2.json")).unwrap();
    let profile = PHASE3_HOST_ABI_V2;
    assert_eq!(matrix["id"], profile.id);
    assert_eq!(
        matrix["digest"],
        format!(
            "sha256:{:x}",
            sha2::digest::Output::<Sha256>::from(host_abi_digest())
        )
    );
    assert_eq!(
        matrix["wasmtimeVersion"],
        crate::WasmtimeConfig::default()
            .profile(crate::config::DispatchMode::Generic)
            .wasmtime_version
    );
    let entries = matrix["interfaces"].as_array().unwrap();
    assert_eq!(entries.len(), profile.interfaces().len());
    for (entry, spec) in entries.iter().zip(profile.interfaces()) {
        assert_eq!(entry["interface"], spec.interface);
        assert_eq!(entry["package"], spec.package);
        assert_eq!(
            entry["sourceSha256"],
            format!("sha256:{:x}", Sha256::digest(spec.wit.as_bytes()))
        );
        assert_eq!(entry["asynchronous"], spec.asynchronous);
        assert_eq!(
            entry["binding"],
            if spec.binding == HostInterfaceBinding::BuiltIn {
                "built-in"
            } else {
                "provider"
            }
        );
        assert_eq!(
            entry["installed"],
            spec.binding == HostInterfaceBinding::BuiltIn
        );
    }
}
