use latent_core::{CapabilityId, ContractId, PlatformErrorCode};
use latent_executor::{BoundImport, ExecutionBackend};
use latent_manifest::{ContractExport, ContractImport};
use latent_wasmtime::WasmtimeComponentEngineFactory;
use serde_json::json;

use super::dispatch::composite;
use super::support::{
    adversarial, artifact, artifact_bytes, budget, config, idle, prepared, request, returned, run,
    Cancellation, MEDIA, VALUES,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the echo component built by tools/validate_contracts.sh"]
async fn binds_existing_host_imports_per_activation_through_generic_dispatch() {
    let component =
        std::path::PathBuf::from(std::env::var_os("LSF_ECHO_COMPONENT").expect("echo path"));
    let contract = "examples:echo/api@0.1.0";
    let mut artifact = artifact_bytes(
        std::fs::read(component).expect("echo component"),
        &[contract],
    );
    let imports = [
        ("context", "latent:context/context@0.1.0"),
        ("log", "latent:log/log@0.1.0"),
    ];
    artifact.manifest.world = ContractId("examples:echo/service@0.1.0".to_owned());
    artifact.manifest.imports = imports
        .iter()
        .map(|(_, name)| ContractImport {
            contract: ContractId((*name).to_owned()),
            optional: false,
        })
        .collect();
    let factory = WasmtimeComponentEngineFactory::new(config()).expect("factory");
    let backend = factory.create_backend_instance();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("echo imports supported by generic backend");
    let cancellation = Cancellation::new("generic-host-imports");
    let mut request = request(
        prepared,
        &cancellation.id,
        contract,
        "echo",
        br#"["small"]"#,
        budget(),
    );
    let error = run(&backend, request.clone(), &cancellation)
        .await
        .expect_err("missing activation bindings");
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    request.imports = imports
        .iter()
        .map(|(capability, contract)| BoundImport {
            capability: CapabilityId((*capability).to_owned()),
            contract: (*contract).to_owned(),
            opaque_handle: "activation-scoped-test-binding".to_owned(),
        })
        .collect();
    assert_eq!(
        returned(
            run(&backend, request, &cancellation)
                .await
                .expect("bound invocation")
        ),
        json!([{"ok": "small"}])
    );
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn rejects_missing_exports_media_and_parameter_shapes_before_creating_a_store() {
    let (backend, prepared) = prepared(config()).await;
    let cancellation = Cancellation::new("invalid-input");
    for (contract, function, media, input) in [
        (
            "tests:missing/api@0.1.0",
            "identify",
            MEDIA,
            b"[]".as_slice(),
        ),
        (VALUES, "missing", MEDIA, b"[]".as_slice()),
        (VALUES, "identify", "text/plain", b"[]".as_slice()),
        (VALUES, "combine", MEDIA, b"[1]".as_slice()),
        (VALUES, "combine", MEDIA, b"[1,2,3]".as_slice()),
        (VALUES, "combine", MEDIA, b"[1,true]".as_slice()),
        (VALUES, "combine", MEDIA, b"[2147483648,0]".as_slice()),
        (VALUES, "identify", MEDIA, b"{".as_slice()),
        (VALUES, "identify", MEDIA, b"[] trailing-secret".as_slice()),
    ] {
        let mut request = request(
            prepared.clone(),
            &cancellation.id,
            contract,
            function,
            input,
            budget(),
        );
        request.activation.input_media_type = media.to_owned();
        let error = run(&backend, request, &cancellation)
            .await
            .expect_err("invalid request");
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        assert!(!format!("{error:?}").contains("trailing-secret"));
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn rejects_invalid_composite_shapes_without_entering_guest_code() {
    let (backend, prepared) = prepared(config()).await;
    let cancellation = Cancellation::new("invalid-composite");
    let mut cases = Vec::new();
    for (field, invalid) in [
        ("color", json!("unknown")),
        ("access", json!(["read", "read"])),
        ("choice", json!({"case": "named"})),
        ("maybe", json!(null)),
        ("pair", json!([1])),
        ("nested", json!({"ok": 1, "err": "ambiguous"})),
    ] {
        let mut value = composite();
        value[field] = invalid;
        cases.push(value);
    }
    let mut extra = composite();
    extra["unexpected"] = json!("must-not-reach-guest");
    cases.push(extra);
    let mut missing = composite();
    missing.as_object_mut().expect("record").remove("bytes");
    cases.push(missing);
    let mut number = composite();
    number["numbers"]["wide"] = json!(42);
    cases.push(number);
    for value in cases {
        let input = serde_json::to_vec(&json!([value])).expect("fixture JSON");
        let error = run(
            &backend,
            request(
                prepared.clone(),
                &cancellation.id,
                VALUES,
                "transform",
                &input,
                budget(),
            ),
            &cancellation,
        )
        .await
        .expect_err("invalid composite");
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic and WAT components built by tools/validate_contracts.sh"]
async fn rejects_manifest_surface_disagreement_unresolved_imports_and_resource_types() {
    let factory = WasmtimeComponentEngineFactory::new(config()).expect("factory");
    let backend = factory.create_backend_instance();
    let mut missing_export = artifact();
    missing_export.manifest.exports.pop();
    let mut nonexistent_export = artifact();
    nonexistent_export.manifest.exports.push(ContractExport {
        contract: ContractId("tests:missing/api@0.1.0".to_owned()),
    });
    let mut unresolved_import = adversarial("unknown-import");
    unresolved_import.manifest.imports.push(ContractImport {
        contract: ContractId("tests:unavailable/host@0.1.0".to_owned()),
        optional: false,
    });
    for artifact in [
        missing_export,
        nonexistent_export,
        unresolved_import,
        adversarial("unsupported-resource"),
    ] {
        let error = backend
            .prepare(
                &artifact,
                &factory.preparation_key(artifact.descriptor.release_digest.clone()),
            )
            .await
            .expect_err("incompatible component");
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert_eq!(backend.cache_snapshot().entries, 0);
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn applies_input_and_output_byte_limits_with_reusable_cleanup() {
    let mut limited = config();
    limited.value_codec_limits.max_input_bytes = 4;
    let (backend, prepared) = prepared(limited).await;
    let cancellation = Cancellation::new("input-limit");
    let error = run(
        &backend,
        request(
            prepared,
            &cancellation.id,
            VALUES,
            "combine",
            b"[1,2]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect_err("input bytes exceed explicit bound");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);

    let mut limited = config();
    limited.value_codec_limits.max_output_bytes = 3;
    let (backend, prepared) = super::support::prepared(limited).await;
    let cancellation = Cancellation::new("output-limit");
    let error = run(
        &backend,
        request(
            prepared,
            &cancellation.id,
            VALUES,
            "identify",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect("post-execution output rejection retains consumption");
    let latent_executor::GuestOutcome::Trapped { trap, consumption } = error else {
        panic!("expected bounded result trap")
    };
    assert_eq!(trap.code, "result-limit-exceeded");
    assert!(consumption.cpu_fuel > 0);
    assert!(consumption.peak_memory_bytes > 0);
    assert_eq!(backend.resource_snapshot().stores_created, 1);
    idle(&backend);
}
