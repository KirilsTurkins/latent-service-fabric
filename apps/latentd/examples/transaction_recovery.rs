//! Private native operator fixture. Default diagnosis only reads the store;
//! explicit startup diagnosis runs the ordinary node owners and shutdown.
use clap::Parser;
use latent_core::TenantId;
use latentd::{
    config::NodeConfig,
    standalone::{RuntimeThreads, StandaloneNode},
};
use std::{path::PathBuf, process::ExitCode};

#[derive(Parser)]
struct Arguments {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    tenant: String,
    /// Runs normal startup and shutdown, and can advance the durable epoch.
    #[arg(long)]
    diagnose_startup: bool,
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
        .worker_threads(settings.control_workers)
        .max_blocking_threads(settings.control_blocking_threads())
        .enable_all()
        .build()
        .map_err(|_| "native-runtime-refused")?;
    let grace = settings.shutdown_grace();
    let result = if args.diagnose_startup {
        encode(runtime.block_on(StandaloneNode::diagnose_startup(
            settings,
            credential,
            &TenantId(args.tenant),
            runtime.handle().clone(),
            RuntimeThreads::default(),
        )))
    } else {
        encode(runtime.block_on(StandaloneNode::diagnose_transaction_store(
            &settings,
            credential,
            &TenantId(args.tenant),
        )))
    };
    runtime.shutdown_timeout(grace);
    println!("{}", result?);
    Ok(())
}

fn encode<T: serde::Serialize>(
    result: Result<T, latent_core::PlatformError>,
) -> Result<String, &'static str> {
    let observed = result.map_err(|_| "native-operator-diagnosis-refused")?;
    serde_json::to_string(&observed).map_err(|_| "diagnosis-encoding-refused")
}
