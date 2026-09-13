use super::{config, document, failure, input, TOKEN};
use crate::config::ExecutionIsolationProfile;
use latent_core::PlatformErrorCode;

#[test]
fn local_check_config_reports_actual_controls_without_secrets_or_storage() {
    let (directory, config) = config();
    let settings = config.derive().unwrap();
    let report = settings.check_config().unwrap();
    let encoded = serde_json::to_string(&report).unwrap();
    assert!(encoded.len() < 4096);
    assert!(!encoded.contains(TOKEN));
    assert!(!encoded.contains("operator"));
    assert!(!encoded.contains(&directory.path().display().to_string()));
    let value: serde_json::Value = serde_json::from_str(&encoded).unwrap();
    assert_eq!(value["profile"], "local-experimental-v1");
    assert_eq!(value["threatClass"], "T0");
    assert_eq!(value["compiler"], "in-process");
    assert_eq!(value["guestBoundary"], "in-process-wasmtime");
    assert_eq!(value["admission"], "trusted-local");
    assert_eq!(value["authenticatedNativeLoading"], false);
    assert!(value["compilerSandbox"].is_null());
    assert_eq!(
        value["protectedCredentialFile"],
        cfg!(all(target_os = "linux", target_arch = "x86_64"))
    );
    assert!(!directory.path().join("data").exists());
    assert!(report.matches(&settings));
    assert_eq!(
        report.attributes()["lsf.security.profile"],
        "local-experimental-v1"
    );
}

#[test]
fn unavailable_profiles_and_a_forged_file_protection_flag_are_not_configuration() {
    let original: serde_json::Value = serde_json::from_str(&document()).unwrap();
    for value in [
        serde_json::Value::Null,
        serde_json::json!({}),
        serde_json::json!("fixed-execution-host-v1"),
        serde_json::json!("external-capsule-v2"),
        serde_json::json!("isolated-aot-compiler-v1"),
        serde_json::json!("renderer-component-v1"),
    ] {
        let mut document = original.clone();
        document["securityProfile"] = value;
        assert!(input::decode(&serde_json::to_vec(&document).unwrap()).is_err());
    }
    let mut forged = original;
    forged["credentialsFromProtectedFile"] = serde_json::json!(true);
    assert!(input::decode(&serde_json::to_vec(&forged).unwrap()).is_err());
}

#[test]
fn a_profile_label_cannot_replace_enforced_admission_or_isolated_compilation() {
    let (_directory, mut config) = config();
    config.security_profile = ExecutionIsolationProfile::ExternalCapsule;
    assert_eq!(
        failure(config.derive()).code,
        PlatformErrorCode::InvalidArgument
    );
    assert!(failure(config.derive())
        .message
        .contains("externalCapsulePrerequisites"));
    let mut input: serde_json::Value = serde_json::from_str(&document()).unwrap();
    input["securityProfile"] = serde_json::json!("external-capsule-v1");
    let config = input::decode(&serde_json::to_vec(&input).unwrap()).unwrap();
    assert!(!config.credentials_from_protected_file);
    assert_eq!(
        failure(config.derive()).code,
        PlatformErrorCode::InvalidArgument
    );
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn an_external_catalog_requirement_survives_reopen_and_blocks_an_omitted_profile() {
    let (_directory, config) = config();
    let settings = config.derive().unwrap();
    let marker = super::super::protected_file::execution_profile_marker;
    assert!(!marker(&settings.data_directory, false).unwrap());
    assert!(!settings.data_directory.exists());
    assert!(marker(&settings.data_directory, true).unwrap());
    assert!(marker(&settings.data_directory, false).unwrap());
    assert!(marker(&settings.data_directory, true).unwrap());
    let reopened = config.derive().unwrap();
    let error = reopened.check_config().unwrap_err();
    assert!(error.message.contains("externalCapsuleRequired"));
    assert!(!settings.data_directory.join("releases").exists());
    let path = settings.data_directory.join("EXECUTION_PROFILE");
    std::fs::write(&path, b"lsf-external").unwrap();
    assert!(marker(&settings.data_directory, false).is_err());
    assert!(marker(&settings.data_directory, true).is_err());
    assert!(reopened.check_config().is_err());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn profile_marker_rejects_links_and_unprotected_directories_and_leaves_targets_untouched() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    let (directory, config) = config();
    let settings = config.derive().unwrap();
    let marker = super::super::protected_file::execution_profile_marker;
    let target = directory.path().join("untouched");
    std::fs::write(&target, "sentinel").unwrap();
    std::fs::create_dir(&settings.data_directory).unwrap();
    symlink(&target, settings.data_directory.join("EXECUTION_PROFILE")).unwrap();
    assert!(marker(&settings.data_directory, false).is_err());
    assert!(marker(&settings.data_directory, true).is_err());
    assert_eq!(std::fs::read_to_string(&target).unwrap(), "sentinel");
    let writable = directory.path().join("writable");
    std::fs::create_dir(&writable).unwrap();
    std::fs::set_permissions(&writable, std::fs::Permissions::from_mode(0o777)).unwrap();
    assert!(marker(&writable, true).is_err());
    assert!(!writable.join("EXECUTION_PROFILE").exists());
}
