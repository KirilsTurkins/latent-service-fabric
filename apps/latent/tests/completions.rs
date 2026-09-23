//! Focused, offline process proof. No node, Wasm fixture or provider is needed.

use std::{fs, process::Command};
use tempfile::TempDir;

const SHELLS: [&str; 4] = ["bash", "zsh", "fish", "powershell"];

fn client(directory: &TempDir) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_latent"));
    command
        .env_clear()
        .env("HOME", directory.path())
        .env("USERPROFILE", directory.path())
        .env("XDG_CONFIG_HOME", directory.path())
        .env("PATH", "")
        .current_dir(directory.path());
    // Windows' loader may need this, but never inherit user configuration.
    if let Some(root) = std::env::var_os("SystemRoot") {
        command.env("SystemRoot", root);
    }
    command
}

#[test]
fn all_shells_work_without_inputs_and_leave_the_home_directory_untouched() {
    let directory = tempfile::tempdir().unwrap();
    for shell in SHELLS {
        let output = client(&directory)
            .args([
                "--config",
                "credentials-do-not-exist.json",
                "--profile",
                "not a valid profile",
                "--endpoint",
                "not a network endpoint",
                "--tenant",
                "not a valid tenant",
                "completions",
                shell,
            ])
            .output()
            .unwrap();
        assert!(output.status.success(), "{shell}: {:?}", output.stderr);
        assert!(output.stderr.is_empty(), "{shell}: {:?}", output.stderr);
        assert!(!output.stdout.is_empty());
        assert!(serde_json::from_slice::<serde_json::Value>(&output.stdout).is_err());
        let repeat = client(&directory)
            .args(["completions", shell])
            .output()
            .unwrap();
        assert!(repeat.status.success());
        assert_eq!(output.stdout, repeat.stdout);
        assert_eq!(fs::read_dir(directory.path()).unwrap().count(), 0);
    }
}

#[test]
fn quiet_preserves_script_bytes_and_json_is_never_a_success_envelope() {
    let directory = tempfile::tempdir().unwrap();
    for shell in SHELLS {
        let normal = client(&directory)
            .args(["completions", shell])
            .output()
            .unwrap();
        assert!(normal.status.success());
        for args in [
            vec!["--quiet", "completions", shell],
            vec!["completions", shell, "--quiet"],
        ] {
            let quiet = client(&directory).args(args).output().unwrap();
            assert!(quiet.status.success());
            assert_eq!(normal.stdout, quiet.stdout);
            assert!(quiet.stderr.is_empty());
        }
        for args in [
            vec!["--output", "json", "completions", shell],
            vec!["completions", shell, "--output=json"],
            vec!["--quiet", "completions", shell, "--output", "json"],
        ] {
            let output = client(&directory).args(args).output().unwrap();
            assert_eq!(output.status.code(), Some(2));
            assert!(output.stdout.is_empty());
            assert!(String::from_utf8(output.stderr)
                .unwrap()
                .contains("--output json"));
        }
    }
}

#[test]
fn invalid_arguments_help_version_and_existing_json_errors_keep_their_exit_contracts() {
    let directory = tempfile::tempdir().unwrap();
    for args in [
        vec!["completions"],
        vec!["completions", "elvish"],
        vec!["completions", "bash", "extra"],
        vec!["completions", "bash", "--install"],
        vec!["not-a-command"],
    ] {
        let output = client(&directory).args(args).output().unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert!(!output.stderr.is_empty());
    }
    for args in [
        vec!["--help"],
        vec!["--version"],
        vec!["completions", "--help"],
    ] {
        let output = client(&directory).args(args).output().unwrap();
        assert!(output.status.success());
        assert!(!output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
    let output = client(&directory)
        .args(["--output", "json", "completions", "unsupported"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    let json: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(json["error"]["code"], "invalid-arguments");
}

#[cfg(target_os = "linux")]
#[test]
fn actual_stdout_write_failure_has_a_nonzero_exit_status() {
    let directory = tempfile::tempdir().unwrap();
    let full = fs::OpenOptions::new()
        .write(true)
        .open("/dev/full")
        .unwrap();
    let output = client(&directory)
        .args(["completions", "bash"])
        .stdout(full)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("could not be generated or written"));
}

#[cfg(unix)]
#[test]
fn real_bash_completion_smoke_in_a_clean_shell() {
    let directory = tempfile::tempdir().unwrap();
    let generated = client(&directory)
        .args(["completions", "bash"])
        .output()
        .unwrap();
    assert!(generated.status.success());
    let script = directory.path().join("latent.bash");
    fs::write(&script, generated.stdout).unwrap();
    let output = Command::new("bash")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", directory.path())
        .env("LC_ALL", "C")
        .current_dir(directory.path())
        .args([
            "--noprofile",
            "--norc",
            "-c",
            include_str!("completions/bash-smoke.bash"),
            "--",
        ])
        .arg(script)
        .output()
        .expect("the Unix completion smoke test requires Bash");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b"bash completion smoke passed\n");
}

#[cfg(target_os = "linux")]
#[test]
fn real_fish_completion_smoke_in_a_clean_shell() {
    let directory = tempfile::tempdir().unwrap();
    let generated = client(&directory)
        .args(["completions", "fish"])
        .output()
        .unwrap();
    assert!(generated.status.success());
    fs::write(directory.path().join("latent.fish"), generated.stdout).unwrap();
    let output = Command::new("fish")
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", directory.path())
        .env("XDG_CONFIG_HOME", directory.path())
        .env("LC_ALL", "C")
        .current_dir(directory.path())
        .args([
            "--no-config",
            "-c",
            include_str!("completions/fish-smoke.fish"),
        ])
        .output()
        .expect("the Linux completion smoke test requires Fish (see toolchain setup)");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b"fish completion smoke passed\n");
    assert!(!directory.path().join("unexpected-callback").exists());
}
