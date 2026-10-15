//! Product command dispatch.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod inspection;
#[cfg(target_os = "linux")]
mod serve;
#[cfg(any(target_os = "linux", test))]
mod status;
#[cfg(test)]
mod tests;

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
    /// Check protected configuration and actual compiler/profile prerequisites.
    CheckConfig {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
    /// Serve the standalone node using a versioned local configuration file.
    Serve {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
    /// Read checked current host proposals without opening the state engine.
    InspectTransactionHosts {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
    /// Preview actual configured HTTP effect fingerprints without publications.
    InspectConfiguredHttpEffects {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
}

/// Handles the supported standalone node commands.
#[must_use]
pub fn main_entry() -> ExitCode {
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
        Command::CheckConfig { config } => run_check_config(&config),
        Command::Serve { config } => run_serve(&config),
        Command::InspectTransactionHosts { config } => run_inspection(&config),
        Command::InspectConfiguredHttpEffects { config } => run_http_effect_inspection(&config),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => report_failure(failure),
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn run_inspection(path: &std::path::Path) -> Result<(), Failure> {
    inspection::run(path)
}
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn run_inspection(_path: &std::path::Path) -> Result<(), Failure> {
    Err(Failure::new("platform", PlatformErrorCode::Unavailable))
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn run_http_effect_inspection(path: &std::path::Path) -> Result<(), Failure> {
    inspection::http_effects(path)
}
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn run_http_effect_inspection(_path: &std::path::Path) -> Result<(), Failure> {
    Err(Failure::new("platform", PlatformErrorCode::Unavailable))
}

#[cfg(target_os = "linux")]
fn run_check_config(path: &std::path::Path) -> Result<(), Failure> {
    let settings = crate::config::NodeConfig::load(path)
        .and_then(|config| config.derive())
        .map_err(|error| Failure::new("configuration", error.code))?;
    let report = settings
        .check_config()
        .map_err(|error| Failure::new("execution-profile", error.code))?;
    status::configuration(&report)
}

#[cfg(not(target_os = "linux"))]
fn run_check_config(_path: &std::path::Path) -> Result<(), Failure> {
    Err(Failure::new("platform", PlatformErrorCode::Unavailable))
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
