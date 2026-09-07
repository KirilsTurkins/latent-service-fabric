use super::{TelemetryDropReason, TelemetryHandle};
use crate::{MetricKind, MetricPoint};
use latent_core::Metadata;
impl TelemetryHandle {
    #[expect(
        clippy::cast_precision_loss,
        reason = "telemetry counters are exported as floating-point metrics"
    )]
    #[must_use]
    pub fn operational_metrics(&self, observed_at_unix_millis: u64) -> Vec<MetricPoint> {
        let snapshot = self.snapshot();
        let metric = |name: &str, value: f64, kind: MetricKind, attributes: Metadata| MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: "1".to_owned(),
            attributes,
            observed_at_unix_millis,
        };
        let dropped = |reason: TelemetryDropReason, value: u64| {
            metric(
                "latent.telemetry.dropped",
                value as f64,
                MetricKind::Counter,
                Metadata::from([("reason".to_owned(), reason.as_str().to_owned())]),
            )
        };
        vec![
            metric(
                "latent.telemetry.queue.depth",
                snapshot.queue_depth as f64,
                MetricKind::Gauge,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.queue.capacity",
                snapshot.queue_capacity as f64,
                MetricKind::Gauge,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.accepted",
                snapshot.accepted as f64,
                MetricKind::Counter,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.exported",
                snapshot.exported as f64,
                MetricKind::Counter,
                Metadata::new(),
            ),
            dropped(TelemetryDropReason::QueueFull, snapshot.dropped_queue_full),
            dropped(
                TelemetryDropReason::QueueClosed,
                snapshot.dropped_queue_closed,
            ),
            dropped(
                TelemetryDropReason::InvalidRecord,
                snapshot.dropped_invalid_record,
            ),
            dropped(TelemetryDropReason::SinkFailure, snapshot.sink_failures),
            dropped(TelemetryDropReason::SinkTimeout, snapshot.sink_timeouts),
        ]
    }
}
