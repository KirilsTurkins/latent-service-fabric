use super::{
    increment, mpsc, oneshot, pipeline_error, Arc, Ordering, PipelineCommand, PipelineCounters,
    TelemetryHandle, TelemetryPipelineConfig, TelemetryRecord,
};
use crate::TelemetrySink;
use latent_core::{PlatformError, PlatformErrorCode};
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::task::JoinHandle;

/// Owns the single worker. Drop closes producers immediately and aborts the task;
/// its pending export and queued records are dropped on the runtime's next poll.
#[must_use = "retain the runtime owner while telemetry should be exported"]
pub struct TelemetryRuntime {
    sender: mpsc::Sender<PipelineCommand>,
    task: Option<JoinHandle<()>>,
    counters: Arc<PipelineCounters>,
    config: TelemetryPipelineConfig,
}
impl std::fmt::Debug for TelemetryRuntime {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TelemetryRuntime")
            .field(
                "worker_finished",
                &self.task.as_ref().is_none_or(JoinHandle::is_finished),
            )
            .finish_non_exhaustive()
    }
}
impl TelemetryRuntime {
    pub fn spawn(
        config: TelemetryPipelineConfig,
        sink: Arc<dyn TelemetrySink>,
    ) -> Result<(TelemetryHandle, Self), PlatformError> {
        config.validate()?;
        let runtime = tokio::runtime::Handle::try_current().map_err(|_| {
            pipeline_error(
                PlatformErrorCode::Unavailable,
                "telemetry requires an async runtime",
            )
        })?;
        let (sender, receiver) = mpsc::channel(config.queue_capacity);
        let counters = Arc::new(PipelineCounters::default());
        let task = runtime.spawn(worker(receiver, sink, config, Arc::clone(&counters)));
        let handle = TelemetryHandle {
            sender: sender.clone(),
            counters: Arc::clone(&counters),
            config,
        };
        Ok((
            handle,
            Self {
                sender,
                task: Some(task),
                counters,
                config,
            },
        ))
    }
    /// Stops accepting producers, drains preceding records, then joins the worker.
    /// A timeout aborts it; dropping this shutdown future also aborts it.
    pub async fn shutdown(mut self) -> Result<(), PlatformError> {
        self.counters.closed.store(true, Ordering::Release);
        let result = tokio::time::timeout(self.config.shutdown_timeout, async {
            let (sender, receiver) = oneshot::channel();
            self.sender
                .send(PipelineCommand::Shutdown(sender))
                .await
                .map_err(|_| closed())?;
            receiver.await.map_err(|_| closed())?;
            if let Some(task) = self.task.as_mut() {
                task.await.map_err(|_| {
                    pipeline_error(PlatformErrorCode::Internal, "telemetry worker failed")
                })?;
            }
            Ok(())
        })
        .await;
        match result {
            Ok(Ok(())) => {
                self.task.take();
                Ok(())
            }
            Ok(Err(error)) => Err(error),
            Err(_) => {
                increment(&self.counters.shutdown_timeouts);
                Err(pipeline_error(
                    PlatformErrorCode::DeadlineExceeded,
                    "telemetry shutdown timed out",
                ))
            }
        }
    }
    pub fn abort(self) {
        drop(self);
    }
}
impl Drop for TelemetryRuntime {
    fn drop(&mut self) {
        self.counters.closed.store(true, Ordering::Release);
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}
fn closed() -> PlatformError {
    pipeline_error(PlatformErrorCode::Unavailable, "telemetry worker is closed")
}

async fn worker(
    mut receiver: mpsc::Receiver<PipelineCommand>,
    sink: Arc<dyn TelemetrySink>,
    config: TelemetryPipelineConfig,
    counters: Arc<PipelineCounters>,
) {
    let _close = CloseOnDrop(Arc::clone(&counters));
    let mut shutdown_acknowledge = None;
    while let Some(command) = receiver.recv().await {
        match command {
            PipelineCommand::Record(record) => {
                let export = async {
                    match record {
                        TelemetryRecord::Metric(point) => sink.emit_metric(point).await,
                        TelemetryRecord::Log(record) => sink.emit_log(record).await,
                        TelemetryRecord::Span(span) => sink.emit_span(span).await,
                    }
                };
                match tokio::time::timeout(
                    config.export_timeout,
                    CatchExport::new(export, Arc::clone(&counters)),
                )
                .await
                {
                    Ok(Ok(Ok(()))) => increment(&counters.exported),
                    Ok(_) => increment(&counters.sink_failures),
                    Err(_) => increment(&counters.sink_timeouts),
                }
            }
            PipelineCommand::Flush(acknowledge) => {
                let _ = acknowledge.send(());
            }
            PipelineCommand::Shutdown(acknowledge) => {
                receiver.close();
                shutdown_acknowledge = Some(acknowledge);
            }
        }
    }
    if let Some(acknowledge) = shutdown_acknowledge {
        let _ = acknowledge.send(());
    }
}
struct CloseOnDrop(Arc<PipelineCounters>);
impl Drop for CloseOnDrop {
    fn drop(&mut self) {
        self.0.closed.store(true, Ordering::Release);
    }
}

/// Catches exporter construction, polling, and destructor panics without a
/// separate task. Exporter code must not block or panic while already unwinding.
struct CatchExport<F> {
    future: Option<Pin<Box<F>>>,
    counters: Arc<PipelineCounters>,
}
impl<F> CatchExport<F> {
    fn new(future: F, counters: Arc<PipelineCounters>) -> Self {
        Self {
            future: Some(Box::pin(future)),
            counters,
        }
    }
    fn drop_inner(&mut self) -> Result<(), ()> {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(self.future.take()))).map_err(
            |_| {
                increment(&self.counters.worker_panics);
            },
        )
    }
}
impl<F: Future> Future for CatchExport<F> {
    type Output = Result<F::Output, ()>;
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            this.future
                .as_mut()
                .expect("live exporter future")
                .as_mut()
                .poll(context)
        }));
        match result {
            Ok(Poll::Pending) => Poll::Pending,
            Ok(Poll::Ready(value)) => Poll::Ready(this.drop_inner().map(|()| value)),
            Err(_) => {
                increment(&this.counters.worker_panics);
                let _ = this.drop_inner();
                Poll::Ready(Err(()))
            }
        }
    }
}
impl<F> Drop for CatchExport<F> {
    fn drop(&mut self) {
        let _ = self.drop_inner();
    }
}
