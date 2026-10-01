//! Private native qualification helper. No compiler or guest code is run here.
use clap::Parser;
use latent_core::TenantId;
use latentd::{config::NodeConfig, standalone::StandaloneNode};
use std::{path::PathBuf, process::ExitCode};

#[derive(Parser)]
struct Arguments {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    tenant: String,
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
        .worker_threads(2)
        .max_blocking_threads(1)
        .enable_all()
        .build()
        .map_err(|_| "native-runtime-refused")?;
    let result = runtime
        .block_on(StandaloneNode::diagnose_transaction_store(
            &settings,
            credential,
            &TenantId(args.tenant),
        ))
        .map_err(|_| "native-operator-diagnosis-refused");
    runtime.shutdown_timeout(settings.shutdown_grace());
    let observed = result?;
    println!(
        "{}",
        serde_json::to_string(&observed).map_err(|_| "diagnosis-encoding-refused")?
    );
    Ok(())
}
