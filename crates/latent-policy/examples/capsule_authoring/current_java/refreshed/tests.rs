use super::*;
use serde_json::Value;

const PRIOR: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json"
));

fn five_inputs(root: &Path) -> Vec<OsString> {
    vec![root.as_os_str().to_owned(); NAMES.len()]
}

#[test]
fn refreshed_current_packet_preserves_six_components_and_closed_compiler_contracts() {
    let current: Value = serde_json::from_slice(PINS).unwrap();
    let prior: Value = serde_json::from_slice(PRIOR).unwrap();
    assert_eq!(current["captures"]["sourceCommit"], SOURCE);
    assert_eq!(
        current["captures"]["sourceTree"],
        prior["captures"]["sourceTree"]
    );
    assert_eq!(current["captures"]["nativeIdempotencyProfile"], PROFILE);
    assert_ne!(
        current["captures"]["nativeIdempotencyProfile"],
        prior["captures"]["nativeIdempotencyProfile"]
    );
    assert_eq!(
        current["predecessorCapturePacketSha256"],
        latent_artifacts::package::artifact_blob_digest(PRIOR).as_str()
    );
    let variants = current["captures"]["variants"].as_object().unwrap();
    assert_eq!(variants.len(), 6);
    assert_eq!(NAMES.len(), 5);
    assert!(!NAMES.contains(&"forbidden-http"));
    for (name, capture) in variants {
        let materials = &capture["materials"];
        let old = &prior["captures"]["variants"][name]["materials"];
        for field in [
            "component",
            "compilerInputs",
            "companion",
            "recipeInputs",
            "capsuleSource",
            "applicationSchemaInputs",
        ] {
            assert_eq!(materials[field], old[field], "{name} {field}");
        }
        assert_ne!(materials["report"], old["report"], "{name}");
        assert_eq!(
            current["reconstruction"]["componentIdentityComparison"][name]["byteExactHistorical"],
            true
        );
    }
    assert_eq!(
        current["diagnosticProbe"]["helper"],
        prior["diagnosticProbe"]["helper"]
    );
    assert_ne!(
        current["diagnosticProbe"]["declaration"],
        prior["diagnosticProbe"]["declaration"]
    );
    for field in ["ordinaryJavaHeapBytes", "nativeMemoryGrantBytes"] {
        assert_eq!(
            current["compilerInputs"][field],
            prior["compilerInputs"][field]
        );
    }
    for field in [
        "signingQualified",
        "executionQualified",
        "memoryExhaustionQualified",
        "packagedDistributionQualified",
    ] {
        assert_eq!(current[field], false, "{field}");
    }
}

#[test]
fn refreshed_current_mode_requires_original_source_and_five_inputs_before_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    for (source, paths) in [
        ("wrong", five_inputs(root.path())),
        (
            "47e4e60778d7fdd033d5f1d6c05595752713c971",
            five_inputs(root.path()),
        ),
        (SOURCE, Vec::new()),
        (SOURCE, vec![root.path().into(); 4]),
        (SOURCE, vec![root.path().into(); 6]),
    ] {
        let error = sign_refreshed_current_java(&output, source, &paths).unwrap_err();
        assert_eq!(
            error.to_string(),
            "current Java fixture requires the exact source and five positive captured inputs"
        );
        assert!(!output.exists());
    }
}

#[test]
fn refreshed_current_mode_refuses_unpinned_report_before_component_or_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    std::fs::write(
        root.path().join("compiler-report.json"),
        br#"{"variant":"aggregate"}"#,
    )
    .unwrap();
    let error =
        sign_refreshed_current_java(&output, SOURCE, &five_inputs(root.path())).unwrap_err();
    assert_eq!(
        error.to_string(),
        "current Java fixture material digest mismatch"
    );
    assert!(!root.path().join("component.wasm").exists());
    assert!(!output.exists());
}

#[test]
fn refreshed_current_mode_refuses_relative_input_before_read_or_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    let paths = vec![OsString::from("relative-current-fixture"); 5];
    let error = sign_refreshed_current_java(&output, SOURCE, &paths).unwrap_err();
    assert_eq!(
        error.to_string(),
        "current Java fixture inputs must be absolute"
    );
    assert!(!output.exists());
}

#[test]
fn refreshed_current_mode_keeps_forbidden_capture_unsigned_before_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    std::fs::write(
        root.path().join("compiler-report.json"),
        br#"{"variant":"forbidden-http"}"#,
    )
    .unwrap();
    let error =
        sign_refreshed_current_java(&output, SOURCE, &five_inputs(root.path())).unwrap_err();
    assert_eq!(
        error.to_string(),
        "current Java fixture variant is not approved for signing"
    );
    assert!(!root.path().join("component.wasm").exists());
    assert!(!output.exists());
}

#[test]
fn refreshed_current_mode_refuses_existing_or_relative_output_before_inputs() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("sentinel");
    std::fs::write(&output, b"preserve").unwrap();
    for path in [output.as_path(), Path::new("relative-output")] {
        let error =
            sign_refreshed_current_java(path, SOURCE, &five_inputs(root.path())).unwrap_err();
        assert_eq!(
            error.to_string(),
            "current Java fixture output must be fresh and absolute"
        );
        assert_eq!(std::fs::read(&output).unwrap(), b"preserve");
        assert!(!root.path().join("compiler-report.json").exists());
    }
}
