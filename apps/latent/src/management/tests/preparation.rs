use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use clap::Parser;
use latent_artifacts::content_digest;
use latent_manifest::ManifestCodec;

use crate::args::{
    ApplyArgs, Command, DeleteArgs, DeploymentCommand, DeploymentOperationArgs, FileArgs,
    OptionalReleaseOperation, PublishArgs, ReleaseCommand, ServicePageArgs, ValidateCommand,
};
use crate::config::{InputLimits, ResolvedConfig};
use crate::operation::Operation;

use super::prepare;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Files(PathBuf);
impl Files {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "latent-cli-management-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn put(&self, name: &str, bytes: &[u8]) -> PathBuf {
        let path = self.0.join(name);
        fs::write(&path, bytes).unwrap();
        path
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn config() -> ResolvedConfig {
    ResolvedConfig {
        endpoint: "http://127.0.0.1:1".to_owned(),
        tenant: "examples".to_owned(),
        token: "x".repeat(32),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
        manifest_profile: latent_manifest::ManifestValidationProfile::default(),
    }
}

#[test]
fn transaction_deployment_preparation_keeps_default_refusal_and_exact_preconditions() {
    let files = Files::new();
    let mut manifest: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../../../examples/echo-contract/deployment.json"
    ))
    .unwrap();
    manifest["spec"]["publication"] =
        serde_json::json!(format!("publication:sha256:{}", "a".repeat(64)));
    manifest["spec"]["resources"]["stateReadBytes"] = serde_json::json!(4096);
    manifest["spec"]["resources"]["stateWriteBytes"] = serde_json::json!(8192);
    let file = files.put("deployment.json", &serde_json::to_vec(&manifest).unwrap());
    let command = Command::Deployment(DeploymentCommand::Apply(ApplyArgs {
        file: file.clone(),
        expected_generation: Some(0),
        operation: DeploymentOperationArgs {
            operation_id: Some("transaction-install".to_owned()),
            expected_state_version: Some(u64::MAX),
        },
    }));
    let original = fs::read(&file).unwrap();
    assert!(prepare::prepare(&command, &config()).is_err());
    let mut selected = config();
    selected.manifest_profile =
        crate::args::Cli::try_parse_from(["latent", "--phase4", "node", "list"])
            .unwrap_or_else(|_| panic!("test command"))
            .manifest_profile()
            .unwrap();
    let Operation::ApplyDeployment(request) = prepare::prepare(&command, &selected).unwrap() else {
        panic!("deployment operation");
    };
    assert_eq!(request.expected_generation, Some(0));
    assert_eq!(
        request.operation.unwrap().expected_state_version,
        Some(u64::MAX)
    );
    let deployment = request.deployment.unwrap();
    let resources = deployment.resources.unwrap();
    assert_eq!(resources.state_read_bytes, 4096);
    assert_eq!(resources.state_write_bytes, 8192);
    assert_eq!(fs::read(&file).unwrap(), original);
    selected.tenant = "foreign".to_owned();
    assert!(prepare::prepare(&command, &selected).is_err());
    manifest["spec"]["routeWeight"] = serde_json::json!(10_001);
    fs::write(&file, serde_json::to_vec(&manifest).unwrap()).unwrap();
    selected.tenant = "examples".to_owned();
    assert!(prepare::prepare(&command, &selected).is_err());
}

#[test]
fn apply_and_delete_keep_absent_zero_and_maximum_preconditions() {
    let files = Files::new();
    let file = files.put(
        "deployment.json",
        include_bytes!("../../../../../examples/echo-contract/deployment.json"),
    );
    let command = Command::Deployment(DeploymentCommand::Apply(ApplyArgs {
        operation: DeploymentOperationArgs::default(),
        file: file.clone(),
        expected_generation: None,
    }));
    let failure = prepare::prepare(&command, &config()).err().unwrap();
    assert_eq!(failure.error["code"], "missing-publication");
    assert!(!failure.request_dispatched);
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(&file).unwrap()).unwrap();
    manifest["spec"]["publication"] =
        serde_json::json!(format!("publication:sha256:{}", "a".repeat(64)));
    fs::write(&file, serde_json::to_vec(&manifest).unwrap()).unwrap();
    for expected_generation in [None, Some(0), Some(u64::MAX)] {
        let command = Command::Deployment(DeploymentCommand::Apply(ApplyArgs {
            operation: DeploymentOperationArgs::default(),
            file: file.clone(),
            expected_generation,
        }));
        let Operation::ApplyDeployment(value) = prepare::prepare(&command, &config()).unwrap()
        else {
            panic!("wrong operation");
        };
        assert_eq!(value.expected_generation, expected_generation);
        assert_eq!(value.deployment.unwrap().generation, 0);
        let command = Command::Deployment(DeploymentCommand::Delete(DeleteArgs {
            operation: DeploymentOperationArgs::default(),
            id: "echo-production".to_owned(),
            expected_generation,
        }));
        let Operation::DeleteDeployment(value) = prepare::prepare(&command, &config()).unwrap()
        else {
            panic!("wrong operation");
        };
        assert_eq!(value.expected_generation, expected_generation);
    }
}

#[test]
fn local_validation_needs_neither_profile_nor_connection_and_rejects_unknown_fields() {
    let files = Files::new();
    let good = files.put(
        "deployment.json",
        include_bytes!("../../../../../examples/echo-contract/deployment.json"),
    );
    assert!(prepare::validate(
        &ValidateCommand::Deployment(FileArgs { file: good }),
        latent_manifest::ManifestValidationProfile::default(),
    )
    .is_ok());
    let bad = files.put(
        "invalid.json",
        br#"{"apiVersion":"latent.dev/v1alpha1","kind":"Deployment","unknown":"secret"}"#,
    );
    assert!(prepare::validate(
        &ValidateCommand::Deployment(FileArgs { file: bad }),
        latent_manifest::ManifestValidationProfile::default(),
    )
    .is_err());
}

#[test]
fn manifest_tenant_mismatch_is_a_local_failure() {
    let files = Files::new();
    let file = files.put(
        "deployment.json",
        include_bytes!("../../../../../examples/echo-contract/deployment.json"),
    );
    let mut cfg = config();
    cfg.tenant = "foreign".to_owned();
    assert!(prepare::prepare(
        &Command::Deployment(DeploymentCommand::Apply(ApplyArgs {
            operation: DeploymentOperationArgs::default(),
            file,
            expected_generation: None
        })),
        &cfg
    )
    .is_err());
}

#[test]
fn publish_preparation_checks_metadata_and_exact_component_digest() {
    let files = Files::new();
    let bytes = b"tiny fake component bytes, never executed";
    let mut manifest = prepare::codec()
        .decode_capsule(include_bytes!(
            "../../../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    manifest.component_digest = content_digest(bytes);
    let manifest_file = files.put(
        "capsule.json",
        &prepare::codec().encode_capsule(&manifest).unwrap(),
    );
    let contracts = files.put(
        "contracts.json",
        include_bytes!("../../../../../examples/echo-contract/contracts.json"),
    );
    let component = files.put("component.wasm", bytes);
    let command = Command::Release(ReleaseCommand::Publish(PublishArgs {
        operation: OptionalReleaseOperation::default(),
        manifest: manifest_file,
        component: component.clone(),
        contracts: contracts.clone(),
    }));
    let Operation::PublishRelease(request) = prepare::prepare(&command, &config()).unwrap() else {
        panic!("wrong operation");
    };
    assert!(request.release.is_none());
    let artifact = request.artifact.unwrap();
    assert_eq!(artifact.component_digest, content_digest(bytes).0);
    assert_eq!(artifact.component_bytes, bytes);
    assert_eq!(artifact.component_media_type, "application/wasm");
    fs::write(&component, b"different").unwrap();
    assert!(prepare::prepare(&command, &config()).is_err());
    fs::write(&component, bytes).unwrap();
    fs::write(&contracts, br#"{"format_version":1,"contracts":[]}"#).unwrap();
    assert!(prepare::prepare(&command, &config()).is_err());
}

#[test]
fn publication_rejects_multiple_stdin_inputs_before_attempting_any_read() {
    let command = Command::Release(ReleaseCommand::Publish(PublishArgs {
        operation: OptionalReleaseOperation::default(),
        manifest: "-".into(),
        component: "-".into(),
        contracts: "missing".into(),
    }));
    assert!(prepare::prepare(&command, &config()).is_err());
}

#[test]
fn one_page_preserves_cursor_and_zero_default_without_followup() {
    let command = Command::Release(ReleaseCommand::List(ServicePageArgs {
        service: Some("examples/echo".to_owned()),
        page_size: 0,
        page_token: Some("opaque-cursor".to_owned()),
    }));
    let Operation::ListReleases(request) = prepare::prepare(&command, &config()).unwrap() else {
        panic!("wrong operation");
    };
    assert_eq!(request.service.as_deref(), Some("examples/echo"));
    let page = request.page.unwrap();
    assert_eq!(page.page_size, 0);
    assert_eq!(page.page_token.as_deref(), Some("opaque-cursor"));
}
