use super::*;
use clap::{Arg, Command, Parser, ValueHint};

fn script(shell: CompletionShell, command: Command) -> Vec<u8> {
    let mut bytes = Vec::new();
    write_script(shell, command, &mut bytes).unwrap();
    bytes
}

#[test]
fn all_generators_are_deterministic_and_include_real_nested_grammar() {
    for &shell in CompletionShell::value_variants() {
        let bytes = script(shell, Cli::command());
        assert_eq!(bytes, script(shell, Cli::command()), "{shell:?}");
        let text = String::from_utf8(bytes).unwrap();
        for expected in [
            "completions",
            "publish-package",
            "deployment",
            "connect-timeout-ms",
            "config",
            "budget-profile",
            "phase1",
            "phase3",
            "human",
            "json",
            "provider-binding",
            "rolled-back",
        ] {
            assert!(text.contains(expected), "{shell:?}: missing {expected}");
        }
    }
}

#[test]
fn test_only_command_extension_reaches_every_generator_without_a_command_table() {
    for &shell in CompletionShell::value_variants() {
        let original = String::from_utf8(script(shell, Cli::command())).unwrap();
        assert!(!original.contains("grammar-probe"));
        let command = Cli::command().subcommand(
            Command::new("grammar-probe")
                .arg(Arg::new("position-choice").value_parser(["position-alpha", "position-beta"]))
                .arg(
                    Arg::new("test-choice")
                        .long("test-choice")
                        .value_parser(["probe-alpha", "probe-beta"]),
                )
                .arg(
                    Arg::new("probe-file")
                        .long("probe-file")
                        .value_hint(ValueHint::FilePath),
                )
                .arg(
                    Arg::new("probe-dir")
                        .long("probe-dir")
                        .value_hint(ValueHint::DirPath),
                ),
        );
        let extended = String::from_utf8(script(shell, command)).unwrap();
        for expected in [
            "grammar-probe",
            "test-choice",
            "probe-alpha",
            "probe-beta",
            "probe-file",
            "probe-dir",
            "position-alpha",
            "position-beta",
        ] {
            assert!(extended.contains(expected), "{shell:?}: missing {expected}");
        }
    }
}

#[test]
fn completion_shell_parser_is_explicit_and_rejects_invalid_arguments() {
    for shell in ["bash", "zsh", "fish", "powershell"] {
        assert!(Cli::try_parse_from(["latent", "completions", shell]).is_ok());
    }
    for arguments in [
        vec!["latent", "completions"],
        vec!["latent", "completions", "elvish"],
        vec!["latent", "completions", "power-shell"],
        vec!["latent", "completions", "BASH"],
        vec!["latent", "completions", "bash", "extra"],
        vec!["latent", "completions", "bash", "--install"],
    ] {
        assert!(Cli::try_parse_from(arguments).is_err());
    }
}

#[test]
fn json_is_rejected_before_any_script_bytes_are_written() {
    for &shell in CompletionShell::value_variants() {
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();
        let code = execute(shell, OutputFormat::Json, &mut stdout, &mut stderr);
        assert_eq!(code, 2);
        assert!(stdout.is_empty());
        assert!(String::from_utf8(stderr).unwrap().contains("--output json"));
    }
}

struct FailingWriter {
    remaining: usize,
    zero_write: bool,
    fail_flush: bool,
    bytes: Vec<u8>,
}

impl Write for FailingWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return if self.zero_write {
                Ok(0)
            } else {
                Err(io::Error::from(io::ErrorKind::BrokenPipe))
            };
        }
        let count = self.remaining.min(bytes.len());
        self.bytes.extend_from_slice(&bytes[..count]);
        self.remaining -= count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        if self.fail_flush {
            Err(io::Error::other("flush failed"))
        } else {
            Ok(())
        }
    }
}

#[test]
fn broken_pipe_partial_write_zero_write_and_flush_failure_are_not_success() {
    for &shell in CompletionShell::value_variants() {
        for (remaining, zero_write, fail_flush) in [
            (0, false, false),
            (7, false, false),
            (0, true, false),
            (usize::MAX, false, true),
        ] {
            let mut writer = FailingWriter {
                remaining,
                zero_write,
                fail_flush,
                bytes: Vec::new(),
            };
            let mut stderr = Vec::new();
            let code = execute(shell, OutputFormat::Human, &mut writer, &mut stderr);
            assert_eq!(code, 2);
            assert!(!stderr.is_empty());
            if remaining != usize::MAX {
                assert_eq!(writer.bytes.len(), remaining);
            }
        }
    }
}

struct ShortWriter {
    interrupted: bool,
    flushed: bool,
    bytes: Vec<u8>,
}

impl Write for ShortWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if !self.interrupted {
            self.interrupted = true;
            return Err(io::Error::from(io::ErrorKind::Interrupted));
        }
        let count = bytes.len().min(7);
        self.bytes.extend_from_slice(&bytes[..count]);
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.flushed = true;
        Ok(())
    }
}

#[test]
fn interrupted_and_short_writes_are_retried_and_success_requires_flush() {
    for &shell in CompletionShell::value_variants() {
        let mut writer = ShortWriter {
            interrupted: false,
            flushed: false,
            bytes: Vec::new(),
        };
        write_script(shell, Cli::command(), &mut writer).unwrap();
        assert!(writer.flushed);
        assert_eq!(writer.bytes, script(shell, Cli::command()));
    }
}
