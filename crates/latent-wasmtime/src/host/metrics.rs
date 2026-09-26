//! Custom observations use the installed shared telemetry owner and exact grants.
use super::{service::synchronize, HostState};
use latent_capabilities::broker::metrics::{
    Metric, MetricError, MetricProvider, METRICS_CAPABILITY,
};
use latent_component_bindings::host::phase3::latent::telemetry::custom as wit;
use latent_telemetry::MetricKind;
use std::{sync::Arc, time::Instant};
use wasmtime::component::Linker;

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    provider: Arc<MetricProvider>,
) -> wasmtime::Result<()> {
    linker.instance(METRICS_CAPABILITY)?.func_wrap_async(
        "emit-metric",
        move |mut store, (metric,): (wit::Metric,)| {
            let provider = provider.clone();
            Box::new(async move {
                let started = Instant::now();
                checkpoint(&mut store)?;
                let pending = store
                    .data()
                    .capabilities
                    .session
                    .as_ref()
                    .ok_or(MetricError::Unavailable)
                    .and_then(|session| {
                        provider.emit(
                            session,
                            Metric {
                                name: metric.name,
                                kind: match metric.kind {
                                    wit::MetricKind::Counter => MetricKind::Counter,
                                    wit::MetricKind::UpDownCounter => MetricKind::UpDownCounter,
                                    wit::MetricKind::Gauge => MetricKind::Gauge,
                                    wit::MetricKind::Histogram => MetricKind::Histogram,
                                },
                                value: metric.value,
                                unit: metric.unit,
                                attributes: metric.attributes,
                            },
                        )
                    });
                synchronize(&mut store)?;
                let result = match pending {
                    Ok(pending) => pending.await,
                    Err(error) => Err(error),
                };
                checkpoint(&mut store)?;
                let result = result
                    .map(|completion| {
                        store
                            .data_mut()
                            .capabilities
                            .retain_lowering(completion.owner);
                        completion.accepted
                    })
                    .map_err(|error| match error {
                        MetricError::InvalidName => wit::TelemetryError::InvalidName,
                        MetricError::BudgetExhausted => wit::TelemetryError::BudgetExhausted,
                        MetricError::Unavailable => wit::TelemetryError::Unavailable,
                    });
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result,))
            })
        },
    )?;
    Ok(())
}
fn checkpoint(store: &mut wasmtime::StoreContextMut<'_, HostState>) -> wasmtime::Result<()> {
    super::service::checkpoint(store)?;
    if let Some(session) = &store.data().capabilities.session {
        session
            .check_liveness()
            .map_err(super::capabilities::host_error)?;
    }
    Ok(())
}
