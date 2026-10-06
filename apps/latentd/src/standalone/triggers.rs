//! One node-owned loop drives the original bounded NATS consumer.
use super::{error, PlatformError, PlatformErrorCode};
use latent_nats::{
    triggers::{NatsTriggers, TriggerMonitor},
    EventError,
};
use latent_node::LocalActivationManager;
use std::time::Instant;
use tokio::{sync::watch, task::JoinHandle};

#[derive(Clone, Copy, Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TriggerStatus {
    pub configuration_epoch: u64,
    pub triggers: usize,
    pub accepting: bool,
    pub active_deliveries: u64,
    pub pulls: u64,
    pub executions: u64,
    pub acknowledged: u64,
    pub uncertain_acknowledgements: u64,
    pub delivery_errors: u64,
}
#[derive(Clone, Copy, Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TriggerShutdownReport {
    pub clean: bool,
    pub joined: bool,
    pub status: TriggerStatus,
}
pub(super) struct TriggerOwner {
    accepting: watch::Sender<bool>,
    stop: watch::Sender<bool>,
    monitor: TriggerMonitor,
    task: Option<JoinHandle<(NatsTriggers, Result<(), EventError>)>>,
}
impl TriggerOwner {
    pub fn start(poller: NatsTriggers, manager: LocalActivationManager) -> Self {
        let monitor = poller.monitor();
        let (accepting, ready) = watch::channel(false);
        let (stop, stopped) = watch::channel(false);
        Self {
            accepting,
            stop,
            monitor,
            task: Some(tokio::spawn(run(poller, manager, ready, stopped))),
        }
    }
    pub fn start_accepting(&self) {
        self.accepting.send_replace(true);
    }
    pub fn stop_accepting(&self) {
        self.accepting.send_replace(false);
    }
    pub fn snapshot(&self) -> TriggerStatus {
        let snapshot = self.monitor.snapshot();
        TriggerStatus {
            configuration_epoch: snapshot.configuration_epoch,
            triggers: snapshot.triggers,
            accepting: *self.accepting.borrow(),
            active_deliveries: snapshot.active_deliveries,
            pulls: snapshot.pulls,
            executions: snapshot.executions,
            acknowledged: snapshot.acknowledged,
            uncertain_acknowledgements: snapshot.uncertain_acknowledgements,
            delivery_errors: snapshot.delivery_errors,
        }
    }
    pub fn is_finished(&self) -> bool {
        self.task.as_ref().is_none_or(JoinHandle::is_finished)
    }
    pub async fn shutdown(
        mut self,
        deadline: Instant,
    ) -> Result<TriggerShutdownReport, PlatformError> {
        self.stop_accepting();
        self.stop.send_replace(true);
        // The original owner joins its actual task. Completion after the
        // original cutoff makes shutdown unsuccessful without hiding ownership.
        let (poller, outcome) =
            self.task
                .take()
                .expect("owned input task")
                .await
                .map_err(|_| {
                    error(
                        PlatformErrorCode::Unavailable,
                        "transactional-input-task-failed",
                    )
                })?;
        let status = self.snapshot();
        let clean = outcome.is_ok() && status.active_deliveries == 0 && Instant::now() <= deadline;
        drop(poller);
        Ok(TriggerShutdownReport {
            clean,
            joined: true,
            status,
        })
    }
}
impl Drop for TriggerOwner {
    fn drop(&mut self) {
        self.stop_accepting();
        self.stop.send_replace(true);
    }
}
async fn stop(stop: &mut watch::Receiver<bool>) {
    loop {
        if *stop.borrow() || stop.changed().await.is_err() {
            return;
        }
    }
}
async fn run(
    mut poller: NatsTriggers,
    manager: LocalActivationManager,
    mut ready: watch::Receiver<bool>,
    mut stopped: watch::Receiver<bool>,
) -> (NatsTriggers, Result<(), EventError>) {
    let delay = std::time::Duration::from_millis(poller.config().poll_interval_millis);
    loop {
        if *stopped.borrow() || stopped.has_changed().is_err() {
            break;
        }
        if !*ready.borrow() {
            tokio::select! { biased; () = stop(&mut stopped) => break,
                changed = ready.changed() => { if changed.is_err() { break; } }
            }
            continue;
        }
        if matches!(
            Box::pin(poller.step(&manager, &mut stopped)).await,
            Err(EventError::Cancelled)
        ) {
            break;
        }
        tokio::select! { biased; () = stop(&mut stopped) => break,
            changed = ready.changed() => { if changed.is_err() { break; } },
            () = tokio::time::sleep(delay) => {}
        }
    }
    let result = poller.close_idle();
    (poller, result)
}
