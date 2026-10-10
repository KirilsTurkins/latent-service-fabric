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
    let (config, reload) = NodeConfig::load_with_stream_reload(path)
        .map_err(|error| Failure::new("configuration", error.code))?;
    let settings = config
        .derive()
        .map_err(|error| Failure::new("configuration", error.code))?;
    let runtime_timeout = settings.shutdown_grace;
    let threads = RuntimeThreads::default();
    let control_threads = Arc::clone(&threads.control);
    let invocation_threads = Arc::clone(&threads.invocation);
    let control = runtime(
        settings.control_workers,
        settings.control_blocking_threads(),
        "latent-control",
        &threads.control,
    )?;
    let invocation = match runtime(
        settings.runtime_workers,
        1,
        "latent-invocation",
        &threads.invocation,
    ) {
        Ok(runtime) => runtime,
        Err(error) => {
            control.shutdown_timeout(runtime_timeout);
            return Err(error);
        }
    };
    let result = invocation.block_on(serve(settings, control.handle().clone(), threads, reload));
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
    blocking: usize,
    name: &'static str,
    counter: &Arc<AtomicUsize>,
) -> Result<Runtime, Failure> {
    let started = Arc::clone(counter);
    let stopped = Arc::clone(counter);
    Builder::new_multi_thread()
        .worker_threads(workers)
        .max_blocking_threads(blocking)
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
    reload: Option<crate::config::StreamReloadGuard>,
) -> Result<ShutdownReport, Failure> {
    let mut signals = StopSignals::new(reload.is_some())?;
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
    let mut node = StandaloneNode::start(settings, control, threads)
        .await
        .map_err(|error| Failure::new("startup", error.code))?;
    let ready = node
        .inventory()
        .is_ok_and(|inventory| inventory.health.ready);
    let monitoring = match status::started(&node_id, &node, ready) {
        Ok(()) => signals.wait(&node_id, &mut node, reload.as_ref()).await,
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
    reload: Option<Signal>,
    publish_bindings: Option<Signal>,
    drain_streams: Option<Signal>,
}

impl StopSignals {
    fn new(streams_enabled: bool) -> Result<Self, Failure> {
        Ok(Self {
            interrupt: signal(SignalKind::interrupt())
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
            terminate: signal(SignalKind::terminate())
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
            reload: streams_enabled
                .then(|| signal(SignalKind::hangup()))
                .transpose()
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
            publish_bindings: streams_enabled
                .then(|| signal(SignalKind::user_defined1()))
                .transpose()
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
            drain_streams: streams_enabled
                .then(|| signal(SignalKind::user_defined2()))
                .transpose()
                .map_err(|_| Failure::new("signal", PlatformErrorCode::Unavailable))?,
        })
    }

    async fn wait(
        &mut self,
        node_id: &str,
        node: &mut StandaloneNode,
        reload: Option<&crate::config::StreamReloadGuard>,
    ) -> Result<(), Failure> {
        let _ = (node_id, reload);
        let mut tick = tokio::time::interval(Duration::from_millis(250));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                biased;
                signal = self.interrupt.recv() => return signal_received(signal),
                signal = self.terminate.recv() => return signal_received(signal),
                received = stream_signal(&mut self.reload) => {
                    signal_received(received)?;
                    #[cfg(all(target_arch = "x86_64", feature = "development-outbound-streams"))]
                    if let Some(guard) = reload {
                        let result = tokio::select! {
                            biased;
                            signal = self.interrupt.recv() => return signal_received(signal),
                            signal = self.terminate.recv() => return signal_received(signal),
                            result = node.reload_outbound_streams(guard) => result,
                        };
                        status::stream_control(node_id, result.as_ref(), node.outbound_stream_control_status().ok().as_ref())?;
                    }
                }
                received = stream_signal(&mut self.publish_bindings) => {
                    signal_received(received)?;
                    #[cfg(all(target_arch = "x86_64", feature = "development-outbound-streams"))]
                    if let Some(guard) = reload {
                        let result = tokio::select! {
                            biased;
                            signal = self.interrupt.recv() => return signal_received(signal),
                            signal = self.terminate.recv() => return signal_received(signal),
                            result = node.publish_outbound_stream_bindings(guard) => result,
                        };
                        status::stream_control(node_id, result.as_ref(), node.outbound_stream_control_status().ok().as_ref())?;
                    }
                }
                received = stream_signal(&mut self.drain_streams) => {
                    signal_received(received)?;
                    #[cfg(all(target_arch = "x86_64", feature = "development-outbound-streams"))]
                    if let Some(guard) = reload {
                        let result = tokio::select! {
                            biased;
                            signal = self.interrupt.recv() => return signal_received(signal),
                            signal = self.terminate.recv() => return signal_received(signal),
                            result = node.drain_outbound_streams(guard) => result,
                        };
                        status::stream_control(node_id, result.as_ref(), node.outbound_stream_control_status().ok().as_ref())?;
                    }
                }
                _ = tick.tick() => {
                    if !node.is_running() {
                        return Err(Failure::new("server", PlatformErrorCode::Unavailable));
                    }
                }
            }
        }
    }
}

async fn stream_signal(signal: &mut Option<Signal>) -> Option<()> {
    match signal {
        Some(signal) => signal.recv().await,
        None => std::future::pending().await,
    }
}

fn signal_received(signal: Option<()>) -> Result<(), Failure> {
    signal.ok_or_else(|| Failure::new("signal", PlatformErrorCode::Unavailable))
}
