//! Minimal native reference: shared application logic over the same protobuf RPC.
//! It intentionally supplies no Wasm isolation, fuel/memory enforcement, fabric
//! scheduler, durable catalog, telemetry pipeline, or retained activation journal.

mod command;
mod server;
mod service;
#[cfg(test)]
mod tests;
mod validation;

use clap::Parser;
use std::process::ExitCode;

pub(super) fn main() -> ExitCode {
    let args = match command::Args::try_parse() {
        Ok(args) if args.validate().is_ok() => args,
        _ => {
            eprintln!("invalid native reference configuration");
            return ExitCode::FAILURE;
        }
    };
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(_) => {
            eprintln!("native reference runtime failed");
            return ExitCode::FAILURE;
        }
    };
    let result = runtime.block_on(server::run(args));
    // All application work is synchronous and finitely bounded. No compiler or
    // detached blocking task is launched by this reference.
    runtime.shutdown_timeout(std::time::Duration::from_secs(5));
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(()) => {
            eprintln!("native reference server failed");
            ExitCode::FAILURE
        }
    }
}
