//! Private native startup diagnostic. It runs ordinary owners and shutdown;
//! unsupported offline modes refuse without opening the configured store.
use clap::Parser;
use latent_core::TenantId;
use latentd::{
    config::NodeConfig,
    standalone::{RuntimeThreads, StandaloneNode},
};
use std::{io::Write, path::PathBuf, process::ExitCode};

#[derive(Parser)]
struct Arguments {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    tenant: String,
    /// Runs normal startup and shutdown, and can advance the durable epoch.
    #[arg(long, conflicts_with = "request_file")]
    diagnose_startup: bool,
    /// Closed native action data. Signed selection and current policy remain required.
    #[arg(long, conflicts_with = "diagnose_startup")]
    request_file: Option<PathBuf>,
}
fn main() -> ExitCode {
    match run(Arguments::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(code) => {
            eprintln!("transaction-recovery-helper: {code}");
            ExitCode::FAILURE
        }
    }
}
fn run(args: Arguments) -> Result<(), &'static str> {
    if args.request_file.is_some() || !args.diagnose_startup {
        return Err("offline-recovery-adapter-unavailable");
    }
    let settings = NodeConfig::load(&args.config)
        .and_then(|input| input.derive())
        .map_err(|_| "protected-configuration-refused")?;
    let bytes = latent_protected_files::read(
        &args.credential_file,
        512,
        latent_protected_files::ProtectedFilePolicy::Secret,
        "recoveryFixtureCredential",
    )
    .map_err(|_| "protected-credential-refused")?;
    let credential = std::str::from_utf8(&bytes).map_err(|_| "credential-encoding-refused")?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers())
        .max_blocking_threads(settings.control_blocking_threads())
        .enable_all()
        .build()
        .map_err(|_| "native-runtime-refused")?;
    let grace = settings.shutdown_grace();
    let result = encode(runtime.block_on(StandaloneNode::diagnose_startup(
        settings,
        credential,
        &TenantId(args.tenant),
        runtime.handle().clone(),
        RuntimeThreads::default(),
    )));
    runtime.shutdown_timeout(grace);
    println!("{}", result?);
    Ok(())
}

fn encode<T: serde::Serialize>(
    result: Result<T, latent_core::PlatformError>,
) -> Result<String, &'static str> {
    let observed = result.map_err(|_| "native-operator-diagnosis-refused")?;
    let mut bytes = BoundedOutput(Vec::new());
    serde_json::to_writer(&mut bytes, &observed).map_err(|_| "diagnosis-encoding-refused")?;
    String::from_utf8(bytes.0).map_err(|_| "diagnosis-encoding-refused")
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
