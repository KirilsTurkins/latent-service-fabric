//! Bounded private operator observation through the original startup owner.
//! This never replaces startup, grants policy or executes a business command.
use clap::Parser;
use std::{
    io::Write,
    path::PathBuf,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};

#[derive(Parser)]
struct Arguments {
    #[arg(long)]
    config: PathBuf,
    #[arg(long)]
    credential_file: PathBuf,
    #[arg(long)]
    tenant: String,
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Arguments::parse();
    let raw = latent_protected_files::read(
        &args.credential_file,
        512,
        latent_protected_files::ProtectedFilePolicy::Secret,
        "startupDiagnosisCredential",
    )
    .map_err(|error| error.code.wire_code())?;
    let credential = std::str::from_utf8(&raw)?;
    if credential.is_empty() || credential.chars().any(char::is_control) {
        return Err("bounded credential required".into());
    }
    let settings = latentd::config::NodeConfig::load(&args.config)
        .and_then(|value| value.derive())
        .map_err(|error| error.code.wire_code())?;
    let grace = settings.shutdown_grace();
    let workers = Arc::new(AtomicUsize::new(0));
    let started = Arc::clone(&workers);
    let stopped = Arc::clone(&workers);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers())
        .max_blocking_threads(settings.control_blocking_threads())
        .on_thread_start(move || {
            started.fetch_add(1, Ordering::SeqCst);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, Ordering::SeqCst);
        })
        .enable_all()
        .build()?;
    let report = runtime.block_on(latentd::standalone::StandaloneNode::diagnose_startup(
        settings,
        credential,
        &latent_core::TenantId(args.tenant),
        runtime.handle().clone(),
        latentd::standalone::RuntimeThreads::default(),
    ));
    runtime.shutdown_timeout(grace);
    if workers.load(Ordering::SeqCst) != 0 {
        return Err("owned runtime did not retire".into());
    }
    let bytes = serde_json::to_vec(&report.map_err(|error| error.code.wire_code())?)?;
    if bytes.len() > 262_144 {
        return Err("bounded report required".into());
    }
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(&bytes)?;
    stdout.write_all(b"\n")?;
    Ok(())
}
