//! Deterministic process-command construction and captured execution.

use std::ffi::{OsStr, OsString};
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Output};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapturedProcess {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

impl CapturedProcess {
    pub fn success(&self) -> bool {
        self.status.success()
    }

    pub fn stdout_text(&self) -> String {
        String::from_utf8_lossy(&self.stdout).into_owned()
    }

    pub fn stderr_text(&self) -> String {
        String::from_utf8_lossy(&self.stderr).into_owned()
    }
}

impl From<Output> for CapturedProcess {
    fn from(output: Output) -> Self {
        Self {
            status: output.status,
            stdout: output.stdout,
            stderr: output.stderr,
        }
    }
}

/// Reusable process specification for CLI and integration tests.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessHarness {
    program: OsString,
    arguments: Vec<OsString>,
    current_directory: Option<PathBuf>,
    environment: Vec<(OsString, OsString)>,
    clear_environment: bool,
}

impl ProcessHarness {
    pub fn new(program: impl Into<OsString>) -> Self {
        Self {
            program: program.into(),
            arguments: Vec::new(),
            current_directory: None,
            environment: Vec::new(),
            clear_environment: false,
        }
    }

    #[must_use]
    pub fn arg(mut self, argument: impl Into<OsString>) -> Self {
        self.arguments.push(argument.into());
        self
    }

    #[must_use]
    pub fn args<I, S>(mut self, arguments: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<OsString>,
    {
        self.arguments.extend(arguments.into_iter().map(Into::into));
        self
    }

    #[must_use]
    pub fn current_dir(mut self, directory: impl Into<PathBuf>) -> Self {
        self.current_directory = Some(directory.into());
        self
    }

    #[must_use]
    pub fn env(mut self, key: impl Into<OsString>, value: impl Into<OsString>) -> Self {
        self.environment.push((key.into(), value.into()));
        self
    }

    #[must_use]
    pub fn env_clear(mut self) -> Self {
        self.clear_environment = true;
        self
    }

    pub fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command.args(&self.arguments);
        if self.clear_environment {
            command.env_clear();
        }
        for (key, value) in &self.environment {
            command.env(key, value);
        }
        if let Some(directory) = &self.current_directory {
            command.current_dir(directory);
        }
        command
    }

    pub fn run(&self) -> io::Result<CapturedProcess> {
        self.command().output().map(Into::into)
    }

    pub fn program(&self) -> &OsStr {
        &self.program
    }

    pub fn current_directory(&self) -> Option<&Path> {
        self.current_directory.as_deref()
    }
}

#[cfg(test)]
mod tests {
    use super::ProcessHarness;
    use std::ffi::OsStr;
    use std::path::Path;

    #[test]
    fn builds_a_repeatable_command() {
        let harness = ProcessHarness::new("latent")
            .args(["invoke", "echo"])
            .env("LSF_TEST", "1")
            .current_dir("fixture");
        let command = harness.command();

        assert_eq!(command.get_program(), OsStr::new("latent"));
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            vec![OsStr::new("invoke"), OsStr::new("echo")]
        );
        assert_eq!(command.get_current_dir(), Some(Path::new("fixture")));
        assert!(command
            .get_envs()
            .any(|(key, value)| key == OsStr::new("LSF_TEST") && value == Some(OsStr::new("1"))));
    }
}
