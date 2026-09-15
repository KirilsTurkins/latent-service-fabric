use super::support;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use latent_artifacts::CapsuleArtifact;
use latent_core::{ActivationId, CapabilityId, ContractId, ResourceBudget};
use latent_executor::{BoundImport, ExecutionRequest, PreparedComponent};
use latent_manifest::{ContractImport, RendererRequirement};
use latent_wasmtime::{WasmtimeBackend, WasmtimeConfig};
use serde_json::Value;

pub const WEB: &str = "latent:web/application@0.1.0";
const CONTEXT: &str = "latent:context/context@0.1.0";

pub fn config() -> WasmtimeConfig {
    let mut config = WasmtimeConfig {
        maximum_component_bytes: 32 * 1024 * 1024,
        maximum_memory_bytes: 256 * 1024 * 1024,
        maximum_fuel: 2_000_000_000,
        fuel_async_yield_interval: Some(10_000),
        hostcall_fuel: 2 * 1024 * 1024,
        ..WasmtimeConfig::default()
    };
    config.install_angular_renderer();
    config.value_codec_limits.max_input_bytes = 2 * 1024 * 1024;
    config.value_codec_limits.max_output_bytes = 2 * 1024 * 1024;
    config.value_codec_limits.max_string_bytes = 512 * 1024;
    config.value_codec_limits.max_nodes = 32768;
    config.value_codec_limits.max_lifted_bytes = 64 * 1024 * 1024;
    config
}

pub fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 2_000_000_000,
        memory_bytes: 256 * 1024 * 1024,
        wall_time_limit_millis: Some(5000),
        ..support::budget()
    }
}

pub fn artifact() -> CapsuleArtifact {
    let bytes = std::fs::read(
        std::env::var_os("LSF_ANGULAR_COMPONENT").expect("required Angular renderer gate fixture"),
    )
    .unwrap();
    let mut artifact = support::artifact_bytes(bytes, &[WEB]);
    artifact.manifest.world = ContractId("tests:angular/service@0.1.0".into());
    artifact.manifest.imports = vec![ContractImport {
        contract: ContractId(CONTEXT.into()),
        optional: false,
    }];
    artifact.manifest.runtime_requirements.renderer = Some(RendererRequirement::angular());
    artifact.manifest.execution.resource_budget_ceiling = budget();
    artifact
}

pub fn request(prepared: &PreparedComponent, id: &ActivationId, path: &str) -> ExecutionRequest {
    let mut value: Value = serde_json::from_slice(include_bytes!(
        "../../../latent-ingress/tests/fixtures/http-request-v1.json"
    ))
    .unwrap();
    value[0]["path"] = path.into();
    value[0]["headers"][0]["value"] =
        serde_json::to_value(format!("session={}", id.0).as_bytes()).unwrap();
    let mut request = support::request(
        prepared.clone(),
        id,
        WEB,
        "handle",
        &serde_json::to_vec(&value).unwrap(),
        budget(),
    );
    request.activation.principal.subject.clone_from(&id.0);
    request.activation.root_activation_id = ActivationId(format!("root-{}", id.0));
    request.activation.parent_activation_id = Some(ActivationId(format!("parent-{}", id.0)));
    request.imports = vec![BoundImport {
        capability: CapabilityId("context".into()),
        contract: CONTEXT.into(),
        opaque_handle: "activation-owned-context".into(),
    }];
    request
}

pub fn html(value: &Value) -> String {
    String::from_utf8(
        STANDARD
            .decode(value[0]["body-base64"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap()
}

pub async fn success(backend: &WasmtimeBackend, prepared: &PreparedComponent, subject: &str) {
    let cancel = support::Cancellation::new(subject);
    let value = support::returned(
        support::run(backend, request(prepared, &cancel.id, "/"), &cancel)
            .await
            .unwrap(),
    );
    assert_eq!(value[0]["status"], 200);
    assert_eq!(value[0]["headers"][0]["name"], "x-renderer-calls");
    assert_eq!(value[0]["headers"][0]["value"], serde_json::json!([49]));
    let html = html(&value);
    assert!(
        html.contains("ngh="),
        "Angular hydration annotations absent"
    );
    assert!(html.contains("&lt;private&gt;") || !subject.contains('<'));
    let state = html
        .split("<script id=\"ng-state\" type=\"application/json\">")
        .nth(1)
        .unwrap();
    let state: Value = serde_json::from_str(state.split("</script>").next().unwrap()).unwrap();
    let data: Value = serde_json::from_str(state["lsf-name"].as_str().unwrap()).unwrap();
    assert_eq!(data["principal"]["subject"], subject);
    assert_eq!(data["activation"], subject);
    assert_eq!(data["root"], format!("root-{subject}"));
    assert_eq!(data["parent"], format!("parent-{subject}"));
    assert_eq!(data["callbacks"], serde_json::json!(["timer", "microtask"]));
    assert_eq!(
        data["cookies"][0]["value"],
        serde_json::to_value(format!("session={subject}").as_bytes()).unwrap()
    );
    assert_eq!(data["trace"]["traceId"], "trace-generic");
    assert!(data["deadline"].as_str().unwrap().parse::<u64>().is_ok());
}
