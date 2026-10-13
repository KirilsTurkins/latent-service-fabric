//! One separately captured early HTTP fixture, without execution authority.
use std::{ffi::OsString, path::Path};

use serde_json::Value;

use super::current_java::{absent, digest_matches, model_material, pinned, read, require};
use super::{inputs, sign_checked, Result};

const SOURCE: &str = "47e4e60778d7fdd033d5f1d6c05595752713c971";
const VARIANT: &str = "forbidden-http-before-stage";
const WORLD: &str = "examples:transactional-aggregate/service@1.0.0";
const SERVICE: &str = "examples/transaction-java-forbidden-http-before-stage";
const PINS: &[u8] = include_bytes!(
    "../../../../docs/development/phase4-handoffs/2026-10-12/pr970-early-http-compiler-evidence.json"
);

fn no_effect_authority(root: &Path) -> Result<()> {
    for name in [
        "java-current-http-profile.json",
        "deferred-http-requirements.json",
        "application-schema-inputs.json",
    ] {
        absent(root, name)?;
    }
    Ok(())
}

#[expect(
    clippy::too_many_lines,
    reason = "One closed captured source validates every material and original ceiling before ephemeral signing"
)]
fn load(root: &Path) -> Result<inputs::Build> {
    require(
        root.is_absolute(),
        "early HTTP fixture needs absolute input",
    )?;
    no_effect_authority(root)?;
    let capture: Value = serde_json::from_slice(PINS)?;
    require(
        capture["sourceCommit"] == SOURCE && capture["variant"] == VARIANT,
        "early HTTP captured source owner mismatch",
    )?;
    let pins = &capture["materials"];
    let report_raw = pinned(root, "compiler-report.json", &pins["report"], 262_144)?;
    let report: Value = serde_json::from_slice(&report_raw)?;
    require(
        report["sourceRevision"] == SOURCE
            && report["variant"] == VARIANT
            && report["language"] == "java"
            && report["world"] == WORLD
            && report["status"] == "compiled"
            && report["compiled"] == true
            && report["workingTreeChanged"] == false
            && report["signedNodeExecutionQualified"] == false
            && report["admissionRejectionQualified"] == false
            && report["immediateHttpDenialQualified"] == false
            && report["postStageRollbackQualified"] == false,
        "early HTTP requires exact clean completed compiler custody",
    )?;
    let component = pinned(root, "component.wasm", &pins["component"], 32 * 1024 * 1024)?;
    require(
        component.starts_with(b"\0asm\x0d\0\x01\0"),
        "early HTTP component header mismatch",
    )?;
    let source = pinned(
        root,
        "source-inputs.json",
        &pins["sourceInputs"],
        4 * 1024 * 1024,
    )?;
    let recipe = pinned(
        root,
        "recipe-inputs.json",
        &pins["recipeInputs"],
        4 * 1024 * 1024,
    )?;
    let closure = pinned(
        root,
        "compiler-inputs.json",
        &pins["compilerInputs"],
        4 * 1024 * 1024,
    )?;
    let archive = pinned(
        root,
        "source.tar.gz",
        &pins["sourceArchive"],
        32 * 1024 * 1024,
    )?;
    let companion = pinned(
        root,
        "transaction-binding.json",
        &pins["companion"],
        262_144,
    )?;
    pinned(
        root,
        "src/dev/latent/app/Capsule.java",
        &pins["capsuleSource"],
        262_144,
    )?;
    let declaration_raw = pinned(
        root,
        "java-early-http-denial-input.json",
        &pins["declaration"],
        8192,
    )?;
    let declaration: Value = serde_json::from_slice(&declaration_raw)?;
    require(
        declaration["schemaVersion"] == "latent.java.early-http-denial-input.v1"
            && declaration["variant"] == VARIANT
            && declaration["sourceDigest"] == pins["capsuleSource"]["sha256"]
            && declaration["companionDigest"] == pins["companion"]["sha256"]
            && declaration["callBefore"]
                == serde_json::json!(["state-get", "state-put", "intent-stage"])
            && declaration["expectedTypedError"] == "permission-denied"
            && declaration["expectedBusinessResult"] == "rejected"
            && [
                "componentCompiled",
                "signedExecutionQualified",
                "immediateHttpDenialQualified",
                "postStageRollbackQualified",
            ]
            .iter()
            .all(|field| declaration[*field] == false),
        "early HTTP fixture cannot infer execution from authored inputs",
    )?;
    let fixture_raw = read(root, "fixture-provenance-input.json", 65_536)?;
    let fixture: Value = serde_json::from_slice(&fixture_raw)?;
    require(
        fixture["schemaVersion"] == "latent.component.signing-fixture-input.v1"
            && fixture["evidenceKind"] == "synthetic-native-package-trust"
            && fixture["compilerSource"] == SOURCE
            && fixture["requirementsDigest"].is_null()
            && fixture["compilerExecutedBySigner"] == false
            && fixture["packagedDistributionQualified"] == false
            && fixture["signedNodeExecutionQualified"] == false,
        "early HTTP fixture must keep synthetic trust and original claims",
    )?;
    for (raw, field) in [
        (&report_raw, "compilerReportDigest"),
        (&archive, "sourceArchiveDigest"),
        (&source, "sourceSnapshotDigest"),
        (&component, "componentDigest"),
        (&companion, "companionDigest"),
    ] {
        digest_matches(raw, &fixture[field])?;
    }
    let manifest: Value = serde_json::from_slice(&read(root, "capsule.json", 65_536)?)?;
    require(
        manifest["execution"]["limits"] == capture["limits"]
            && manifest["execution"]["threading"] == "single-threaded"
            && manifest["execution"]["snapshotEligible"] == false
            && manifest["execution"]["fusionEligible"] == false,
        "early HTTP fixture must retain original invocation ceilings",
    )?;
    let imports = manifest["imports"]
        .as_array()
        .ok_or("early HTTP imports missing")?;
    let expected = capture["actualImports"]
        .as_array()
        .ok_or("early HTTP captured imports missing")?;
    require(
        imports.len() == expected.len()
            && expected.iter().all(|contract| {
                imports
                    .iter()
                    .filter(|entry| entry["contract"] == *contract && entry["optional"] == false)
                    .count()
                    == 1
            }),
        "early HTTP original imports must remain exact",
    )?;
    let model = &fixture["provenanceModel"];
    for (name, raw) in [
        ("source-snapshot", source),
        ("build-recipe", recipe),
        ("compiler-closure", closure),
    ] {
        model_material(model, name, &raw)?;
    }
    model_material(
        model,
        "package-inputs",
        &read(root, "package-inputs.json", 4 * 1024 * 1024)?,
    )?;
    require(
        model["componentDigest"] == pins["component"]["sha256"]
            && model["componentSize"] == pins["component"]["bytes"]
            && model["source"]["repository"]
                == "https://github.com/KirilsTurkins/latent-service-fabric"
            && model["source"]["snapshotDigest"] == pins["sourceInputs"]["sha256"]
            && model["source"]["repositoryTrust"] == "operator-asserted"
            && model["source"]["capture"] == "explicit-input-files"
            && model["parameters"]
                == serde_json::json!({"compiler":"teavm-c", "entryPoint":"dev.latent.app.Capsule",
                "target":"wasm32-wasip1", "bindings":"lsf-java-wit-v1", "optimization":"O2", "javaHeapBytes":4_194_304})
            && model["reproducibility"] == "not-checked"
            && model["hermetic"] == false
            && model["dependencyCompleteness"] == "declared-inputs-incomplete",
        "early HTTP provenance cannot exceed captured custody",
    )?;
    let build = inputs::load_current_java(root, &serde_json::to_vec(model)?)?;
    require(
        build.bundle.layout().config().name == format!("java718-{VARIANT}")
            && build.world == WORLD
            && build.service == SERVICE,
        "early HTTP fixture package, world or distinct service mismatch",
    )?;
    Ok(build)
}

pub(crate) fn sign_early_http(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    require(
        compiler_source == SOURCE && paths.len() == 1,
        "early HTTP signing requires its one exact separate captured input",
    )?;
    let build = load(Path::new(&paths[0]))?;
    sign_checked(output, vec![build], false, Some(SOURCE))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn separate_early_input_rejects_other_source_and_extra_packages_before_output() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("must-not-exist");
        assert!(sign_early_http(&output, "9bae83952d9513c965a88d375b2a533916a98473", &[]).is_err());
        assert!(sign_early_http(&output, SOURCE, &[]).is_err());
        assert!(
            sign_early_http(&output, SOURCE, &[root.path().into(), root.path().into()]).is_err()
        );
        assert!(!output.exists());
    }

    #[cfg(unix)]
    #[test]
    fn early_input_cannot_gain_positive_effect_authority_through_dangling_marker() {
        let root = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(
            "missing",
            root.path().join("java-current-http-profile.json"),
        )
        .unwrap();
        assert!(no_effect_authority(root.path()).is_err());
    }
}
