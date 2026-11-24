use clap::{error::ErrorKind, Parser};
use serde_json::json;

use super::{status, Command, CommandLine};

#[test]
fn check_config_requires_an_explicit_file_and_never_selects_serve() {
    let parsed =
        CommandLine::try_parse_from(["latentd", "check-config", "--config", "node.json"]).unwrap();
    let Command::CheckConfig {
        config,
        check_state_roots: false,
        check_retained_state: false,
    } = parsed.command
    else {
        panic!("check-config")
    };
    assert_eq!(config, std::path::PathBuf::from("node.json"));
    assert!(CommandLine::try_parse_from(["latentd", "check-config"]).is_err());
    let retained = [
        "latentd",
        "check-config",
        "--config",
        "node.json",
        "--check-retained-state",
    ];
    assert!(CommandLine::try_parse_from(retained).is_err());
    assert!(
        CommandLine::try_parse_from(retained.into_iter().chain(["--check-state-roots"])).is_ok()
    );
}

#[test]
fn serve_requires_configuration_and_help_advertises_only_product_surfaces() {
    let parsed = CommandLine::try_parse_from(["latentd", "serve", "--config", "node.json"])
        .expect("parse product command");
    let Command::Serve { config } = parsed.command else {
        panic!("serve command expected");
    };
    assert_eq!(config, std::path::PathBuf::from("node.json"));
    assert!(CommandLine::try_parse_from(["latentd", "serve"]).is_err());
    let help = CommandLine::try_parse_from(["latentd", "--help"])
        .err()
        .expect("help is a successful display request");
    assert_eq!(help.kind(), ErrorKind::DisplayHelp);
    let text = help.to_string();
    assert!(text.contains("check-config"));
    assert!(text.contains("serve"));
    assert!(text.contains("transaction-recovery"));
    assert!(!text.contains("migrate-catalog"));
    assert!(!text.contains("phase0-spike"));
}

#[test]
fn transaction_recovery_uses_a_protected_credential_path_and_one_mode() {
    let common = [
        "latentd",
        "transaction-recovery",
        "--config",
        "node.json",
        "--credential-file",
        "operator.credential",
        "--tenant",
        "tenant",
    ];
    assert!(CommandLine::try_parse_from(common).is_err());
    let parsed =
        CommandLine::try_parse_from(common.into_iter().chain(["--request-file", "request.json"]))
            .unwrap();
    assert!(matches!(parsed.command, Command::TransactionRecovery(_)));
    assert!(CommandLine::try_parse_from(common.into_iter().chain([
        "--request-file",
        "request.json",
        "--diagnose-startup",
    ]))
    .is_err());
    assert!(CommandLine::try_parse_from(common.into_iter().chain([
        "--request-file",
        "request.json",
        "--credential",
        "direct-value",
    ]))
    .is_err());
}

#[test]
fn status_encoding_is_one_bounded_json_line() {
    let value = json!({"event": "started", "nodeId": "escaped\nidentifier", "ready": false});
    let bytes = status::encode(&value).expect("bounded output");
    let text = std::str::from_utf8(&bytes).expect("UTF-8 JSON output");
    assert_eq!(text.lines().count(), 1);
    assert!(text.ends_with('\n'));
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes).expect("JSON line"),
        value
    );
    assert!(status::encode(&json!({"oversized": "x".repeat(16 * 1024)})).is_err());
}

#[test]
fn obsolete_catalog_migration_command_is_rejected() {
    assert!(
        CommandLine::try_parse_from(["latentd", "migrate-catalog", "--config", "node.json"])
            .is_err()
    );
}

#[test]
fn event_profile_preview_requires_an_explicit_configuration() {
    let parsed = CommandLine::try_parse_from([
        "latentd",
        "inspect-configured-event-effects",
        "--config",
        "node.json",
    ])
    .unwrap();
    let Command::InspectConfiguredEventEffects { config } = parsed.command else {
        panic!("event effect inspection expected");
    };
    assert_eq!(config, std::path::PathBuf::from("node.json"));
    assert!(CommandLine::try_parse_from(["latentd", "inspect-configured-event-effects"]).is_err());
}
