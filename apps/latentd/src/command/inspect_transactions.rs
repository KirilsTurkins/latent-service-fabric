use super::Failure;
use crate::{config::NodeConfig, standalone::StandaloneNode};
use latent_core::PlatformErrorCode;
use std::{io::Write, path::Path};

pub(super) fn run(path: &Path) -> Result<(), Failure> {
    let settings = NodeConfig::load(path)
        .and_then(|config| config.derive())
        .map_err(|error| Failure::new("configuration", error.code))?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(settings.control_workers)
        .max_blocking_threads(settings.control_blocking_threads())
        .thread_name("latent-host-inspection")
        .enable_all()
        .build()
        .map_err(|_| Failure::new("runtime", PlatformErrorCode::Unavailable))?;
    let result = runtime.block_on(StandaloneNode::inspect_transaction_hosts(
        &settings,
        runtime.handle(),
    ));
    runtime.shutdown_timeout(settings.shutdown_grace);
    let report = result.map_err(|error| Failure::new("transaction-host-inspection", error.code))?;
    let mut bytes = serde_json::to_vec(&report)
        .map_err(|_| Failure::new("status", PlatformErrorCode::Internal))?;
    if bytes.len() >= 256 * 1024 {
        return Err(Failure::new("status", PlatformErrorCode::ResourceExhausted));
    }
    bytes.push(b'\n');
    std::io::stdout()
        .lock()
        .write_all(&bytes)
        .map_err(|_| Failure::new("status", PlatformErrorCode::Unavailable))
}
