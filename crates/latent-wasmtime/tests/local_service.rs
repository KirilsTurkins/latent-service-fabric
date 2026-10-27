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
#[path = "local_service/load.rs"]
mod load;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_service/outbound.rs"]
mod outbound;
#[path = "local_service/packages.rs"]
mod packages;
#[path = "local_service/runtime.rs"]
mod runtime;

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

#[cfg(all(
    feature = "development-test-host",
    target_os = "linux",
    target_arch = "x86_64"
))]
#[path = "guest_sdk/package.rs"]
mod join_cause_package;
#[cfg(all(
    feature = "development-test-host",
    target_os = "linux",
    target_arch = "x86_64"
))]
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

#[cfg(all(
    feature = "development-test-host",
    target_os = "linux",
    target_arch = "x86_64"
))]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires a separately reviewed NORMAL+auxiliary signed .NET fixture owner"]
async fn dotnet_join_cause_borrows_one_word_before_unchanged_native_finalization() {
    use latent_activation::ActivationOutcome;
    use latent_artifacts::ArtifactRepository;
    use latent_core::{ContractId, FunctionId, TenantId};
    use latent_signing::DOTNET_CAPSULE_BUILD_TYPE;
    use latent_wasmtime::DevelopmentJoinCause;
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("dotnet")
    );
    // Distinct source/component identities. Both traverse the real publisher /
    // builder verification, catalog, deployment, admission and node manager.
    let mut normal_source = None;
    let mut normal_release = None;
    for (name, auxiliary) in [
        ("dotnet-root-return-normal", false),
        ("dotnet-root-return-join-cause", true),
    ] {
        let bundle = join_cause_package::bundle(&join_cause_package::input(name));
        let observation = join_cause_package::observation(name);
        if auxiliary {
            assert_eq!(
                normal_source.as_ref(),
                Some(&observation.source.snapshot_digest)
            );
            assert_ne!(normal_release.as_ref(), Some(&packages::release(&bundle)));
        } else {
            normal_source = Some(observation.source.snapshot_digest.clone());
            normal_release = Some(packages::release(&bundle));
        }
        let signers = join_cause_package::Signers::new(DOTNET_CAPSULE_BUILD_TYPE);
        let temp = tempfile::tempdir().unwrap();
        let upload = signers.upload_for_tenant(&bundle, &observation, &TenantId("tenant-a".into()));
        let catalog =
            join_cause_package::catalog(temp.path(), signers.policy, Some(128 * 1024 * 1024));
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
        let actual_release = packages::release(&bundle);
        let manifest = latent_manifest::JsonManifestCodec::default();
        use latent_manifest::ManifestCodec;
        let ceiling = manifest
            .decode_capsule(bundle.blob("capsule.json").unwrap())
            .unwrap()
            .execution
            .resource_budget_ceiling;
        assert_eq!(ceiling.cpu_fuel, 1_000_000_000);
        assert_eq!(ceiling.memory_bytes, 128 * 1024 * 1024);
        assert_eq!(ceiling.wall_time_limit_millis, Some(120_000));
        // PackageBundle intentionally owns its bytes. Decode the second role
        // from the SAME bounded source and require its exact package identity.
        let callee_bundle = join_cause_package::bundle(&join_cause_package::input(name));
        assert_eq!(callee_bundle.layout().digest(), bundle.layout().digest());
        let f = fixture::Fixture::with_activation_runtime(
            1,
            (catalog, bundle, callee_bundle),
            latent_core::activation_runtime::RuntimeLimits {
                tasks: 8,
                executors: 2,
                queued_work: 8,
                waits: 16,
                timers: 8,
                results: 8,
                native_owners: 8,
            },
            120_000,
        )
        .await;
        for (mode, id, expected) in [
            (
                8,
                "dotnet-ac7-diag-quiescence",
                DevelopmentJoinCause::Quiescence,
            ),
            (
                9,
                "dotnet-ac7-diag-original-fault",
                DevelopmentJoinCause::OriginalFault,
            ),
            (
                10,
                "dotnet-ac7-diag-unexpected",
                DevelopmentJoinCause::Unexpected,
            ),
        ] {
            let mut request = f.request(id, mode);
            request.target.contract = ContractId("examples:greeting/api@1.0.0".into());
            request.target.function = FunctionId("probe".into());
            request.budget = ceiling.clone();
            let guard = auxiliary.then(|| {
                f.backend
                    .arm_development_join_cause_observation(
                        id,
                        &actual_release.0,
                        "examples:greeting/api@1.0.0",
                        "probe",
                    )
                    .unwrap()
            });
            let receipt = f.manager.start(request).unwrap().await;
            assert_eq!(
                receipt.resolved_revision.as_ref().unwrap().release,
                actual_release
            );
            // The original terminal path is unchanged. A diagnostic word is
            // neither an original trap nor a physical-retirement success.
            let terminal = match &receipt.outcome {
                ActivationOutcome::Failed { error, .. } => {
                    assert_eq!(error.code, latent_core::PlatformErrorCode::GuestTrap);
                    "guest-trap"
                }
                ActivationOutcome::DeclaredError { .. } => panic!("unexpected declared error"),
                ActivationOutcome::Succeeded(_) => {
                    panic!("auxiliary failure cannot qualify as success")
                }
            };
            let snapshot = guard.as_ref().map(|g| g.snapshot().unwrap());
            if let Some(s) = snapshot {
                assert_eq!(s.claims, 1);
                assert!(!s.invalid);
                assert_eq!(s.cause, Some(expected));
            }
            println!(
                "DOTNET_JOIN_CAUSE_AUX {}",
                serde_json::json!({
                "component":actual_release.0,"mode":mode,"auxiliary":auxiliary,
                "observation":snapshot,"terminalOutcome":terminal,
                "acceptedCauseEvidence":auxiliary && expected != DevelopmentJoinCause::Unexpected,
                "originalTrapQualified":false,"physicalRetirementQualified":false})
            );
        }
    }
}
