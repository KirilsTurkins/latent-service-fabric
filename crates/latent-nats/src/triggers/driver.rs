use super::{
    consumer::{self, Ack},
    execution::execute,
    monitor::Counters,
    Acknowledgement, NatsTriggers, TriggerStep, TriggerTerminal,
};
use crate::{network, provider::tick, EventError, Result};
use latent_node::LocalActivationManager;
use std::{
    future::Future,
    sync::{atomic::Ordering, Arc},
    time::{Duration, Instant},
};
use tokio::sync::watch;

struct Active(Arc<Counters>);
impl Drop for Active {
    fn drop(&mut self) {
        self.0.active.fetch_sub(1, Ordering::AcqRel);
    }
}
pub(super) async fn stopped(stop: &mut watch::Receiver<bool>) {
    loop {
        if *stop.borrow() || stop.changed().await.is_err() {
            return;
        }
    }
}
pub(super) async fn interruptible<T>(
    stop: &mut watch::Receiver<bool>,
    future: impl Future<Output = Result<T>>,
) -> Result<T> {
    tokio::select! { biased; ()=stopped(stop)=>Err(EventError::Cancelled), result=future=>result }
}
impl NatsTriggers {
    /// One bounded batch, with tenants rotated before each tenant's bindings.
    /// A retained report is fixed-size; it owns no socket, payload or retry task.
    pub async fn step(
        &mut self,
        manager: &LocalActivationManager,
        stop: &mut watch::Receiver<bool>,
    ) -> Result<Option<TriggerStep>> {
        if *stop.borrow() {
            return Err(EventError::Cancelled);
        }
        let Some((tenant, index)) = self.next_binding() else {
            return Ok(None);
        };
        self.retry_after[index] =
            Some(Instant::now() + Duration::from_millis(self.config.poll_interval_millis));
        // The fixed poller frame is covered by installation metadata, independent
        // of how many dormant bindings are configured.
        let result = Box::pin(self.delivery(manager, stop, tenant, index)).await;
        if let Err(error) = result {
            tick(&self.monitor.0.rejected);
            self.retry_after[index] =
                Some(Instant::now() + Duration::from_millis(self.config.redelivery_delay_millis));
            if error == EventError::Cancelled {
                return Err(error);
            }
            let report = TriggerStep {
                configuration_epoch: self.monitor.0.epoch,
                trigger_index: index,
                stream_sequence: 0,
                delivery_count: 0,
                route_generation: 0,
                terminal: TriggerTerminal::Rejected,
                acknowledgement: Acknowledgement::NotSent,
                error: Some(error),
            };
            self.monitor.record(report);
            return Ok(Some(report));
        }
        if let Ok(Some(report)) = result {
            self.monitor.record(report);
        }
        result
    }
    fn next_binding(&mut self) -> Option<(usize, usize)> {
        for _ in 0..self.tenants.len() {
            let tenant = self.next_tenant;
            self.next_tenant = (self.next_tenant + 1) % self.tenants.len();
            let row = &mut self.tenants[tenant];
            for _ in 0..row.bindings.len() {
                let index = row.bindings[row.cursor];
                row.cursor = (row.cursor + 1) % row.bindings.len();
                if self.retry_after[index].is_none_or(|time| time <= Instant::now()) {
                    return Some((tenant, index));
                }
            }
        }
        None
    }
    async fn delivery(
        &mut self,
        manager: &LocalActivationManager,
        stop: &mut watch::Receiver<bool>,
        tenant: usize,
        index: usize,
    ) -> Result<Option<TriggerStep>> {
        let (reservation, deadline, inbox) = self.reserve(manager, index)?;
        self.monitor.0.active.fetch_add(1, Ordering::AcqRel);
        let _active = Active(self.monitor.0.clone());
        let super::connection::Open {
            mut connection,
            request,
            auth,
        } = self.open(tenant, index, deadline.monotonic(), stop).await?;
        let binding = &self.config.bindings[index];
        let credential = &self.credentials[self.tenants[tenant].credential];
        interruptible(
            stop,
            consumer::check(
                connection.resource(),
                &request,
                binding,
                &self.config,
                &inbox,
            ),
        )
        .await?;
        reservation.publication_eligibility()?;
        network::check_current(credential, &auth.stamp)?;
        tick(&self.monitor.0.pulls);
        let delivery = interruptible(
            stop,
            consumer::pull(
                connection.resource(),
                &request,
                binding,
                &self.config,
                &inbox,
            ),
        )
        .await?;
        let Some((message, identity)) = delivery else {
            let _ = connection.park();
            return Ok(None);
        };
        let route_generation = reservation.revision().route_generation.0;
        let (mut terminal, mut ack, shutdown) =
            if identity.delivery > self.config.maximum_deliveries {
                drop(reservation);
                (TriggerTerminal::Exhausted, Ack::Terminate, false)
            } else {
                tick(&self.monitor.0.executions);
                execute(reservation, message.payload(), stop).await
            };
        if shutdown {
            return Ok(Some(TriggerStep {
                configuration_epoch: self.monitor.0.epoch,
                trigger_index: index,
                stream_sequence: identity.sequence,
                delivery_count: identity.delivery,
                route_generation,
                terminal,
                acknowledgement: Acknowledgement::NotSent,
                error: Some(EventError::Cancelled),
            }));
        }
        if ack == Ack::Retry && identity.delivery >= self.config.maximum_deliveries {
            terminal = TriggerTerminal::Exhausted;
            ack = Ack::Terminate;
        }
        if terminal == TriggerTerminal::Exhausted {
            tick(&self.monitor.0.exhausted);
        }
        let (acknowledgement, error) = super::acknowledgement::finish(
            super::acknowledgement::Pending {
                connection,
                request: &request,
                credential,
                stamp: &auth.stamp,
                response: &message,
                inbox: &inbox,
                delay_millis: self.config.redelivery_delay_millis,
            },
            &self.monitor.0,
            ack,
            stop,
        )
        .await;
        Ok(Some(TriggerStep {
            configuration_epoch: self.monitor.0.epoch,
            trigger_index: index,
            stream_sequence: identity.sequence,
            delivery_count: identity.delivery,
            route_generation,
            terminal,
            acknowledgement,
            error,
        }))
    }
    /// One caller-owned task and timer, independent of the trigger count.
    pub async fn run(
        &mut self,
        manager: &LocalActivationManager,
        mut stop: watch::Receiver<bool>,
    ) -> Result<()> {
        loop {
            if *stop.borrow() || stop.has_changed().is_err() {
                break;
            }
            if matches!(
                Box::pin(self.step(manager, &mut stop)).await,
                Err(EventError::Cancelled)
            ) {
                break;
            }
            tokio::select! { biased; ()=stopped(&mut stop)=>break,
            ()=tokio::time::sleep(Duration::from_millis(self.config.poll_interval_millis))=>{} }
        }
        self.close_idle()
    }
}
