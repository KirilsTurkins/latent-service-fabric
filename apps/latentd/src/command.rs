//! Product command dispatch.
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
    /// Inspect installed transaction hosts without listening or running a guest.
    InspectTransactionHosts {
        #[arg(long, value_name = "PATH")]
        config: PathBuf,
    },
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
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => report_failure(failure),
    }
}

#[cfg(target_os = "linux")]
fn run_inspection(path: &std::path::Path) -> Result<(), Failure> {
    let settings = crate::config::NodeConfig::load(path)
        .and_then(|value| value.derive())
        .map_err(|error| Failure::new("configuration", error.code))?;
    let grace = settings.shutdown_grace;
    let threads = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let started = std::sync::Arc::clone(&threads);
    let stopped = std::sync::Arc::clone(&threads);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers)
        .max_blocking_threads(settings.control_blocking_threads())
        .thread_name("latent-inspection")
        .on_thread_start(move || {
            started.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
        })
        .enable_all()
        .build()
        .map_err(|_| Failure::new("runtime", PlatformErrorCode::Unavailable))?;
    let result = runtime
        .block_on(
            crate::standalone::StandaloneNode::inspect_transaction_hosts(
                &settings,
                runtime.handle(),
            ),
        )
        .map_err(|error| Failure::new("inspection", error.code));
    runtime.shutdown_timeout(grace);
    if threads.load(std::sync::atomic::Ordering::SeqCst) != 0 {
        return Err(Failure::new(
            "runtime-shutdown",
            PlatformErrorCode::DeadlineExceeded,
        ));
    }
    status::inspection(&result?)
}
#[cfg(not(target_os = "linux"))]
fn run_inspection(_path: &std::path::Path) -> Result<(), Failure> {
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
