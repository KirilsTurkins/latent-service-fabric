//! Common PID1 child/transport owner for the infrastructure comparison.

mod child;
mod command;
mod forward;
mod observe;
mod output;
mod streams;
mod supervisor;

use clap::Parser;
use std::process::ExitCode;

type Result<T> = std::result::Result<T, &'static str>;

pub(super) fn main() -> ExitCode {
    let origin = std::time::Instant::now();
    let args = match command::Args::try_parse() {
        Ok(args) if args.validate().is_ok() => args,
        _ => {
            eprintln!("invalid container wrapper configuration");
            return ExitCode::FAILURE;
        }
    };
    let Ok(runtime) = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
    else {
        eprintln!("container wrapper runtime failed");
        return ExitCode::FAILURE;
    };
    let result = runtime.block_on(supervisor::run(&args, origin));
    runtime.shutdown_timeout(std::time::Duration::from_secs(5));
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(reason) => {
            eprintln!("container wrapper failed: {reason}");
            ExitCode::FAILURE
        }
    }
}
