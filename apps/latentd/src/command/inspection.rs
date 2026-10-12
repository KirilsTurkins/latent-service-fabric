use super::Failure;
use crate::{config::NodeConfig, standalone::StandaloneNode};
use latent_core::PlatformErrorCode;
use std::io::Write;

pub(super) fn run(path: &std::path::Path) -> Result<(), Failure> {
    run_mode(path, false)
}
pub(super) fn http_effects(path: &std::path::Path) -> Result<(), Failure> {
    run_mode(path, true)
}
fn run_mode(path: &std::path::Path, preview: bool) -> Result<(), Failure> {
    let settings = NodeConfig::load(path)
        .and_then(|config| config.derive())
        .map_err(|error| Failure::new("configuration", error.code))?;
    let grace = settings.shutdown_grace();
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers())
        .max_blocking_threads(settings.control_blocking_threads())
        .enable_all()
        .build()
        .map_err(|_| Failure::new("runtime", PlatformErrorCode::Unavailable))?;
    let encoded = if preview {
        runtime
            .block_on(StandaloneNode::inspect_configured_http_effects(
                settings,
                runtime.handle().clone(),
            ))
            .and_then(crate::standalone::ConfiguredHttpEffectInspection::encode)
    } else {
        runtime
            .block_on(StandaloneNode::inspect_transaction_hosts(
                settings,
                runtime.handle().clone(),
            ))
            .and_then(crate::standalone::NativeTransactionHostInspection::encode)
    };
    runtime.shutdown_timeout(grace);
    let encoded =
        encoded.map_err(|error| Failure::new("transaction-host-inspection", error.code))?;
    let mut output = std::io::stdout().lock();
    output
        .write_all(encoded.get())
        .and_then(|()| output.write_all(b"\n"))
        .map_err(|_| {
            Failure::new(
                "transaction-host-inspection",
                PlatformErrorCode::Unavailable,
            )
        })
}
