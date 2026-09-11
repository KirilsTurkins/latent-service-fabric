use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationClock, ContractId, PlatformErrorCode, ReleaseDigest};
use latent_executor::{ExecutionBackend, ExecutionCleanup};
use latent_manifest::ContractImport;
use latent_wasmtime::WasmtimeComponentEngineFactory;
use serde_json::json;
use sha2::{Digest, Sha256};

use super::support::*;

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn missing_clock_grant_is_rejected_before_store_creation() {
    let clock = Arc::new(ManualClock::new());
    let (backend, prepared) = prepared(config(), services(&clock)).await;
    let cancellation = Cancellation::new("missing-clock", &budget(), clock.sample());
    let mut request = request(&prepared, &cancellation, "snapshot", &json!([]));
    request
        .imports
        .retain(|import| import.contract != IMPORTS[3]);
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        backend.invoke_contained(request, &cancellation),
    )
    .await
    .expect("missing grant watchdog");
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component and denied-import fixture"]
async fn forbidden_import_families_are_unavailable_even_when_manifest_declares_them() {
    let original = artifact();
    let path = PathBuf::from(std::env::var_os("LSF_CAPABILITIES_COMPONENT").expect("fixture path"));
    let factory = WasmtimeComponentEngineFactory::new(config()).expect("factory");
    let backend = factory.create_backend_instance();
    let cases = include_str!("fixtures/denied-imports.txt");
    assert_eq!(cases.lines().count(), 9);
    for line in cases.lines() {
        let (family, contract) = line.split_once(' ').expect("family and import name");
        let mut artifact = original.clone();
        artifact.component_bytes =
            std::fs::read(path.with_file_name(format!("denied-{family}.wasm")))
                .expect("denied import fixture");
        artifact.descriptor.release_digest = ReleaseDigest(format!(
            "sha256:{:x}",
            Sha256::digest(&artifact.component_bytes)
        ));
        artifact.descriptor.size_bytes =
            u64::try_from(artifact.component_bytes.len()).expect("fixture size");
        artifact.manifest.component_digest = artifact.descriptor.release_digest.clone();
        artifact.manifest.imports = vec![ContractImport {
            contract: ContractId(contract.to_owned()),
            optional: false,
        }];
        let error = backend
            .prepare(
                &artifact,
                &factory.preparation_key(artifact.descriptor.release_digest.clone()),
            )
            .await
            .expect_err("a forbidden import must not receive ambient authority");
        assert_eq!(
            error.code,
            PlatformErrorCode::IncompatibleContract,
            "{family}"
        );
        assert_eq!(
            error.message, "component imports an unsupported host capability",
            "{family}"
        );
    }
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
}
