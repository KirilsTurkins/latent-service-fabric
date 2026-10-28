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

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires a separately reviewed NORMAL+auxiliary signed .NET fixture owner"]
async fn dotnet_join_cause_borrows_one_word_before_unchanged_native_finalization() {
    #[cfg(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    ))]
    {
        use latent_activation::ActivationOutcome;
        use latent_artifacts::ArtifactRepository;
        use latent_core::{ContractId, FunctionId, ServiceId, TenantId};
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
            let manifest = latent_manifest::JsonManifestCodec::default();
            use latent_manifest::ManifestCodec;
            let capsule = manifest
                .decode_capsule(bundle.blob("capsule.json").unwrap())
                .unwrap();
            let tenant: TenantId = capsule.metadata.tenant.expect("captured capsule tenant");
            let service = ServiceId(capsule.metadata.name);
            let ceiling = capsule.execution.resource_budget_ceiling;
            let signers =
                join_cause_package::Signers::for_tenant(DOTNET_CAPSULE_BUILD_TYPE, &tenant);
            let temp = tempfile::tempdir().unwrap();
            let upload = signers.upload_for_tenant(&bundle, &observation, &tenant);
            let catalog =
                join_cause_package::catalog(temp.path(), signers.policy, Some(128 * 1024 * 1024));
            catalog
                .admit_package(&tenant, upload, &mut |_| Ok(()))
                .await
                .unwrap();
            let actual_release = packages::release(&bundle);
            assert_eq!(ceiling.cpu_fuel, 1_000_000_000);
            assert_eq!(ceiling.memory_bytes, 128 * 1024 * 1024);
            assert_eq!(ceiling.wall_time_limit_millis, Some(120_000));
            assert_eq!(ceiling.child_calls, 0);
            // PackageBundle intentionally owns its bytes. Decode the second role
            // from the SAME bounded source and require its exact package identity.
            let callee_bundle = join_cause_package::bundle(&join_cause_package::input(name));
            assert_eq!(callee_bundle.layout().digest(), bundle.layout().digest());
            let f = fixture::Fixture::with_named_activation_runtime(
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
                fixture::RuntimeIdentities {
                    tenant,
                    caller: service.clone(),
                    callee: service,
                },
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
                    if s.invalid {
                        println!(
                            "DOTNET_JOIN_CAUSE_REJECT {}",
                            serde_json::json!({
                            "mode":mode,"observation":s,
                            "rejection":guard.as_ref().unwrap().rejection().unwrap()})
                        );
                    }
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
    #[cfg(not(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    )))]
    {
        panic!("requires the reviewed development-test-host Linux x86_64 fixture");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the separately reviewed canonical TaskReturn witness replay owner"]
async fn dotnet_join_cause_canonical_task_return_witness_preserves_original_failure() {
    #[cfg(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    ))]
    {
        use latent_activation::ActivationOutcome;
        use latent_artifacts::ArtifactRepository;
        use latent_core::{ContractId, FunctionId, ServiceId, TenantId};
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
            let manifest = latent_manifest::JsonManifestCodec::default();
            use latent_manifest::ManifestCodec;
            let capsule = manifest
                .decode_capsule(bundle.blob("capsule.json").unwrap())
                .unwrap();
            let tenant: TenantId = capsule.metadata.tenant.expect("captured capsule tenant");
            let service = ServiceId(capsule.metadata.name);
            let ceiling = capsule.execution.resource_budget_ceiling;
            let signers =
                join_cause_package::Signers::for_tenant(DOTNET_CAPSULE_BUILD_TYPE, &tenant);
            let temp = tempfile::tempdir().unwrap();
            let upload = signers.upload_for_tenant(&bundle, &observation, &tenant);
            let catalog =
                join_cause_package::catalog(temp.path(), signers.policy, Some(128 * 1024 * 1024));
            catalog
                .admit_package(&tenant, upload, &mut |_| Ok(()))
                .await
                .unwrap();
            let actual_release = packages::release(&bundle);
            assert_eq!(ceiling.cpu_fuel, 1_000_000_000);
            assert_eq!(ceiling.memory_bytes, 128 * 1024 * 1024);
            assert_eq!(ceiling.wall_time_limit_millis, Some(120_000));
            assert_eq!(ceiling.child_calls, 0);
            // PackageBundle intentionally owns its bytes. Decode the second role
            // from the SAME bounded source and require its exact package identity.
            let callee_bundle = join_cause_package::bundle(&join_cause_package::input(name));
            assert_eq!(callee_bundle.layout().digest(), bundle.layout().digest());
            let f = fixture::Fixture::with_named_activation_runtime(
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
                fixture::RuntimeIdentities {
                    tenant,
                    caller: service.clone(),
                    callee: service,
                },
            )
            .await;
            let journal = f.manager.journal();
            f.broker
                .install_diagnostic_sink(std::sync::Arc::new(journal.clone()))
                .unwrap();
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
                        .arm_development_task_return_observation(
                            id,
                            &actual_release.0,
                            "examples:greeting/api@1.0.0",
                            "probe",
                        )
                        .unwrap()
                });
                let diagnostic_tenant = request.target.tenant.clone();
                let receipt = f.manager.start(request).unwrap().await;
                let page = journal
                    .inspect_tree(&diagnostic_tenant, &receipt.activation_id, 1, None)
                    .unwrap();
                let journal_record = page
                    .nodes
                    .iter()
                    .find(|node| node.activation_id == receipt.activation_id);
                assert_eq!(
                    receipt.resolved_revision.as_ref().unwrap().release,
                    actual_release
                );
                // The original terminal path is unchanged. A diagnostic word is
                // neither an original trap nor a physical-retirement success.
                let terminal = match &receipt.outcome {
                    ActivationOutcome::Failed { error, .. } => {
                        assert_eq!(error.code, latent_core::PlatformErrorCode::GuestTrap);
                        let numeric = |d: &latent_core::diagnostic::ActivationDiagnostic,
                                       terminal: bool| {
                            serde_json::json!({"stage":d.stage as u32,"reason":d.reason as u32,
                                "configuredBound":d.configured_bound,"calculatedRequirement":d.calculated_requirement,
                                "terminal":terminal})
                        };
                        let last_observed = journal_record
                            .filter(|node| !node.diagnostic_is_terminal)
                            .and_then(|node| node.diagnostic.as_ref())
                            .map(|d| numeric(d, false));
                        let terminal_diagnostic =
                            latent_core::diagnostic::ActivationDiagnostic::from_error(error);
                        println!(
                            "DOTNET_JOIN_RESOURCE_DIAGNOSTIC {}",
                            serde_json::json!({
                            "mode":mode,"auxiliary":auxiliary,"lastObservedDiagnostic":last_observed,
                            "terminalDiagnostic":terminal_diagnostic.as_ref().map(|d| numeric(d, true)),
                            "journalDiagnosticIsTerminal":journal_record.map(|node| node.diagnostic_is_terminal)})
                        );
                        let classified = (|| {
                            use latent_core::error::GuestTrapKind;
                            let mut details = error
                                .details
                                .iter()
                                .filter(|d| d.kind == "activation.guest-trap-kind");
                            let detail = details.next()?;
                            if details.next().is_some() {
                                return None;
                            }
                            let kind = GuestTrapKind::from_wire_name(detail.fields.get("kind")?)?;
                            let phase = match (kind, detail.fields.get("phase").map(String::as_str))
                            {
                                (_, None) => None,
                                (GuestTrapKind::RuntimeError, Some("instantiate")) => {
                                    Some("instantiate")
                                }
                                (GuestTrapKind::RuntimeError, Some("export-lookup")) => {
                                    Some("export-lookup")
                                }
                                (GuestTrapKind::RuntimeError, Some("call-and-postreturn")) => {
                                    Some("call-and-postreturn")
                                }
                                _ => return None,
                            };
                            if detail.fields.len() != 1 + usize::from(phase.is_some()) {
                                return None;
                            }
                            let mut hosts = error
                                .details
                                .iter()
                                .filter(|d| d.kind == "activation.guest-host-failure");
                            let host = if let Some(detail) = hosts.next() {
                                if detail.fields.len() != 1 {
                                    return None;
                                }
                                Some(
                                    latent_core::PlatformErrorCode::from_wire_code(
                                        detail.fields.get("code")?,
                                    )?
                                    .wire_code(),
                                )
                            } else {
                                None
                            };
                            if hosts.next().is_some()
                                || (host.is_some() && kind != GuestTrapKind::RuntimeError)
                            {
                                return None;
                            }
                            Some((kind.wire_name(), phase, host))
                        })();
                        let (trap_kind, phase, host) = classified
                            .map(|(k, p, h)| (Some(k), p, h))
                            .unwrap_or((None, None, None));
                        println!(
                            "DOTNET_JOIN_FAILURE_CLASSIFICATION {}",
                            serde_json::json!({
                            "mode":mode,"auxiliary":auxiliary,"trapKind":trap_kind,
                            "runtimePhase":phase,"hostFailureCode":host})
                        );
                        "guest-trap"
                    }
                    ActivationOutcome::DeclaredError { .. } => panic!("unexpected declared error"),
                    ActivationOutcome::Succeeded(_) => {
                        panic!("auxiliary failure cannot qualify as success")
                    }
                };
                let snapshot = guard.as_ref().map(|g| g.snapshot().unwrap());
                let post_call = guard.as_ref().map(|g| g.post_call_snapshot().unwrap());
                let rejection = guard.as_ref().and_then(|g| g.rejection().unwrap());
                let cause_evidence = auxiliary
                    && expected != DevelopmentJoinCause::Unexpected
                    && snapshot
                        .is_some_and(|s| s.claims == 1 && !s.invalid && s.cause == Some(expected));
                // Emit the closed first refusal before any assertion can fail.
                // This NEW stage cannot turn the old failed outer oracle green.
                println!(
                    "DOTNET_JOIN_TASK_RETURN {}",
                    serde_json::json!({
                        "component":actual_release.0,"mode":mode,"auxiliary":auxiliary,
                        "stage":"canonicalTaskReturnBeforeScopeExit",
                        "taskReturnWitness":snapshot,"postCallObservation":post_call,
                        "rejection":rejection,"terminalOutcome":terminal,
                        "outerInvocationSucceeded":false,
                        "canonicalTaskReturnCauseEvidence":cause_evidence,
                        "oldPostCallProgrammeQualified":false,
                        "originalTrapQualified":false,"physicalRetirementQualified":false})
                );
                if let Some(s) = snapshot {
                    assert_eq!(s.claims, 1);
                    assert!(!s.invalid);
                    assert_eq!(s.cause, Some(expected));
                }
            }
        }
    }
    #[cfg(not(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    )))]
    {
        panic!("requires the reviewed development-test-host Linux x86_64 fixture");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the separately signed private managed-stage diagnostic owner"]
async fn dotnet_managed_stage_diagnostic_preserves_failed_root_return_boundary() {
    #[cfg(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    ))]
    {
        use latent_activation::ActivationOutcome;
        use latent_artifacts::{AdmissionAuthority, ArtifactRepository};
        use latent_core::{ContractId, FunctionId, ServiceId};
        use latent_manifest::ManifestCodec;
        let name = "dotnet-root-return-managed-stage";
        let observation = join_cause_package::observation(name);
        assert_eq!(
            observation.build_type,
            latent_signing::DOTNET_MANAGED_STAGE_DIAGNOSTIC_BUILD_TYPE
        );
        assert!(!observation
            .materials
            .iter()
            .any(|row| row.name == "closed-runtime"));
        // The truthful private adapter subset must not satisfy the ordinary recipe.
        let mut ordinary = observation.clone();
        ordinary.build_type = latent_signing::DOTNET_CAPSULE_BUILD_TYPE.into();
        let error = latent_signing::decode_build_observation(
            &serde_json::to_vec(&ordinary).unwrap(),
            latent_signing::ProvenanceLimits::default(),
        )
        .unwrap_err();
        assert_eq!(
            error.reason(),
            latent_signing::SignatureFailure::MalformedProvenance
        );
        assert_eq!(
            std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
            Ok("dotnet")
        );
        let supplied = std::env::var("LSF_DOTNET_MANAGED_STAGE_COMPONENT")
            .expect("operator exact component digest");
        let encoded = supplied.strip_prefix("sha256:").expect("prefixed digest");
        assert_eq!(encoded.len(), 64);
        let mut component = [0u8; 32];
        for (index, pair) in encoded.as_bytes().chunks_exact(2).enumerate() {
            let digit = |byte| match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                _ => panic!("lowercase hexadecimal component digest required"),
            };
            component[index] = (digit(pair[0]) << 4) | digit(pair[1]);
        }
        let limits = latent_packaging::PackagingLimits::default();
        use std::io::Read;
        let mut source = Vec::new();
        std::fs::File::open(join_cause_package::input(name).join("package-source.json"))
            .unwrap()
            .take(65537)
            .read_to_end(&mut source)
            .unwrap();
        assert!(source.len() <= 65536);
        let source = latent_packaging::decode_package_source(&source, limits).unwrap();
        // SAME real compiled bytes: defaults cannot accept this private import.
        let input =
            latent_packaging::read_package_input(&join_cause_package::input(name), &source, limits)
                .unwrap();
        let error = latent_packaging::build_package(input, limits).unwrap_err();
        assert_eq!(
            error.code,
            latent_core::PlatformErrorCode::IncompatibleContract
        );
        assert_eq!(error.message, "unsupported-host-import");
        let mut wrong_limits = limits;
        let mut wrong = component;
        wrong[0] ^= 1;
        wrong_limits.semantics.development_managed_stage_component = Some(wrong);
        let input = latent_packaging::read_package_input(
            &join_cause_package::input(name),
            &source,
            wrong_limits,
        )
        .unwrap();
        let error = latent_packaging::build_package(input, wrong_limits).unwrap_err();
        assert_eq!(error.message, "private-stage-component-mismatch");
        let bundle =
            join_cause_package::managed_stage_bundle(&join_cause_package::input(name), component);
        let release = packages::release(&bundle);
        assert_eq!(supplied, release.0);
        assert_eq!(
            bundle
                .surface()
                .unwrap()
                .development_managed_stage_profile()
                .unwrap()
                .0,
            "dotnet-managed-stage-diagnostic-v2"
        );
        let capsule = latent_manifest::JsonManifestCodec::default()
            .decode_capsule(bundle.blob("capsule.json").unwrap())
            .unwrap();
        let tenant = capsule.metadata.tenant.expect("captured tenant");
        let service = ServiceId(capsule.metadata.name);
        let ceiling = capsule.execution.resource_budget_ceiling;
        assert_eq!(ceiling.cpu_fuel, 1_000_000_000);
        assert_eq!(ceiling.memory_bytes, 128 * 1024 * 1024);
        assert_eq!(ceiling.wall_time_limit_millis, Some(120_000));
        assert_eq!(ceiling.child_calls, 0);
        let signers = join_cause_package::Signers::for_tenant(
            latent_signing::DOTNET_MANAGED_STAGE_DIAGNOSTIC_BUILD_TYPE,
            &tenant,
        );
        let directory = tempfile::tempdir().unwrap();
        let upload = signers.upload_for_tenant(&bundle, &observation, &tenant);
        let replay = signers.upload_for_tenant(&bundle, &observation, &tenant);
        let (catalog, authority) = join_cause_package::managed_stage_catalog(
            directory.path(),
            signers.policy,
            Some(128 * 1024 * 1024),
            component,
        );
        // Real publisher/builder/SBOM verification first creates the retained binding.
        // Recovery repeats exact profile+digest and all historical/evidence checks.
        let checked = authority.verify(&tenant, replay).unwrap();
        let binding = checked.grant.binding().clone();
        let recovered = authority.recover(&binding, checked.upload).unwrap();
        assert_eq!(recovered.grant.binding().release, release);
        drop(recovered);
        catalog
            .admit_package(&tenant, upload, &mut |_| Ok(()))
            .await
            .unwrap();
        let callee =
            join_cause_package::managed_stage_bundle(&join_cause_package::input(name), component);
        assert_eq!(callee.layout().digest(), bundle.layout().digest());
        let f = fixture::Fixture::with_managed_stage_runtime(
            (catalog, bundle, callee),
            latent_core::activation_runtime::RuntimeLimits {
                tasks: 8,
                executors: 2,
                queued_work: 8,
                waits: 16,
                timers: 8,
                results: 8,
                native_owners: 8,
            },
            fixture::RuntimeIdentities {
                tenant,
                caller: service.clone(),
                callee: service,
            },
            component,
        )
        .await;
        let mut programme_failed = false;
        for (mode, id) in [
            (3, "dotnet-managed-stage-handled"),
            (9, "dotnet-managed-stage-unobserved"),
        ] {
            let mut request = f.request(id, mode);
            request.target.contract = ContractId("examples:greeting/api@1.0.0".into());
            request.target.function = FunctionId("probe".into());
            request.budget = ceiling.clone();
            let guard = f
                .backend
                .arm_development_managed_stage(id, &release.0)
                .unwrap();
            let receipt = f.manager.start(request).unwrap().await;
            assert_eq!(receipt.resolved_revision.as_ref().unwrap().release, release);
            let terminal = match &receipt.outcome {
                ActivationOutcome::Succeeded(success) if mode == 3 => {
                    assert_eq!(
                        serde_json::from_slice::<Vec<u32>>(&success.output).unwrap(),
                        [0xAC70_0003]
                    );
                    "succeeded"
                }
                ActivationOutcome::Failed { error, .. } if mode == 9 => {
                    assert_eq!(error.code, latent_core::PlatformErrorCode::GuestTrap);
                    "guest-trap"
                }
                ActivationOutcome::Failed { error, .. } => {
                    // Project only validated closed categories, never error text or frames.
                    let classified = (|| {
                        use latent_core::error::GuestTrapKind;
                        let mut rows = error
                            .details
                            .iter()
                            .filter(|row| row.kind == "activation.guest-trap-kind");
                        let row = rows.next()?;
                        if rows.next().is_some() {
                            return None;
                        }
                        let kind = GuestTrapKind::from_wire_name(row.fields.get("kind")?)?;
                        let phase = match (kind, row.fields.get("phase").map(String::as_str)) {
                            (_, None) => None,
                            (GuestTrapKind::RuntimeError, Some("instantiate")) => {
                                Some("instantiate")
                            }
                            (GuestTrapKind::RuntimeError, Some("export-lookup")) => {
                                Some("export-lookup")
                            }
                            (GuestTrapKind::RuntimeError, Some("call-and-postreturn")) => {
                                Some("call-and-postreturn")
                            }
                            _ => return None,
                        };
                        if row.fields.len() != 1 + usize::from(phase.is_some()) {
                            return None;
                        }
                        Some((kind.wire_name(), phase))
                    })();
                    if mode == 3 && error.code == latent_core::PlatformErrorCode::GuestTrap {
                        programme_failed = true;
                        eprintln!("private diagnostic changed the original terminal boundary: platform={} trap={:?}",
                            error.code.wire_code(), classified);
                        "guest-trap"
                    } else {
                        panic!("private diagnostic changed the original terminal boundary: platform={} trap={:?}",
                            error.code.wire_code(), classified);
                    }
                }
                _ => panic!("private diagnostic changed the original terminal boundary"),
            };
            let snapshot = guard.snapshot().unwrap();
            assert_eq!(snapshot.claims, 1);
            assert!(!snapshot.invalid);
            assert!(snapshot.cause.is_none());
            assert!(guard.rejection().unwrap().is_none());
            println!(
                "DOTNET_MANAGED_STAGE_CALL {}",
                serde_json::json!({
                    "profile":"dotnet-managed-stage-diagnostic-v2", "component":release.0,
                    "mode":mode, "terminalOutcome":terminal, "claims":snapshot.claims,
                    "originalCauseQualified":false, "originalSixCallsQualified":false,
                    "fullAc7Qualified":false, "physicalRetirementQualified":false, "nativeAccountingQualified":false
                })
            );
            drop(guard);
            f.idle().await;
        }
        assert!(
            !programme_failed,
            "private diagnostic changed the original terminal boundary"
        );
    }
    #[cfg(not(all(
        feature = "development-test-host",
        target_os = "linux",
        target_arch = "x86_64"
    )))]
    {
        panic!("requires the reviewed development-test-host Linux x86_64 fixture");
    }
}
