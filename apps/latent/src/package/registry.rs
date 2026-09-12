//! One explicit registry owner and one absolute deadline per CLI transfer.
mod budget;
mod data;
mod profile;
#[cfg(test)]
mod tests;
mod transfer;

use crate::{
    args::{Cli, PackageCommand},
    error::Failure,
    output::Outcome,
};
use latent_oci::HttpOciRegistry;
use std::time::Duration;
use tokio::time::Instant;

const MAX_PACKAGE: usize = 32 * 1024 * 1024;
const PACKAGE_RESERVATION: usize = MAX_PACKAGE + 2 * 256 * 1024;
const MAX_GRAPH_BYTES: usize = 128 * 1024 * 1024;

pub(super) fn execute(cli: &Cli, command: &PackageCommand) -> Result<Outcome, Failure> {
    let duration = Duration::from_millis(cli.rpc_timeout_ms.unwrap_or(60_000));
    let deadline = Instant::now() + duration;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|_| {
            invalid(
                "registry-runtime",
                "The bounded registry runtime is unavailable.",
            )
        })?;
    let result=runtime.block_on(async {
        let path=match command {
            PackageCommand::Push(args)=>&args.registry_profile,
            PackageCommand::Pull(args)=>&args.registry_profile,
            _=>return Err(invalid("registry-command", "A package transfer command is required.")),
        };
        let configured=profile::load(path,cli,duration)?;
        let reference=match command {PackageCommand::Push(a)=>&a.reference,PackageCommand::Pull(a)=>&a.reference,_=>unreachable!()};
        validate_reference(reference)?;
        check(deadline)?;
        let registry=HttpOciRegistry::new(configured.config).map_err(super::failure)?;
        let budget=budget::Budget::new(MAX_GRAPH_BYTES);
        let mut progress=transfer::Progress::default();
        let result={
            let work=transfer::run(&registry,configured.reference,command,&budget,&mut progress,deadline);
            tokio::pin!(work);
            tokio::select! {
                biased;
                signal=tokio::signal::ctrl_c()=>Err(if signal.is_ok() {Failure::interrupted(false)} else {invalid("registry-signal", "The interrupt handler is unavailable.")}),
                ()=tokio::time::sleep_until(deadline)=>Err(timeout()),
                result=&mut work=>result,
            }
        };
        let result=result.and_then(|value| { check(deadline)?; Ok(value) });
        // Cleanup has its own finite grace; expiry never claims upload DELETE
        // completed. No mutation is retried, including a lost manifest reply.
        let cleanup_deadline=(Instant::now()+Duration::from_secs(5)).min(deadline+Duration::from_secs(5));
        let cleanup=registry.shutdown(cleanup_deadline).await.is_ok();
        let mut result=match result {
            Ok(value) if cleanup=>Ok(value),
            Ok(_)=>Err(Failure::transport("registry-cleanup-incomplete", "Transfer replies were received but registry cleanup did not finish.")),
            Err(error)=>Err(error),
        };
        if let Err(error)=&mut result {
            error.request_dispatched=progress.dispatched;
            error.outcome_known=progress.uncertain.is_none();
            error.data=progress.summary(cleanup);
        }
        result
    });
    runtime.shutdown_timeout(Duration::from_secs(1));
    result
}

fn check(deadline: Instant) -> Result<(), Failure> {
    if Instant::now() >= deadline {
        Err(timeout())
    } else {
        Ok(())
    }
}
fn timeout() -> Failure {
    Failure::transport(
        "registry-deadline",
        "The package transfer deadline expired.",
    )
}
fn invalid(code: &'static str, message: &'static str) -> Failure {
    Failure::local(code, message)
}
fn limit() -> Failure {
    invalid(
        "registry-byte-limit",
        "The package transfer exceeds its fixed byte or count limit.",
    )
}
fn association() -> Failure {
    invalid(
        "registry-association",
        "The registry bytes do not match the selected package or evidence association.",
    )
}
fn validate_reference(value: &str) -> Result<(), Failure> {
    let bytes = value.as_bytes();
    let valid = if value.starts_with("sha256:") {
        value.parse::<latent_core::PackageDigest>().is_ok()
    } else {
        !bytes.is_empty()
            && bytes.len() <= 128
            && (bytes[0].is_ascii_alphanumeric() || bytes[0] == b'_')
            && bytes
                .iter()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-'))
    };
    if valid {
        Ok(())
    } else {
        Err(invalid(
            "registry-reference",
            "A bounded OCI tag or SHA-256 package digest is required.",
        ))
    }
}
