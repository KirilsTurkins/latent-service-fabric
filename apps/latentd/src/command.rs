//! Product command dispatch, separate from the historical Phase 0 entry point.

#[cfg(target_os = "linux")]
mod migrate;
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
    /// Migrate an offline catalog to tenant-scoped publication storage.
    MigrateCatalog {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
        #[command(flatten)]
        limits: MigrationOptions,
    },
    /// Run the finite, non-production Phase 0 validation tools.
    #[command(name = "phase0-spike", visible_alias = "spike")]
    Phase0Spike,
}

#[derive(clap::Args)]
struct MigrationOptions {
    #[arg(long, default_value_t = 32, value_parser = clap::value_parser!(u16).range(1..=1024))]
    batch_size: u16,
    #[arg(long, default_value_t = 268_435_456)]
    max_metadata_bytes: usize,
    #[arg(long, default_value_t = 8_589_934_592)]
    max_disk_bytes: u64,
    #[arg(long, default_value_t = 1_000_000)]
    max_files: usize,
    #[arg(long, default_value_t = 68_719_476_736)]
    max_work_bytes: u64,
}
impl MigrationOptions {
    fn limits(self) -> latent_artifacts::CatalogMigrationLimits {
        latent_artifacts::CatalogMigrationLimits {
            batch_size: usize::from(self.batch_size),
            max_metadata_bytes: self.max_metadata_bytes,
            max_disk_bytes: self.max_disk_bytes,
            max_files: self.max_files,
            max_work_bytes: self.max_work_bytes,
        }
    }
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
        Command::CheckConfig { config } => run_check_config(&config),
        Command::Serve { config } => run_serve(&config),
        Command::MigrateCatalog { config, limits } => run_migrate(&config, limits.limits()),
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

#[cfg(target_os = "linux")]
fn run_migrate(
    path: &std::path::Path,
    limits: latent_artifacts::CatalogMigrationLimits,
) -> Result<(), Failure> {
    migrate::run(path, limits)
}
#[cfg(not(target_os = "linux"))]
fn run_migrate(
    _path: &std::path::Path,
    _limits: latent_artifacts::CatalogMigrationLimits,
) -> Result<(), Failure> {
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
