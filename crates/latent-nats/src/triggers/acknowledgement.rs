use super::{
    consumer::{self, Ack},
    driver::stopped,
    monitor::Counters,
    wire, Acknowledgement,
};
use crate::{
    network::{self, Connection},
    provider::tick,
    EventError, NatsCredential,
};
use latent_capabilities::broker::pools::{IngressRequest, PooledConnection};
use tokio::sync::watch;

pub(super) struct Pending<'a> {
    pub connection: PooledConnection<Connection>,
    pub request: &'a IngressRequest,
    pub credential: &'a NatsCredential,
    pub stamp: &'a [u8; 32],
    pub response: &'a wire::Frame,
    pub inbox: &'a str,
    pub delay_millis: u64,
}
pub(super) async fn finish(
    mut pending: Pending<'_>,
    counters: &Counters,
    ack: Ack,
    stop: &mut watch::Receiver<bool>,
) -> (Acknowledgement, Option<EventError>) {
    if let Err(error) = network::check_current(pending.credential, pending.stamp) {
        return (Acknowledgement::NotSent, Some(error));
    }
    if *stop.borrow() {
        return (Acknowledgement::NotSent, Some(EventError::Cancelled));
    }
    let result = tokio::select! {
        biased;
        ()=stopped(stop)=>Err(EventError::Uncertain),
        result=consumer::acknowledge(pending.connection.resource(), pending.request,
            pending.response, ack, pending.delay_millis, pending.inbox)=>result,
    };
    match result {
        Ok(()) => {
            let _ = pending.connection.park();
            let (counter, acknowledgement) = match ack {
                Ack::Success => (&counters.acknowledged, Acknowledgement::Accepted),
                Ack::Retry => (&counters.retries, Acknowledgement::RetryScheduled),
                Ack::Terminate => (&counters.terminated, Acknowledgement::Terminated),
            };
            tick(counter);
            (acknowledgement, None)
        }
        Err(EventError::Uncertain) => {
            tick(&counters.uncertain);
            (Acknowledgement::Uncertain, Some(EventError::Uncertain))
        }
        Err(error) => (Acknowledgement::NotSent, Some(error)),
    }
}
