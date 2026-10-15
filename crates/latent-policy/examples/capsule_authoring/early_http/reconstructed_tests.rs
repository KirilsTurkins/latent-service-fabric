use super::*;

#[test]
fn reconstructed_capture_changes_only_report_identity_and_preserves_authority_inputs() {
    let prior: Value = serde_json::from_slice(REBUILT_PINS).unwrap();
    let reconstructed: Value = serde_json::from_slice(RECONSTRUCTED_PINS).unwrap();
    for field in [
        "schemaVersion",
        "sourceCommit",
        "sourceTree",
        "variant",
        "actualImports",
        "limits",
    ] {
        assert_eq!(reconstructed[field], prior[field], "{field}");
    }
    assert_eq!(reconstructed["sourceCommit"], SOURCE);
    for (name, identity) in prior["materials"].as_object().unwrap() {
        if name == "report" {
            assert_ne!(reconstructed["materials"][name], *identity);
        } else {
            assert_eq!(reconstructed["materials"][name], *identity, "{name}");
        }
    }
    assert_eq!(
        reconstructed["historicalCapturePacketSha256"],
        latent_artifacts::package::artifact_blob_digest(REBUILT_PINS)
    );
    assert_eq!(reconstructed["reportAndCompilerClosureAreNew"], false);
    assert_eq!(reconstructed["reportIsNew"], true);
    assert_eq!(reconstructed["compilerClosureByteExactHistorical"], true);
    for field in [
        "signedNodeExecutionQualified",
        "immediateHttpDenialQualified",
        "postStageRollbackQualified",
        "productionApproval",
        "issueClosure",
    ] {
        assert_eq!(reconstructed[field], false, "{field}");
    }
}

#[test]
fn reconstructed_mode_requires_original_source_and_one_input_before_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    let input = root.path().as_os_str().to_owned();
    for (source, paths) in [
        ("wrong", vec![input.clone()]),
        (
            "eba0d96e9439028aacd6c1f9a85d4ce0118a19bc",
            vec![input.clone()],
        ),
        (SOURCE, Vec::new()),
        (SOURCE, vec![input.clone(), input]),
    ] {
        let error = sign_reconstructed_early_http(&output, source, &paths).unwrap_err();
        assert_eq!(
            error.to_string(),
            "reconstructed early HTTP signing requires one exact captured input"
        );
        assert!(!output.exists());
    }
}

#[test]
fn reconstructed_mode_refuses_unpinned_report_before_component_or_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    std::fs::write(root.path().join("compiler-report.json"), b"{}").unwrap();
    let error = sign_reconstructed_early_http(&output, SOURCE, &[root.path().into()]).unwrap_err();
    assert_eq!(
        error.to_string(),
        "current Java fixture material digest mismatch"
    );
    assert!(!root.path().join("component.wasm").exists());
    assert!(!output.exists());
}

#[test]
fn reconstructed_mode_refuses_positive_effect_assets_before_report_or_output() {
    for name in [
        "java-current-http-profile.json",
        "deferred-http-requirements.json",
        "application-schema-inputs.json",
    ] {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("must-not-exist");
        std::fs::write(root.path().join(name), b"unreviewed").unwrap();
        let error =
            sign_reconstructed_early_http(&output, SOURCE, &[root.path().into()]).unwrap_err();
        assert_eq!(
            error.to_string(),
            "negative Java fixture must not add a positive effect association"
        );
        assert!(!root.path().join("compiler-report.json").exists());
        assert!(!output.exists());
    }
}

#[test]
fn reconstructed_mode_refuses_relative_input_before_read_or_output() {
    let root = tempfile::tempdir().unwrap();
    let output = root.path().join("must-not-exist");
    let error =
        sign_reconstructed_early_http(&output, SOURCE, &[OsString::from("relative-early-fixture")])
            .unwrap_err();
    assert_eq!(error.to_string(), "early HTTP fixture needs absolute input");
    assert!(!output.exists());
}

#[cfg(unix)]
#[test]
fn reconstructed_mode_refuses_dangling_effect_assets_before_report_or_output() {
    for name in [
        "java-current-http-profile.json",
        "deferred-http-requirements.json",
        "application-schema-inputs.json",
    ] {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("must-not-exist");
        std::os::unix::fs::symlink("missing", root.path().join(name)).unwrap();
        let error =
            sign_reconstructed_early_http(&output, SOURCE, &[root.path().into()]).unwrap_err();
        assert_eq!(
            error.to_string(),
            "negative Java fixture must not add a positive effect association"
        );
        assert!(!root.path().join("compiler-report.json").exists());
        assert!(!output.exists());
    }
}
