use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_core::PlatformErrorCode;
use tokio::runtime::{Builder, Runtime};
use tokio::signal::unix::{signal, Signal, SignalKind};

use crate::config::{NodeConfig, NodeSettings};
use crate::standalone::{RuntimeThreads, ShutdownReport, StandaloneNode};

use super::{status, Failure};

pub(super) fn run(path: &Path) -> Result<(), Failure> {
    // No runtime, directory ownership or listener exists before derivation.
    let settings = NodeConfig::load(path)
        .and_then(|config| config.derive())
        .map_err(|error| Failure::new("configuration", error.code))?;
    let runtime_timeout = settings.shutdown_grace;
    let threads = RuntimeThreads::default();
    let control_threads = Arc::clone(&threads.control);
    let invocation_threads = Arc::clone(&threads.invocation);
    let control = runtime(settings.control_workers, "latent-control", &threads.control)?;
    let invocation = match runtime(
        settings.runtime_workers,
        "latent-invocation",
        &threads.invocation,
    ) {
        Ok(runtime) => runtime,
        Err(error) => {
            control.shutdown_timeout(runtime_timeout);
            return Err(error);
        }
    };
    let result = invocation.block_on(serve(settings, control.handle().clone(), threads));
    // Runtime owners stay outside async. A timeout bounds waiting; it does not
    // prove that an uncooperative OS or blocking operation was forcibly stopped.
    control.shutdown_timeout(runtime_timeout);
    invocation.shutdown_timeout(runtime_timeout);
    if control_threads.load(Ordering::SeqCst) != 0 || invocation_threads.load(Ordering::SeqCst) != 0
    {
        return Err(Failure::new(
            "runtime-shutdown",
            PlatformErrorCode::DeadlineExceeded,
        ));
    }
    status::stopped(&result?)
}

fn runtime(
    workers: usize,
    name: &'static str,
    counter: &Arc<AtomicUsize>,
) -> Result<Runtime, Failure> {
    let started = Arc::clone(counter);
    let stopped = Arc::clone(counter);
    Builder::new_multi_thread()
        .worker_threads(workers)
        .max_blocking_threads(1)
        .thread_name(name)
        .on_thread_start(move || {
            started.fetch_add(1, Ordering::SeqCst);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, Ordering::SeqCst);
        })
        .enable_all()
        .build()
        .map_err(|_| Failure::new("runtime", PlatformErrorCode::Unavailable))
}

async fn serve(
    settings: NodeSettings,
    control: tokio::runtime::Handle,
    threads: RuntimeThreads,
) -> Result<ShutdownReport, Failure> {
    let mut signals = StopSignals::new()?;
    let node_id = settings.node.id.0.clone();
    let shutdown_timeout = settings
        .shutdown_grace
        .checked_mul(2)
        .and_then(|duration| duration.checked_add(settings.transport.shutdown_timeout))
        .and_then(|duration| {
            settings
                .manager
                .cleanup_grace
                .checked_mul(2)
                .and_then(|cleanup| duration.checked_add(cleanup))
        })
        .and_then(|duration| duration.checked_add(settings.telemetry.shutdown_timeout))
        .and_then(|duration| duration.checked_add(Duration::from_secs(1)))
        .ok_or_else(|| Failure::new("configuration", PlatformErrorCode::InvalidArgument))?;
    let node = StandaloneNode::start(settings, control, threads)
        .await
        .map_err(|error| Failure::new("startup", error.code))?;
    let ready = node
        .inventory()
        .is_ok_and(|inventory| inventory.health.ready);
    let monitoring = match status::started(&node_id, node.endpoint(), ready) {
        Ok(()) => signals.wait(&node).await,
        Err(error) => Err(error),
    };
    let report = tokio::time::timeout(shutdown_timeout, node.shutdown())
        .await
        .map_err(|_| Failure::new("shutdown", PlatformErrorCode::DeadlineExceeded))?
        .map_err(|error| Failure::new("shutdown", error.code))?;
    // A server failure remains an unsuccessful exit even if cleanup succeeded.
    monitoring?;
    Ok(report)
}

struct StopSignals {
    interrupt: Signal,
    terminate: Signal,
}

impl StopSignals {
    fn new() -> Result<Self, Failure> {
        Ok(Self {
            interrupt: signal(SignalKind::interrupt())
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
            terminate: signal(SignalKind::terminate())
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
        })
    }

    async fn wait(&mut self, node: &StandaloneNode) -> Result<(), Failure> {
        let mut tick = tokio::time::interval(Duration::from_millis(250));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                biased;
                signal = self.interrupt.recv() => return signal_received(signal),
                signal = self.terminate.recv() => return signal_received(signal),
                _ = tick.tick() => {
                    if !node.is_running() {
                        return Err(Failure::new("server", PlatformErrorCode::Unavailable));
                    }
                }
            }
        }
    }
}

fn signal_received(signal: Option<()>) -> Result<(), Failure> {
    signal.ok_or_else(|| Failure::new("signal", PlatformErrorCode::Unavailable))
}
