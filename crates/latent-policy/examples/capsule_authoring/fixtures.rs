//! Explicit synthetic trust for real captured Java bytes. This is a package test
//! fixture, not a newly observed Java build or packaged distribution approval.
use super::{inputs, Result, TENANT};
use latent_artifacts::package::{artifact_blob_digest, LayerRole};
use latent_packaging::{
    build_package_with_sbom, decode_package_source, read_package_file, read_package_input,
    PackagingLimits,
};
use latent_signing::{
    decode_build_observation, BuildObservation, ProvenanceLimits, JAVA_CAPSULE_BUILD_TYPE,
};
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fixture {
    schema_version: String,
    evidence_kind: String,
    compiler_source: String,
    compiler_report_digest: String,
    source_archive_digest: String,
    component_digest: String,
    source_snapshot_digest: String,
    companion_digest: String,
    requirements_digest: Option<String>,
    compiler_executed_by_signer: bool,
    packaged_distribution_qualified: bool,
    signed_node_execution_qualified: bool,
    provenance_model: BuildObservation,
}

pub(super) fn load(root: &Path) -> Result<inputs::Build> {
    load_selected(root, "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6", false)
}

pub(super) fn load_current(root: &Path, compiler_source: &str) -> Result<inputs::Build> {
    if compiler_source.len() != 40
        || !compiler_source
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err("explicit current compiler commit required".into());
    }
    load_selected(root, compiler_source, true)
}

fn load_selected(root: &Path, compiler_source: &str, current: bool) -> Result<inputs::Build> {
    let raw = read(root, "fixture-provenance-input.json", 65536)?;
    let fixture: Fixture = serde_json::from_slice(&raw)?;
    check_model(root, &fixture, compiler_source)?;
    if current {
        check_current_report(root, &fixture)?;
    }
    let limits = PackagingLimits::default();
    let source_bytes = read(root, "package-source.json", 65536)?;
    let source = decode_package_source(&source_bytes, limits).map_err(|error| error.message)?;
    let input = read_package_input(root, &source, limits).map_err(|error| error.message)?;
    inputs::verify_package_inputs(&input, &source_bytes, &fixture.provenance_model)?;
    let component = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Component)
        .ok_or("component missing")?;
    if artifact_blob_digest(&component.bytes).as_str() != fixture.component_digest
        || component.bytes.len() as u64 != fixture.provenance_model.component_size
    {
        return Err("original Java component association changed".into());
    }
    check_asset(
        &input,
        "transaction-binding.json",
        "application/vnd.latent.transaction-binding.v1+json",
        &fixture.companion_digest,
    )?;
    if let Some(digest) = &fixture.requirements_digest {
        check_asset(
            &input,
            "deferred-http-requirements.json",
            "application/json",
            digest,
        )?;
    }
    let manifest = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .ok_or("capsule manifest missing")?;
    let manifest: Value = serde_json::from_slice(&manifest.bytes)?;
    let service = manifest["metadata"]["name"]
        .as_str()
        .ok_or("service missing")?
        .to_owned();
    let world = manifest["component"]["world"]
        .as_str()
        .ok_or("world missing")?
        .to_owned();
    if manifest["metadata"]["tenant"] != TENANT
        || world != "examples:transactional-aggregate/service@1.0.0"
    {
        return Err("Java fixture scope changed".into());
    }
    let inventory = inputs::sbom(&input, &fixture.source_snapshot_digest)?;
    let bundle =
        build_package_with_sbom(input, inventory, limits).map_err(|error| error.message)?;
    let deployment = read(root, "deployment.json", 65536)?;
    let declared: Value = serde_json::from_slice(&deployment)?;
    if declared["metadata"]["tenant"] != TENANT
        || declared["spec"]["service"] != service
        || declared["spec"]["release"] != fixture.component_digest
        || declared["spec"]["grants"] != serde_json::json!([])
    {
        return Err("fixture deployment grants or component association changed".into());
    }
    Ok(inputs::Build {
        bundle,
        observation: fixture.provenance_model,
        deployment,
        service,
        world,
        fixture_evidence: Some(raw),
    })
}

fn check_model(root: &Path, fixture: &Fixture, compiler_source: &str) -> Result<()> {
    if fixture.schema_version != "latent.component.signing-fixture-input.v1"
        || fixture.evidence_kind != "synthetic-native-package-trust"
        || fixture.compiler_source != compiler_source
        || fixture.compiler_executed_by_signer
        || fixture.packaged_distribution_qualified
        || fixture.signed_node_execution_qualified
        || fixture.provenance_model.build_type != JAVA_CAPSULE_BUILD_TYPE
        || fixture.provenance_model.started_at != 0
        || fixture.provenance_model.finished_at != 0
        || fixture.provenance_model.component_digest != fixture.component_digest
        || fixture.provenance_model.source.snapshot_digest != fixture.source_snapshot_digest
    {
        return Err(
            "explicit unsigned fixture model required; compiler execution is not inferred".into(),
        );
    }
    decode_build_observation(
        &serde_json::to_vec(&fixture.provenance_model)?,
        ProvenanceLimits::default(),
    )?;
    for (name, digest, bound) in [
        (
            "source-inputs.json",
            &fixture.source_snapshot_digest,
            4 * 1024 * 1024,
        ),
        (
            "source.tar.gz",
            &fixture.source_archive_digest,
            32 * 1024 * 1024,
        ),
        (
            "compiler-report.json",
            &fixture.compiler_report_digest,
            262144,
        ),
    ] {
        if artifact_blob_digest(&read(root, name, bound)?).as_str() != digest {
            return Err("original compiler fixture material changed".into());
        }
    }
    Ok(())
}

fn check_current_report(root: &Path, fixture: &Fixture) -> Result<()> {
    let report: Value = serde_json::from_slice(&read(root, "compiler-report.json", 262144)?)?;
    check_report(&report, fixture)?;
    if report["recipeDigest"]
        != artifact_blob_digest(&read(root, "recipe-inputs.json", 4 * 1024 * 1024)?).as_str()
    {
        return Err("current compiler recipe changed".into());
    }
    let closure = read(root, "compiler-inputs.json", 4 * 1024 * 1024)?;
    let material = fixture
        .provenance_model
        .materials
        .iter()
        .find(|material| material.name == "compiler-closure")
        .ok_or("current compiler closure missing")?;
    if material.digest != artifact_blob_digest(&closure).as_str()
        || material.size != closure.len() as u64
    {
        return Err("current compiler closure changed".into());
    }
    Ok(())
}

fn check_report(report: &Value, fixture: &Fixture) -> Result<()> {
    if report["schemaVersion"] != "latent.transaction-guest.compiler.v1"
        || report["evidenceKind"] != "authored-component-compiler"
        || report["language"] != "java"
        || report["world"] != "examples:transactional-aggregate/service@1.0.0"
        || report["sourceRevision"] != fixture.compiler_source
        || report["status"] != "compiled"
        || report["compiled"] != true
        || report["workingTreeChanged"] != false
        || report["signedNodeExecutionQualified"] != false
        || report["admissionRejectionQualified"] != false
        || report["componentDigest"] != fixture.component_digest
        || report["componentBytes"] != fixture.provenance_model.component_size
        || report["sourceDigest"] != fixture.source_snapshot_digest
        || report["sourceArchiveDigest"] != fixture.source_archive_digest
        || report["companionDigest"] != fixture.companion_digest
        || !matches!(
            report["variant"].as_str(),
            Some(
                "aggregate"
                    | "put-once-legacy-v1"
                    | "put-once-compatible-v2"
                    | "put-once-writer-v2"
                    | "put-once-diagnostics"
            )
        )
    {
        return Err(
            "exact current Java capture required; runtime qualification is separate".into(),
        );
    }
    let imports = report["actualImports"]
        .as_array()
        .ok_or("current imports missing")?;
    if imports.len() > 4
        || ![
            "latent:state/key-value@0.2.0",
            "latent:intents/staging@0.1.0",
        ]
        .iter()
        .all(|name| imports.iter().filter(|entry| *entry == name).count() == 1)
        || imports.iter().any(|entry| {
            !matches!(
                entry.as_str(),
                Some(
                    "latent:state/key-value@0.2.0"
                        | "latent:intents/staging@0.1.0"
                        | "latent:clock/monotonic@0.1.0"
                        | "latent:clock/wall@0.1.0"
                )
            )
        })
    {
        return Err("current Java transaction import profile changed".into());
    }
    let commands = report["details"]["commands"]
        .as_array()
        .ok_or("compiler stages missing")?;
    if commands.is_empty()
        || commands.len() > 64
        || commands.iter().any(|command| command["exitCode"] != 0)
        || ![
            "java-to-c",
            "c-to-wasm",
            "component-new",
            "component-validate",
            "compiled-wit",
        ]
        .iter()
        .all(|stage| commands.iter().any(|command| command["stage"] == *stage))
    {
        return Err("successful current Java compiler stages required".into());
    }
    if fixture
        .requirements_digest
        .as_ref()
        .is_some_and(|digest| report["deferredHttpRequirementsDigest"] != *digest)
    {
        return Err("current Java requirements association changed".into());
    }
    Ok(())
}

fn check_asset(
    input: &latent_packaging::PackageInput,
    name: &str,
    media: &str,
    digest: &str,
) -> Result<()> {
    let asset = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Asset && layer.path == name)
        .ok_or("original signed fixture asset missing")?;
    if asset.media_type != media || artifact_blob_digest(&asset.bytes).as_str() != digest {
        return Err("original signed fixture asset digest changed".into());
    }
    Ok(())
}
fn read(root: &Path, name: &str, maximum: u64) -> Result<Vec<u8>> {
    read_package_file(root, name, maximum).map_err(|error| error.message.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // Synthetic material is a validator oracle only; no compiler or node ran.
    fn materials() -> (Fixture, Value) {
        let hash = |byte: char| format!("sha256:{}", byte.to_string().repeat(64));
        let component = hash('1');
        let snapshot = hash('2');
        let archive = hash('3');
        let companion = hash('4');
        let source = "a".repeat(40);
        let commands = [
            "java-to-c",
            "c-to-wasm",
            "component-new",
            "component-validate",
            "compiled-wit",
        ]
        .map(|stage| json!({"stage":stage,"exitCode":0}));
        let fixture: Fixture = serde_json::from_value(json!({
            "schemaVersion":"latent.component.signing-fixture-input.v1",
            "evidenceKind":"synthetic-native-package-trust", "compilerSource":source,
            "compilerReportDigest":hash('5'), "sourceArchiveDigest":archive,
            "componentDigest":component, "sourceSnapshotDigest":snapshot,
            "companionDigest":companion, "requirementsDigest":null,
            "compilerExecutedBySigner":false, "packagedDistributionQualified":false,
            "signedNodeExecutionQualified":false,
            "provenanceModel":{
                "formatVersion":1, "buildType":JAVA_CAPSULE_BUILD_TYPE,
                "source":{"repository":"https://github.com/KirilsTurkins/latent-service-fabric",
                    "revision":"2".repeat(64), "snapshotDigest":snapshot,
                    "repositoryTrust":"operator-asserted", "capture":"explicit-input-files"},
                "componentDigest":component, "componentSize":123, "materials":[],
                "parameters":{"compiler":"teavm-c", "entryPoint":"dev.latent.app.Capsule",
                    "target":"wasm32-wasip1", "bindings":"lsf-java-wit-v1",
                    "optimization":"O2", "javaHeapBytes":4194304},
                "startedAt":0, "finishedAt":0, "reproducibility":"not-checked",
                "hermetic":false, "dependencyCompleteness":"declared-inputs-incomplete"}
        }))
        .unwrap();
        let report = json!({
            "schemaVersion":"latent.transaction-guest.compiler.v1",
            "evidenceKind":"authored-component-compiler", "language":"java",
            "world":"examples:transactional-aggregate/service@1.0.0",
            "sourceRevision":source, "status":"compiled", "compiled":true,
            "workingTreeChanged":false, "signedNodeExecutionQualified":false,
            "admissionRejectionQualified":false, "componentDigest":component,
            "componentBytes":123, "sourceDigest":snapshot, "sourceArchiveDigest":archive,
            "companionDigest":companion, "variant":"aggregate",
            "actualImports":["latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"],
            "details":{"commands":commands}
        });
        (fixture, report)
    }

    #[test]
    fn current_fixture_retains_explicit_source_and_report_associations() {
        let (fixture, report) = materials();
        check_report(&report, &fixture).unwrap();
        for field in [
            "sourceRevision",
            "componentDigest",
            "sourceDigest",
            "sourceArchiveDigest",
            "companionDigest",
        ] {
            let mut changed = report.clone();
            changed[field] = json!("changed");
            assert!(check_report(&changed, &fixture).is_err(), "{field}");
        }
        assert!(load_current(Path::new("not-read"), "guessed-source").is_err());
    }

    #[test]
    fn current_fixture_refuses_missing_failed_stages_and_host_or_execution_claims() {
        let (fixture, report) = materials();
        for (field, value) in [
            ("signedNodeExecutionQualified", json!(true)),
            ("workingTreeChanged", json!(true)),
            ("variant", json!("forbidden-http")),
        ] {
            let mut changed = report.clone();
            changed[field] = value;
            assert!(check_report(&changed, &fixture).is_err(), "{field}");
        }
        let mut failed = report.clone();
        failed["details"]["commands"][0]["exitCode"] = json!(1);
        assert!(check_report(&failed, &fixture).is_err());
        let mut missing = report.clone();
        missing["details"]["commands"].as_array_mut().unwrap().pop();
        assert!(check_report(&missing, &fixture).is_err());
        let mut foreign = report.clone();
        foreign["actualImports"]
            .as_array_mut()
            .unwrap()
            .push(json!("latent:http/client@0.2.0"));
        assert!(check_report(&foreign, &fixture).is_err());
        let (mut required, mut reported) = materials();
        required.requirements_digest = Some(format!("sha256:{}", "6".repeat(64)));
        assert!(check_report(&reported, &required).is_err());
        reported["deferredHttpRequirementsDigest"] = json!(required.requirements_digest);
        check_report(&reported, &required).unwrap();
    }
}
