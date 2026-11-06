//! One separately captured early HTTP fixture, without execution authority.
use std::{ffi::OsString, path::Path};

use serde_json::Value;

use super::current_java::{absent, digest_matches, model_material, pinned, read, require};
use super::{inputs, sign_checked, Result};

const SOURCE: &str = "47e4e60778d7fdd033d5f1d6c05595752713c971";
const NOVEMBER_SOURCE: &str = "fccc27dbc52f2dd0db137078f8e7e436a41ebe8a";
const VARIANT: &str = "forbidden-http-before-stage";
const WORLD: &str = "examples:transactional-aggregate/service@1.0.0";
const SERVICE: &str = "examples/transaction-java-forbidden-http-before-stage";
const CHILD_SOURCE: &str = "5f99649cd3b583d4a855c7c3b07ed3167419b866";
const CHILD_VARIANT: &str = "forbidden-child";
const CHILD_SERVICE: &str = "examples/transaction-java-forbidden-child";
const CHILD_PINS: &[u8] =
    include_bytes!("../../../../docs/testing/evidence/java-acceptance-inputs-5f-2026-11-05.json");
const PINS: &[u8] = include_bytes!(
    "../../../../docs/development/phase4-handoffs/2026-10-12/pr970-early-http-compiler-evidence.json"
);
const REBUILT_PINS: &[u8] = include_bytes!(
    "../../../../docs/testing/evidence/java-early-http-rebuilt-capture-2026-10-13.json"
);
const RECONSTRUCTED_PINS: &[u8] = include_bytes!(
    "../../../../docs/testing/evidence/java-early-http-reconstructed-capture-2026-10-15.json"
);
const NOVEMBER_PINS: &[u8] =
    include_bytes!("../../../../docs/testing/evidence/java-early-http-capture-2026-11-04.json");

#[cfg(test)]
mod reconstructed_tests;

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

fn load(root: &Path, selected_pins: &[u8], expected_source: &str) -> Result<inputs::Build> {
    load_selected(root, selected_pins, expected_source, false)
}

#[expect(
    clippy::too_many_lines,
    reason = "Complete exact fixture custody precedes signing"
)]
fn load_selected(
    root: &Path,
    selected_pins: &[u8],
    expected_source: &str,
    child: bool,
) -> Result<inputs::Build> {
    require(
        root.is_absolute(),
        "early HTTP fixture needs absolute input",
    )?;
    no_effect_authority(root)?;
    let packet: Value = serde_json::from_slice(selected_pins)?;
    let variant = if child { CHILD_VARIANT } else { VARIANT };
    let service = if child { CHILD_SERVICE } else { SERVICE };
    let capture = if child {
        &packet["variants"][CHILD_VARIANT]
    } else {
        &packet
    };
    require(
        packet["sourceCommit"] == expected_source && (child || capture["variant"] == variant),
        "early HTTP captured source owner mismatch",
    )?;
    let pins = &capture["materials"];
    let report_raw = pinned(root, "compiler-report.json", &pins["report"], 262_144)?;
    let report: Value = serde_json::from_slice(&report_raw)?;
    require(
        report["sourceRevision"] == expected_source
            && report["variant"] == variant
            && report["language"] == "java"
            && report["world"] == WORLD
            && report["status"] == "compiled"
            && report["compiled"] == true
            && report["workingTreeChanged"] == false
            && report["signedNodeExecutionQualified"] == false
            && report["admissionRejectionQualified"] == false
            && (child
                || (report["immediateHttpDenialQualified"] == false
                    && report["postStageRollbackQualified"] == false)),
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
    let capsule_source = pinned(
        root,
        "src/dev/latent/app/Capsule.java",
        &pins["capsuleSource"],
        262_144,
    )?;
    if child {
        let text = std::str::from_utf8(&capsule_source)?;
        require(text.contains("try (var command = State.acquireCommand().value()) {")
            && text.contains("Bindings.LatentServiceInvoke.call(")
            && text.contains("Bindings.LatentServiceInvokePlatformErrorCode.PermissionDenied")
            && text.contains("return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected)"),
            "child fixture must retain the typed strict-command call")?;
    } else {
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
    }
    let fixture_raw = read(root, "fixture-provenance-input.json", 65_536)?;
    let fixture: Value = serde_json::from_slice(&fixture_raw)?;
    require(
        fixture["schemaVersion"] == "latent.component.signing-fixture-input.v1"
            && fixture["evidenceKind"] == "synthetic-native-package-trust"
            && fixture["compilerSource"] == expected_source
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
        build.bundle.layout().config().name == format!("java718-{variant}")
            && build.world == WORLD
            && build.service == service,
        "early HTTP fixture package, world or distinct service mismatch",
    )?;
    Ok(build)
}

pub(crate) fn sign_child(output: &Path, compiler_source: &str, paths: &[OsString]) -> Result<()> {
    require(
        compiler_source == CHILD_SOURCE && paths.len() == 1,
        "child signing requires its one exact captured input",
    )?;
    let build = load_selected(Path::new(&paths[0]), CHILD_PINS, CHILD_SOURCE, true)?;
    sign_checked(output, vec![build], false, Some(CHILD_SOURCE))
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
    let build = load(Path::new(&paths[0]), PINS, SOURCE)?;
    sign_checked(output, vec![build], false, Some(SOURCE))
}

pub(crate) fn sign_rebuilt_early_http(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    require(
        compiler_source == SOURCE && paths.len() == 1,
        "rebuilt early HTTP signing requires one exact captured input",
    )?;
    let build = load(Path::new(&paths[0]), REBUILT_PINS, SOURCE)?;
    sign_checked(output, vec![build], false, Some(SOURCE))
}

pub(crate) fn sign_reconstructed_early_http(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    require(
        compiler_source == SOURCE && paths.len() == 1,
        "reconstructed early HTTP signing requires one exact captured input",
    )?;
    let build = load(Path::new(&paths[0]), RECONSTRUCTED_PINS, SOURCE)?;
    sign_checked(output, vec![build], false, Some(SOURCE))
}

pub(crate) fn sign_november_early_http(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    require(
        compiler_source == NOVEMBER_SOURCE && paths.len() == 1,
        "November early HTTP signing requires its exact captured input",
    )?;
    let build = load(Path::new(&paths[0]), NOVEMBER_PINS, NOVEMBER_SOURCE)?;
    sign_checked(output, vec![build], false, Some(NOVEMBER_SOURCE))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn child_signing_requires_its_exact_source_and_complete_input() {
        let output = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let path = root.path().as_os_str().to_owned();
        assert!(sign_child(output.path(), SOURCE, std::slice::from_ref(&path)).is_err());
        assert!(sign_child(output.path(), CHILD_SOURCE, &[]).is_err());
        assert!(sign_child(output.path(), CHILD_SOURCE, &[path]).is_err());
    }

    #[test]
    fn rebuilt_capture_changes_only_report_and_compiler_closure_custody() {
        let original: Value = serde_json::from_slice(PINS).unwrap();
        let rebuilt: Value = serde_json::from_slice(REBUILT_PINS).unwrap();
        assert_eq!(original["sourceCommit"], rebuilt["sourceCommit"]);
        for key in [
            "component",
            "sourceInputs",
            "recipeInputs",
            "sourceArchive",
            "capsuleSource",
            "companion",
        ] {
            assert_eq!(original["materials"][key], rebuilt["materials"][key]);
        }
        for key in ["report", "compilerInputs"] {
            assert_ne!(original["materials"][key], rebuilt["materials"][key]);
        }
        assert_eq!(rebuilt["signedNodeExecutionQualified"], false);
        assert_eq!(rebuilt["issueClosure"], false);
    }

    #[test]
    fn rebuilt_mode_refuses_historical_report_before_creating_output() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("must-not-exist");
        assert!(sign_rebuilt_early_http(&output, "wrong", &[root.path().into()]).is_err());
        assert!(sign_rebuilt_early_http(&output, SOURCE, &[]).is_err());
        assert!(sign_november_early_http(&output, SOURCE, &[root.path().into()]).is_err());
        assert!(sign_november_early_http(&output, NOVEMBER_SOURCE, &[root.path().into()]).is_err());
        assert!(!output.exists());
    }

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
