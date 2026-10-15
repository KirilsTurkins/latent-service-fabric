//! Closed captured inputs and explicit synthetic trust, never compiler execution.
mod native_memory;
pub(crate) use native_memory::sign_native_memory_current_java;
mod reconstructed;
pub(crate) use reconstructed::sign_reconstructed_current_java;

use std::{collections::BTreeSet, ffi::OsString, path::Path};

use latent_artifacts::package::artifact_blob_digest;
use latent_packaging::read_package_file;
use serde_json::Value;

use super::{inputs, sign_checked, Result};

const SOURCE: &str = "9bae83952d9513c965a88d375b2a533916a98473";
const WORLD: &str = "examples:transactional-aggregate/service@1.0.0";
const SERVICE: &str = "examples/transaction-java-aggregate";
const PROFILE: &str =
    "qualified-http-v1:96de426fb7aebd66c97033631e9aec1f85d4eac11f581637e67b7f25239bd161";
const FRESH_HTTP_PROFILE: &str =
    "qualified-http-v1:74c19c60dccdecdca0b94eb8c88776516aa77c261b21dc978dab9793f9600cc5";
const NAMES: [&str; 5] = [
    "aggregate",
    "put-once-legacy-v1",
    "put-once-compatible-v2",
    "put-once-writer-v2",
    "put-once-diagnostics",
];
const WITH_NEGATIVE: [&str; 6] = [
    "aggregate",
    "put-once-legacy-v1",
    "put-once-compatible-v2",
    "put-once-writer-v2",
    "put-once-diagnostics",
    "forbidden-http",
];
const PINS: &[u8] = include_bytes!(
    "../../../../docs/development/phase4-handoffs/2026-10-12/pr970-current-post-evidence.json"
);
const REBUILT_PINS: &[u8] = include_bytes!(
    "../../../../docs/testing/evidence/java-current-rebuilt-capture-2026-10-13.json"
);
const FRESH_HTTP_PINS: &[u8] = include_bytes!(
    "../../../../docs/testing/evidence/java-current-fresh-http-capture-2026-10-13.json"
);

pub(super) fn read(root: &Path, name: &str, maximum: u64) -> Result<Vec<u8>> {
    read_package_file(root, name, maximum).map_err(|error| error.message.into())
}

pub(super) fn require(condition: bool, reason: &'static str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(reason.into())
    }
}

pub(super) fn digest_matches(raw: &[u8], expected: &Value) -> Result<()> {
    require(
        expected.as_str() == Some(artifact_blob_digest(raw).as_str()),
        "current Java fixture material digest mismatch",
    )
}

pub(super) fn pinned(root: &Path, path: &str, identity: &Value, maximum: u64) -> Result<Vec<u8>> {
    let raw = read(root, path, maximum)?;
    digest_matches(&raw, &identity["sha256"])?;
    require(
        identity["bytes"].as_u64() == Some(raw.len() as u64),
        "current Java fixture material size mismatch",
    )?;
    Ok(raw)
}

pub(super) fn model_material(model: &Value, name: &str, raw: &[u8]) -> Result<()> {
    let rows = model["materials"]
        .as_array()
        .ok_or("current Java material list missing")?;
    let selected = rows
        .iter()
        .filter(|row| row["name"] == name)
        .collect::<Vec<_>>();
    require(
        selected.len() == 1,
        "current Java fixture material owner missing or duplicated",
    )?;
    digest_matches(raw, &selected[0]["digest"])?;
    require(
        selected[0]["size"].as_u64() == Some(raw.len() as u64),
        "current Java fixture material association mismatch",
    )
}

fn load(
    root: &Path,
    captures: &Value,
    selected_names: &[&str],
    expected_profile: &str,
    expected_source: &str,
) -> Result<(String, inputs::Build)> {
    require(
        root.is_absolute(),
        "current Java fixture inputs must be absolute",
    )?;
    let report_raw = read(root, "compiler-report.json", 262_144)?;
    let report: Value = serde_json::from_slice(&report_raw)?;
    let name = report["variant"]
        .as_str()
        .ok_or("current Java fixture variant missing")?;
    require(
        selected_names.contains(&name),
        "current Java fixture variant is not approved for signing",
    )?;
    let pin = &captures["variants"][name]["materials"];
    digest_matches(&report_raw, &pin["report"]["sha256"])?;
    require(
        pin["report"]["bytes"].as_u64() == Some(report_raw.len() as u64)
            && report["language"] == "java"
            && report["world"] == WORLD
            && report["sourceRevision"] == expected_source
            && report["workingTreeChanged"] == false
            && report["status"] == "compiled"
            && report["compiled"] == true
            && report["signedNodeExecutionQualified"] == false
            && report["admissionRejectionQualified"] == false,
        "current Java fixture requires the exact clean completed compiler report",
    )?;
    let component = pinned(root, "component.wasm", &pin["component"], 32 * 1024 * 1024)?;
    require(
        component.starts_with(b"\0asm\x0d\0\x01\0"),
        "current Java fixture component header mismatch",
    )?;
    let source = pinned(
        root,
        "source-inputs.json",
        &pin["sourceInputs"],
        4 * 1024 * 1024,
    )?;
    let recipe = pinned(
        root,
        "recipe-inputs.json",
        &pin["recipeInputs"],
        4 * 1024 * 1024,
    )?;
    let closure = pinned(
        root,
        "compiler-inputs.json",
        &pin["compilerInputs"],
        4 * 1024 * 1024,
    )?;
    let companion = pinned(root, "transaction-binding.json", &pin["companion"], 262_144)?;
    let archive = read(root, "source.tar.gz", 32 * 1024 * 1024)?;
    digest_matches(&archive, &report["sourceArchiveDigest"])?;
    if name == "forbidden-http" {
        pinned(
            root,
            "src/dev/latent/app/Capsule.java",
            &pin["capsuleSource"],
            262_144,
        )?;
        for path in [
            "java-current-http-profile.json",
            "deferred-http-requirements.json",
            "application-schema-inputs.json",
        ] {
            absent(root, path)?;
        }
        require(report["nativeEffectOperation"].is_null() && report["nativeEffectProfile"].is_null()
            && report["currentHttpProfileInputDigest"].is_null(),
            "negative Java fixture cannot acquire a current HTTP marker or native effect requirement")?;
    } else if name != "aggregate" {
        pinned(
            root,
            "src/dev/latent/app/Capsule.java",
            &pin["capsuleSource"],
            262_144,
        )?;
        let marker = pinned(
            root,
            "java-current-http-profile.json",
            &pin["currentHttpMarker"],
            8192,
        )?;
        let marker: Value = serde_json::from_slice(&marker)?;
        require(
            marker["schemaVersion"] == "latent.java.current-http-source-input.v1"
                && marker["idempotencyProfile"] == expected_profile
                && report["nativeEffectOperation"] == "http"
                && report["nativeEffectProfile"] == "current-v2-http",
            "current Java fixture HTTP marker mismatch",
        )?;
        pinned(
            root,
            "deferred-http-requirements.json",
            &pin["requirements"],
            8192,
        )?;
        pinned(
            root,
            "application-schema-inputs.json",
            &pin["applicationSchemaInputs"],
            8192,
        )?;
    }
    let fixture_raw = read(root, "fixture-provenance-input.json", 65536)?;
    let fixture: Value = serde_json::from_slice(&fixture_raw)?;
    require(
        fixture["schemaVersion"] == "latent.component.signing-fixture-input.v1"
            && fixture["evidenceKind"] == "synthetic-native-package-trust"
            && fixture["compilerSource"] == expected_source
            && fixture["compilerExecutedBySigner"] == false
            && fixture["packagedDistributionQualified"] == false
            && fixture["signedNodeExecutionQualified"] == false,
        "current Java fixture must declare synthetic trust without execution claims",
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
    if matches!(name, "aggregate" | "forbidden-http") {
        require(
            fixture["requirementsDigest"].is_null(),
            "non-HTTP-effect fixture must not add an effect requirement",
        )?;
    } else {
        require(
            fixture["requirementsDigest"] == pin["requirements"]["sha256"],
            "current Java fixture effect requirement association mismatch",
        )?;
    }
    let model = &fixture["provenanceModel"];
    let manifest: Value = serde_json::from_slice(&read(root, "capsule.json", 65536)?)?;
    let expected_limits = serde_json::json!({"cpuFuel":1_000_000_000_u64,"memoryBytes":67_108_864_u64,
        "wallTimeLimitMillis":120_000,"childCalls":0,"outboundRequests":0,"stateReadBytes":4_194_304,
        "stateWriteBytes":2_097_152,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0,
        "effectCount":if matches!(name, "aggregate" | "forbidden-http") {32} else {1}});
    require(
        manifest["execution"]["limits"] == expected_limits
            && manifest["execution"]["threading"] == "single-threaded"
            && manifest["execution"]["snapshotEligible"] == false
            && manifest["execution"]["fusionEligible"] == false,
        "current Java fixture must retain original invocation bounds",
    )?;
    if name == "forbidden-http" {
        let imports = manifest["imports"]
            .as_array()
            .ok_or("negative Java fixture imports missing")?;
        for contract in [
            "latent:http/client@0.2.0",
            "latent:state/key-value@0.2.0",
            "latent:intents/staging@0.1.0",
        ] {
            require(
                imports
                    .iter()
                    .filter(|entry| entry["contract"] == contract && entry["optional"] == false)
                    .count()
                    == 1,
                "negative Java fixture must retain each original HTTP/state/intent import",
            )?;
        }
    }
    model_material(model, "source-snapshot", &source)?;
    model_material(model, "build-recipe", &recipe)?;
    model_material(model, "compiler-closure", &closure)?;
    model_material(
        model,
        "package-inputs",
        &read(root, "package-inputs.json", 4 * 1024 * 1024)?,
    )?;
    require(
        model["componentDigest"] == pin["component"]["sha256"]
            && model["componentSize"] == pin["component"]["bytes"]
            && model["source"]["repository"]
                == "https://github.com/KirilsTurkins/latent-service-fabric"
            && model["source"]["repositoryTrust"] == "operator-asserted"
            && model["source"]["capture"] == "explicit-input-files"
            && model["source"]["snapshotDigest"] == pin["sourceInputs"]["sha256"]
            && model["parameters"]
                == serde_json::json!({"compiler":"teavm-c",
                "entryPoint":"dev.latent.app.Capsule","target":"wasm32-wasip1",
                "bindings":"lsf-java-wit-v1","optimization":"O2","javaHeapBytes":4_194_304})
            && model["reproducibility"] == "not-checked"
            && model["hermetic"] == false
            && model["dependencyCompleteness"] == "declared-inputs-incomplete",
        "current Java fixture provenance claim exceeds observed source custody",
    )?;
    let build = inputs::load_current_java(root, &serde_json::to_vec(model)?)?;
    let expected_service = if name == "forbidden-http" {
        "examples/transaction-java-forbidden-http"
    } else {
        SERVICE
    };
    require(
        build.bundle.layout().config().name == format!("java718-{name}")
            && build.world == WORLD
            && build.service == expected_service,
        "current Java fixture package, world or service mismatch",
    )?;
    Ok((name.to_owned(), build))
}

pub(crate) fn sign_current_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        PINS,
        PROFILE,
        SOURCE,
    )
}

/// Separate signed negative material. This does not approve an immediate call,
/// qualify a runtime refusal or change the five-positive fixture's contract.
pub(crate) fn sign_current_java_with_negative(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &WITH_NEGATIVE,
        PINS,
        PROFILE,
        SOURCE,
    )
}

pub(crate) fn sign_rebuilt_current_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        REBUILT_PINS,
        PROFILE,
        SOURCE,
    )
}

pub(crate) fn sign_fresh_http_current_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        FRESH_HTTP_PINS,
        FRESH_HTTP_PROFILE,
        SOURCE,
    )
}

pub(super) fn absent(root: &Path, name: &str) -> Result<()> {
    match root.join(name).symlink_metadata() {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        _ => Err("negative Java fixture must not add a positive effect association".into()),
    }
}

fn sign_selected(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
    selected_names: &[&str],
    selected_pins: &[u8],
    expected_profile: &str,
    expected_source: &str,
) -> Result<()> {
    require(
        compiler_source == expected_source && paths.len() == selected_names.len(),
        if selected_names.len() == NAMES.len() {
            "current Java fixture requires the exact source and five positive captured inputs"
        } else {
            "current Java fixture requires the exact source and all six separately selected captured inputs"
        },
    )?;
    require(
        output.is_absolute() && !output.exists(),
        "current Java fixture output must be fresh and absolute",
    )?;
    let packet: Value = serde_json::from_slice(selected_pins)?;
    let captures = &packet["captures"];
    require(
        captures["sourceCommit"] == expected_source
            && captures["nativeIdempotencyProfile"] == expected_profile,
        "committed current Java fixture custody pins changed",
    )?;
    let mut builds = Vec::with_capacity(selected_names.len());
    let mut names = BTreeSet::new();
    for path in paths {
        let (name, build) = load(
            Path::new(path),
            captures,
            selected_names,
            expected_profile,
            expected_source,
        )?;
        require(
            names.insert(name),
            "current Java fixture input is duplicated",
        )?;
        builds.push(build);
    }
    require(
        names
            == selected_names
                .iter()
                .map(|name| (*name).to_owned())
                .collect::<BTreeSet<_>>(),
        "current Java fixture input set is incomplete",
    )?;
    // All captured byte and profile checks finish before generating any key or
    // output. Existing tracked signers, policy and real verification own proofs.
    sign_checked(output, builds, false, Some(compiler_source))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fresh_http_capture_keeps_its_constructor_profile_and_material_custody_separate() {
        let original: Value = serde_json::from_slice(PINS).unwrap();
        let rebuilt: Value = serde_json::from_slice(REBUILT_PINS).unwrap();
        let fresh: Value = serde_json::from_slice(FRESH_HTTP_PINS).unwrap();
        for old in [original, rebuilt] {
            assert_eq!(old["captures"]["nativeIdempotencyProfile"], PROFILE);
            for name in WITH_NEGATIVE {
                assert_ne!(
                    old["captures"]["variants"][name]["materials"]["report"],
                    fresh["captures"]["variants"][name]["materials"]["report"]
                );
            }
        }
        assert_eq!(fresh["captures"]["sourceCommit"], SOURCE);
        assert_eq!(
            fresh["captures"]["nativeIdempotencyProfile"],
            FRESH_HTTP_PROFILE
        );
        assert_eq!(fresh["constructor"]["profile"], FRESH_HTTP_PROFILE);
        assert_eq!(
            fresh["constructor"]["sourceCommit"],
            "d0a1c923b6b37c754ffdc574b2275a3edc73e3af"
        );
        assert_eq!(fresh["captures"]["variants"].as_object().unwrap().len(), 6);
        assert_eq!(fresh["signingQualified"], false);
        assert_eq!(fresh["executionQualified"], false);
        assert_eq!(fresh["packagedDistributionQualified"], false);
        assert!(fresh.get("recipient").is_none());
        assert!(fresh.get("receiptIdentities").is_none());
    }

    #[test]
    fn fresh_http_fixture_rejects_foreign_profile_source_and_partial_set_before_output() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("not-created");
        assert!(sign_fresh_http_current_java(&output, "unreviewed", &[]).is_err());
        assert!(sign_fresh_http_current_java(&output, SOURCE, &[]).is_err());
        let paths = vec![OsString::from(directory.path()); NAMES.len()];
        for (pins, profile) in [(PINS, FRESH_HTTP_PROFILE), (FRESH_HTTP_PINS, PROFILE)] {
            assert!(sign_selected(&output, SOURCE, &paths, &NAMES, pins, profile, SOURCE).is_err());
        }
        assert!(!output.exists());
    }

    #[test]
    fn recompiled_set_preserves_original_source_component_and_authority_inputs() {
        let original: Value = serde_json::from_slice(PINS).unwrap();
        let rebuilt: Value = serde_json::from_slice(REBUILT_PINS).unwrap();
        assert_eq!(
            original["captures"]["sourceCommit"],
            rebuilt["captures"]["sourceCommit"]
        );
        for name in WITH_NEGATIVE {
            let old = &original["captures"]["variants"][name]["materials"];
            let new = &rebuilt["captures"]["variants"][name]["materials"];
            for (key, value) in old.as_object().unwrap() {
                if key == "report" || key == "compilerInputs" {
                    assert_ne!(value, &new[key]);
                } else {
                    assert_eq!(value, &new[key]);
                }
            }
        }
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("must-not-exist");
        assert!(sign_rebuilt_current_java(&output, SOURCE, &[]).is_err());
        assert!(!output.exists());
    }

    #[test]
    fn current_fixture_never_accepts_another_source_or_partial_set() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("not-created");
        assert!(sign_current_java(&output, "unreviewed", &[]).is_err());
        assert!(sign_current_java(&output, SOURCE, &[]).is_err());
        assert!(!output.exists());
    }

    #[test]
    fn changed_unsigned_material_cannot_match_a_closed_custody_pin() {
        let identity =
            serde_json::json!({"sha256": artifact_blob_digest(b"original").as_str(), "bytes":8});
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(directory.path().join("input"), b"changed").unwrap();
        assert!(pinned(directory.path(), "input", &identity, 32).is_err());
    }

    #[test]
    fn negative_fixture_requires_its_separate_complete_source_set_before_output() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("not-created");
        assert!(sign_current_java_with_negative(&output, "unreviewed", &[]).is_err());
        let paths = vec![OsString::from(directory.path()); NAMES.len()];
        assert!(sign_current_java_with_negative(&output, SOURCE, &paths).is_err());
        assert!(
            sign_current_java(&output, SOURCE, &vec![OsString::from(directory.path()); 6]).is_err()
        );
        assert!(!output.exists());
    }

    #[test]
    fn negative_fixture_cannot_add_a_positive_marker_or_dangling_association() {
        let directory = tempfile::tempdir().unwrap();
        absent(directory.path(), "marker").unwrap();
        std::fs::write(directory.path().join("marker"), b"not-approved").unwrap();
        assert!(absent(directory.path(), "marker").is_err());
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(
                directory.path().join("missing"),
                directory.path().join("linked"),
            )
            .unwrap();
            assert!(absent(directory.path(), "linked").is_err());
        }
    }
}
