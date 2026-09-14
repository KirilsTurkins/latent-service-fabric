//! Real canonical-async caller and ordinary synchronous callee exports.
#![allow(
    clippy::similar_names,
    reason = "caller and callee name the two component roles"
)]
#[path = "local_service/acceptance.rs"]
mod acceptance;
#[path = "local_service/component.rs"]
mod component;
#[path = "local_service/fixture.rs"]
mod fixture;
#[path = "local_service/packages.rs"]
mod packages;

#[tokio::test]
async fn declared_service_import_without_a_node_adapter_has_no_execution_authority() {
    use latent_executor::ExecutionBackend;
    let factory =
        latent_wasmtime::WasmtimeComponentEngineFactory::new(latent_wasmtime::WasmtimeConfig {
            maximum_memory_bytes: packages::budget().memory_bytes,
            maximum_fuel: packages::budget().cpu_fuel,
            ..Default::default()
        })
        .unwrap();
    let backend = factory.create_backend_instance();
    let artifact = packages::artifact(&packages::caller(None));
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
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn two_real_components_use_compiled_binding_normal_admission_and_child_accounting() {
    use latent_activation::ActivationOutcome;
    let fixture = fixture::Fixture::new(2, false, true).await;
    let receipt = fixture
        .manager
        .start(fixture.request("parent", 0))
        .unwrap()
        .await;
    let success = match receipt.outcome {
        ActivationOutcome::Succeeded(success) => success,
        outcome => panic!("{outcome:?}"),
    };
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&success.output).unwrap(),
        serde_json::json!([u32::from_le_bytes(*b"[42]")])
    );
    assert_eq!(success.consumption.child_calls, 1);
    assert!(success.consumption.cpu_fuel > 0);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 0);
    let starts = fixture.observations.starts.lock().unwrap();
    assert_eq!(starts.len(), 2);
    assert_eq!(starts[1].parent_activation_id.as_ref().unwrap().0, "parent");
    assert_eq!(starts[1].root_activation_id.0, "parent");
    assert_eq!(starts[1].tenant.0, "tenant-a");
}

#[test]
fn both_real_components_have_checked_packages_and_exact_async_metadata() {
    let caller = packages::caller(None);
    let callee = packages::callee(42);
    latent_packaging::compile_host_binding(
        &caller,
        latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY,
        latent_packaging::PackageComparisonLimits::default(),
    )
    .unwrap();
    let target = latent_packaging::check_invocation_target(
        &callee,
        component::CALLEE,
        latent_packaging::PackageComparisonLimits::default(),
    )
    .unwrap();
    assert_eq!(target.functions(), ["answer", "fail", "spin"]);
}

#[tokio::test]
async fn asynchronous_application_export_waits_for_the_canonical_async_service_import() {
    use latent_component_bindings::host::phase3::latent::service::invoke as wit;
    use wasmtime::{
        component::{Component, Linker},
        Config, Engine, Store,
    };
    let mut config = Config::new();
    config.wasm_component_model_async(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, component::caller(None)).unwrap();
    let mut linker = Linker::<()>::new(&engine);
    linker
        .instance(latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY)
        .unwrap()
        .func_wrap_concurrent(
            "call",
            |_,
             (target, payload, media, options): (
                wit::Target,
                Vec<u8>,
                String,
                wit::CallOptions,
            )| {
                Box::pin(async move {
                    assert!(target.tenant.is_none());
                    assert_eq!(target.service, "callee");
                    assert_eq!(target.contract, component::CALLEE);
                    assert_eq!(target.function, "answer");
                    assert_eq!(payload, b"[]");
                    assert_eq!(media, "application/vnd.latent.wit-values.v1+json");
                    assert!(options.deadline_unix_millis.is_none());
                    assert!(options.metadata.is_empty());
                    tokio::task::yield_now().await;
                    Ok((wit::InvocationOutcome::Success(wit::InvocationResult {
                        payload: b"[42]".to_vec(),
                        media_type: media,
                        metadata: vec![],
                    }),))
                })
            },
        )
        .unwrap();
    let mut store = Store::new(&engine, ());
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let (_, interface) = instance
        .get_export(&mut store, None, component::CALLER)
        .unwrap();
    let (_, run) = instance
        .get_export(&mut store, Some(&interface), "run")
        .unwrap();
    let function = instance
        .get_typed_func::<(u32,), (u32,)>(&mut store, &run)
        .unwrap();
    let (value,) = function.call_async(&mut store, (0,)).await.unwrap();
    assert_eq!(value, u32::from_le_bytes(*b"[42]"));
}
