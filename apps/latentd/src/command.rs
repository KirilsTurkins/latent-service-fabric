//! Product command dispatch, separate from the historical Phase 0 entry point.

#[cfg(target_os = "linux")]
mod serve;
#[cfg(any(target_os = "linux", test))]
mod status;
#[cfg(test)]
mod tests;

use std::ffi::OsStr;
use std::path::PathBuf;
use std::process::ExitCode;

use clap::{error::ErrorKind, Parser, Subcommand};
use latent_core::PlatformErrorCode;

#[derive(Parser)]
#[command(
    name = "latentd",
    version,
    about = "Latent Service Fabric standalone node"
)]
struct CommandLine {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Serve the standalone node using a versioned local configuration file.
    Serve {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
    /// Run the finite, non-production Phase 0 validation tools.
    #[command(name = "phase0-spike", visible_alias = "spike")]
    Phase0Spike,
}

/// Dispatches legacy invocations unchanged, then handles the product commands.
#[must_use]
pub fn main_entry() -> ExitCode {
    if std::env::args_os().nth(1).as_deref().is_some_and(is_phase0) {
        return crate::spike::main_entry();
    }
    let command = match CommandLine::try_parse() {
        Ok(command) => command.command,
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) =>
        {
            return if error.print().is_ok() {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            };
        }
        Err(_) => {
            return report_failure(Failure::new("command", PlatformErrorCode::InvalidArgument))
        }
    };
    let result = match command {
        Command::Serve { config } => run_serve(&config),
        Command::Phase0Spike => Err(Failure::new("command", PlatformErrorCode::InvalidArgument)),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => report_failure(failure),
    }
}

fn is_phase0(argument: &OsStr) -> bool {
    argument == "phase0-spike" || argument == "spike"
}

#[cfg(target_os = "linux")]
fn run_serve(path: &std::path::Path) -> Result<(), Failure> {
    serve::run(path)
}

#[cfg(not(target_os = "linux"))]
fn run_serve(_path: &std::path::Path) -> Result<(), Failure> {
    Err(Failure::new("platform", PlatformErrorCode::Unavailable))
}

#[derive(Clone, Copy)]
struct Failure {
    stage: &'static str,
    code: PlatformErrorCode,
}

impl Failure {
    const fn new(stage: &'static str, code: PlatformErrorCode) -> Self {
        Self { stage, code }
    }
}

fn report_failure(failure: Failure) -> ExitCode {
    // Do not print raw CLI/parser/platform errors, paths, credentials or payloads.
    eprintln!("latentd: {}: {}", failure.stage, failure.code.wire_code());
    ExitCode::from(if failure.code == PlatformErrorCode::InvalidArgument {
        2
    } else {
        1
    })
}
