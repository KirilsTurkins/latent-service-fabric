//! Immediate guest-log bridge into the shared redacted telemetry observer.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use latent_core::ActivationClock;
use latent_telemetry::{GuestLogObserver, GuestLogRecord, LogSeverity};

use crate::{CapturedLog, LogSinkError, StructuredLogSink};

pub struct TelemetryLogSink {
    observer: Arc<dyn GuestLogObserver>,
    clock: Arc<dyn ActivationClock>,
    observer_panics: AtomicU64,
}

impl TelemetryLogSink {
    #[must_use]
    pub fn new(observer: Arc<dyn GuestLogObserver>, clock: Arc<dyn ActivationClock>) -> Self {
        Self {
            observer,
            clock,
            observer_panics: AtomicU64::new(0),
        }
    }

    #[must_use]
    pub fn observer_panics(&self) -> u64 {
        self.observer_panics.load(Ordering::Relaxed)
    }
}

impl StructuredLogSink for TelemetryLogSink {
    fn try_emit(&self, entry: &CapturedLog, _encoded: &[u8]) -> Result<(), LogSinkError> {
        let severity = match entry.level.as_str() {
            "trace" => LogSeverity::Trace,
            "debug" => LogSeverity::Debug,
            "info" => LogSeverity::Info,
            "warn" => LogSeverity::Warn,
            "error" => LogSeverity::Error,
            "fatal" => LogSeverity::Fatal,
            _ => return Err(LogSinkError::Unavailable),
        };
        // The observer validates and redacts borrowed fields before allocating.
        // Default pipeline drop policy accepts the host write and counts its
        // export loss; explicit fail-on-drop policy returns a host sink error.
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            self.observer.on_guest_log(GuestLogRecord {
                activation_id: &entry.activation_id,
                severity,
                body: &entry.message,
                fields: &entry.fields,
                observed_at_unix_millis: self.clock.sample().unix_millis(),
            })
        }));
        if let Ok(result) = result {
            result.map_err(|_| LogSinkError::Unavailable)
        } else {
            let _ =
                self.observer_panics
                    .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |count| {
                        Some(count.saturating_add(1))
                    });
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests;
