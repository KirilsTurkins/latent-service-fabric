//! Bounded offline actions use the authenticated current store owners.
use super::Failure;
use crate::{
    config::NodeConfig,
    standalone::{RuntimeThreads, StandaloneNode},
};
use clap::{Args, Parser};
use latent_core::{PlatformErrorCode, TenantId};
use std::{io::Write, path::PathBuf, process::ExitCode};

#[derive(Args)]
pub(super) struct Arguments {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    tenant: String,
    /// Runs normal startup and shutdown, and can advance the durable epoch.
    #[arg(
        long,
        required_unless_present = "request_file",
        conflicts_with = "request_file"
    )]
    diagnose_startup: bool,
    /// Closed native action data. Signed selection and current policy remain required.
    #[arg(long, conflicts_with = "diagnose_startup")]
    request_file: Option<PathBuf>,
}

pub(super) fn installed(args: Arguments) -> Result<(), Failure> {
    if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        return Err(unavailable("platform"));
    }
    run(args)
}

const fn unavailable(stage: &'static str) -> Failure {
    Failure::new(stage, PlatformErrorCode::Unavailable)
}

#[derive(Parser)]
struct ExampleArguments {
    #[command(flatten)]
    recovery: Arguments,
}

#[must_use]
pub fn transaction_recovery_example_entry() -> ExitCode {
    match run(ExampleArguments::parse().recovery) {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            eprintln!("transaction-recovery-helper: {}", failure.stage);
            ExitCode::FAILURE
        }
    }
}
fn run(args: Arguments) -> Result<(), Failure> {
    let settings = NodeConfig::load(&args.config)
        .and_then(|input| input.derive())
        .map_err(|error| Failure::new("protected-configuration-refused", error.code))?;
    let bytes = latent_protected_files::read(
        &args.credential_file,
        512,
        latent_protected_files::ProtectedFilePolicy::Secret,
        "recoveryFixtureCredential",
    )
    .map_err(|_| unavailable("protected-credential-refused"))?;
    let credential =
        std::str::from_utf8(&bytes).map_err(|_| unavailable("credential-encoding-refused"))?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers())
        .max_blocking_threads(settings.control_blocking_threads())
        .enable_all()
        .build()
        .map_err(|_| unavailable("native-runtime-refused"))?;
    let grace = settings.shutdown_grace();
    let result = if let Some(path) = &args.request_file {
        recover(&runtime, settings, credential, &args.tenant, path)
    } else if args.diagnose_startup {
        encode(runtime.block_on(StandaloneNode::diagnose_startup(
            settings,
            credential,
            &TenantId(args.tenant),
            runtime.handle().clone(),
            RuntimeThreads::default(),
        )))
        .map(Output::Diagnosis)
    } else {
        Err(unavailable("native-recovery-mode-required"))
    };
    runtime.shutdown_timeout(grace);
    let result = result?;
    let mut output = std::io::stdout().lock();
    output
        .write_all(result.bytes())
        .and_then(|()| output.write_all(b"\n"))
        .map_err(|_| unavailable("diagnosis-output-refused"))?;
    Ok(())
}

enum Output {
    Diagnosis(String),
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    Recovery(latent_core::native_capacity::NativeBuffer<Vec<u8>>),
}
impl Output {
    fn bytes(&self) -> &[u8] {
        match self {
            Self::Diagnosis(value) => value.as_bytes(),
            #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
            Self::Recovery(value) => value.get(),
        }
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn recover(
    runtime: &tokio::runtime::Runtime,
    settings: crate::config::NodeSettings,
    credential: &str,
    tenant: &str,
    path: &std::path::Path,
) -> Result<Output, Failure> {
    let bytes = latent_protected_files::read(
        path,
        16_384,
        latent_protected_files::ProtectedFilePolicy::Integrity,
        "nativeRecoveryRequest",
    )
    .map_err(|_| unavailable("protected-request-refused"))?;
    let request = crate::standalone::NativeRecoveryRequest::decode(&bytes)
        .map_err(|error| Failure::new("native-request-refused", error.code))?;
    let report = runtime
        .block_on(StandaloneNode::recover_namespace(
            settings,
            credential,
            &TenantId(tenant.into()),
            request,
            runtime.handle().clone(),
        ))
        .map_err(|error| Failure::new("native-operator-recovery-refused", error.code))?;
    report
        .encode()
        .map(Output::Recovery)
        .map_err(|_| unavailable("recovery-encoding-refused"))
}
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn recover(
    _runtime: &tokio::runtime::Runtime,
    _settings: crate::config::NodeSettings,
    _credential: &str,
    _tenant: &str,
    _path: &std::path::Path,
) -> Result<Output, Failure> {
    Err(unavailable("native-recovery-platform-refused"))
}

fn encode<T: serde::Serialize>(
    result: Result<T, latent_core::PlatformError>,
) -> Result<String, Failure> {
    let observed =
        result.map_err(|error| Failure::new("native-operator-diagnosis-refused", error.code))?;
    let mut bytes = BoundedOutput(Vec::new());
    serde_json::to_writer(&mut bytes, &observed)
        .map_err(|_| unavailable("diagnosis-encoding-refused"))?;
    String::from_utf8(bytes.0).map_err(|_| unavailable("diagnosis-encoding-refused"))
}

struct BoundedOutput(Vec<u8>);
impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let maximum = 4 * 1024 * 1024;
        if bytes.len() > maximum - self.0.len() {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.0
            .try_reserve(bytes.len())
            .map_err(|_| std::io::ErrorKind::OutOfMemory)?;
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
