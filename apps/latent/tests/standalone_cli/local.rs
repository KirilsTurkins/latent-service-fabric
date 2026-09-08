use std::fs;
use std::process::{Command, Stdio};

use serde_json::json;

use super::process::{Output, Process, OPERATOR, WATCHDOG};

fn local(arguments: &[&str]) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_latent"));
    command.args(arguments).stdin(Stdio::null());
    Process::spawn(command, WATCHDOG).wait()
}

#[test]
fn help_version_and_local_manifest_validation_need_no_node() {
    for command in [vec!["--help"], vec!["--version"], vec!["invoke", "--help"]] {
        let output = local(&command);
        assert_eq!(output.code, Some(0));
        assert!(!output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
    let root =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/echo-contract");
    for (kind, name) in [
        ("capsule", "capsule.json"),
        ("deployment", "deployment.json"),
    ] {
        let path = root.join(name);
        let value = local(&[
            "--output",
            "json",
            "validate",
            kind,
            path.to_str().expect("fixture path"),
        ])
        .json(0, "success");
        assert_eq!(value["requestDispatched"], false);
        assert_eq!(value["outcomeKnown"], true);
    }
}

#[test]
fn malformed_arguments_and_inputs_emit_one_redacted_local_json_error() {
    for arguments in [
        vec!["--output", "json", "--quiet", "node", "list"],
        vec![
            "--output",
            "json",
            "release",
            "publish",
            "--manifest",
            "-",
            "--component",
            "-",
            "--contracts",
            "missing.json",
        ],
        vec!["--output", "json", "activation", "get", ""],
        vec!["--output", "json", "--token", OPERATOR, "node", "list"],
    ] {
        let value = local(&arguments).json(2, "local-error");
        assert_eq!(value["requestDispatched"], false);
    }
    let directory = tempfile::tempdir().expect("local inputs");
    let path = directory.path().join("invalid.json");
    let secret = "request-document-sensitive-canary";
    fs::write(&path, secret).expect("malformed manifest");
    let output = local(&[
        "--output",
        "json",
        "validate",
        "capsule",
        path.to_str().expect("test path"),
    ]);
    assert!(!output.stdout.contains(secret) && !output.stderr.contains(secret));
    output.json(2, "local-error");
}

#[test]
fn configured_payload_file_and_stdin_bounds_fail_before_connecting() {
    let directory = tempfile::tempdir().expect("bounded input directory");
    let config = directory.path().join("client.json");
    fs::write(
        &config,
        serde_json::to_vec(&json!({
            "formatVersion": 1, "profiles": [{"name":"local", "endpoint":"http://127.0.0.1:1",
                "tenant":"examples", "token":OPERATOR, "limits":{"maximumPayloadBytes":3}}]
        }))
        .expect("profile JSON"),
    )
    .expect("profile");
    let input = directory.path().join("payload.bin");
    fs::write(&input, b"1234").expect("maximum plus one input");
    for stdin in [false, true] {
        let mut command = Command::new(env!("CARGO_BIN_EXE_latent"));
        command.arg("--config").arg(&config).args([
            "--output",
            "json",
            "invoke",
            "--service",
            "examples/echo",
            "--contract",
            "examples:echo/api@0.1.0",
            "--function",
            "echo",
            "--input",
        ]);
        if stdin {
            command
                .arg("-")
                .stdin(fs::File::open(&input).expect("bounded stdin file"));
        } else {
            command.arg(&input).stdin(Stdio::null());
        }
        let value = Process::spawn(command, WATCHDOG)
            .wait()
            .json(2, "local-error");
        assert_eq!(value["error"]["code"], "input-too-large");
        assert_eq!(value["requestDispatched"], false);
    }
}

#[test]
#[cfg(target_os = "linux")]
fn named_pipe_inputs_fail_before_open_or_network_dispatch() {
    let directory = tempfile::tempdir().expect("named pipe fixture directory");
    let fifo = directory.path().join("unopened-input");
    let mut create = Command::new("mkfifo");
    create.arg(&fifo).stdin(Stdio::null());
    assert_eq!(Process::spawn(create, WATCHDOG).wait().code, Some(0));
    let value = local(&[
        "--output",
        "json",
        "validate",
        "capsule",
        fifo.to_str().expect("test path"),
    ])
    .json(2, "local-error");
    assert_eq!(value["error"]["code"], "input-read-failed");
    let config = directory.path().join("client.json");
    fs::write(
        &config,
        serde_json::to_vec(&json!({
            "formatVersion":1,"profiles":[{"name":"local","endpoint":"http://127.0.0.1:1",
                "tenant":"examples","token":OPERATOR}]
        }))
        .expect("profile JSON"),
    )
    .expect("client profile");
    let value = local(&[
        "--config",
        config.to_str().expect("test path"),
        "--output",
        "json",
        "invoke",
        "--service",
        "examples/echo",
        "--contract",
        "examples:echo/api@0.1.0",
        "--function",
        "echo",
        "--input",
        fifo.to_str().expect("test path"),
    ])
    .json(2, "local-error");
    assert_eq!(value["error"]["code"], "input-read-failed");
    assert_eq!(value["requestDispatched"], false);
}
