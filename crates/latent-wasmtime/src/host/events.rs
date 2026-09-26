//! Synchronous guest publication with an asynchronous, activation-owned wait.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::events::{Event, EventError, EventPublisher, EVENTS_CAPABILITY};
use latent_component_bindings::host::phase3::latent::events::publisher as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::component::Linker;

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    publisher: Arc<dyn EventPublisher>,
) -> wasmtime::Result<()> {
    linker.instance(EVENTS_CAPABILITY)?.func_wrap_async(
        "publish",
        move |mut store, (event,): (wit::Event,)| {
            let publisher = publisher.clone();
            Box::new(async move {
                let started = Instant::now();
                checkpoint(&mut store)?;
                let event = Event {
                    topic: event.topic,
                    key: event.key,
                    payload: event.payload,
                    media_type: event.media_type,
                    attributes: event.attributes,
                    idempotency_key: event.idempotency_key,
                };
                let pending = store
                    .data()
                    .capabilities
                    .session
                    .as_ref()
                    .ok_or(EventError::PermissionDenied)
                    .and_then(|session| publisher.publish(session, event));
                synchronize(&mut store)?;
                let result = match pending {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                // Cancellation cannot roll back an already acknowledged or uncertain effect.
                // The provider has recorded that outcome independently of guest delivery.
                checkpoint(&mut store)?;
                let result = result
                    .map(|completion| {
                        store
                            .data_mut()
                            .capabilities
                            .retain_pool_lowering(completion.owner);
                        let r = completion.receipt;
                        wit::PublishReceipt {
                            event_id: r.event_id,
                            accepted_at_unix_millis: r.accepted_at_unix_millis,
                            stream_name: r.stream_name,
                            sequence: r.sequence,
                            duplicate: r.duplicate,
                        }
                    })
                    .map_err(convert_error);
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result,))
            })
        },
    )?;
    Ok(())
}
fn convert_error(error: EventError) -> wit::EventError {
    match error {
        EventError::InvalidTopic => wit::EventError::InvalidTopic,
        EventError::InvalidEvent => wit::EventError::InvalidEvent,
        EventError::PermissionDenied => wit::EventError::PermissionDenied,
        EventError::BudgetExhausted => wit::EventError::BudgetExhausted,
        EventError::DeadlineExceeded => wit::EventError::DeadlineExceeded,
        EventError::Cancelled => wit::EventError::Cancelled,
        EventError::Unavailable => wit::EventError::Unavailable,
        EventError::Uncertain => wit::EventError::Uncertain,
    }
}
