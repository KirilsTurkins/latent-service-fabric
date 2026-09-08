use std::ffi::OsStr;

use clap::{error::ErrorKind, Parser};
use serde_json::json;

use super::{is_phase0, status, Command, CommandLine};

#[test]
fn legacy_dispatch_is_limited_to_explicit_first_command() {
    assert!(is_phase0(OsStr::new("phase0-spike")));
    assert!(is_phase0(OsStr::new("spike")));
    assert!(!is_phase0(OsStr::new("serve")));
    assert!(!is_phase0(OsStr::new("phase0-spike-extra")));
}

#[test]
fn serve_requires_configuration_and_help_advertises_both_surfaces() {
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
    assert!(text.contains("serve"));
    assert!(text.contains("phase0-spike"));
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
