//! Activation-budgeted structured logging through one bounded node sink.

use std::collections::{BTreeMap, VecDeque};
use std::fmt;
use std::io::{self, Write};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_core::{ActivationBudget, ActivationId, BudgetReservation, Metadata};
use serde::{Serialize, Serializer};

use super::{ActivationHostContext, HostState};
use crate::bindings::latent::log::log;

const MAX_LOG_MESSAGE_BYTES: usize = 256;
const MAX_LOG_FIELDS: usize = 16;
const MAX_LOG_FIELD_NAME_BYTES: usize = 64;
const MAX_LOG_FIELD_VALUE_BYTES: usize = 256;

/// Canonical compact JSON field order used for `log_bytes` accounting.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CapturedLog {
    #[serde(serialize_with = "serialize_activation_id")]
    pub activation_id: ActivationId,
    pub level: String,
    pub message: String,
    pub fields: Metadata,
}

fn serialize_activation_id<S: Serializer>(
    id: &ActivationId,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&id.0)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogSinkError {
    Unavailable,
}

/// Trusted node-owned sink. Implementations must return promptly without
/// blocking, creating per-service work, or retaining unbounded log history.
/// The borrowed entry is valid only during the callback.
pub trait StructuredLogSink: Send + Sync {
    fn try_emit(&self, entry: &CapturedLog, encoded: &[u8]) -> Result<(), LogSinkError>;
}

#[derive(Debug)]
struct RetainedLog {
    entry: CapturedLog,
    encoded_bytes: usize,
}

#[derive(Debug)]
struct LogSinkState {
    entries: VecDeque<RetainedLog>,
    bytes: usize,
}

/// Shared bounded capture with an optional nonblocking node exporter.
#[derive(Clone)]
pub struct BoundedLogSink {
    state: Arc<Mutex<LogSinkState>>,
    maximum_entries: usize,
    maximum_bytes: usize,
    target: Option<Arc<dyn StructuredLogSink>>,
}

impl fmt::Debug for BoundedLogSink {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = self.lock_state();
        formatter
            .debug_struct("BoundedLogSink")
            .field("entries", &state.entries.len())
            .field("bytes", &state.bytes)
            .field("maximum_entries", &self.maximum_entries)
            .field("maximum_bytes", &self.maximum_bytes)
            .field("has_target", &self.target.is_some())
            .finish_non_exhaustive()
    }
}

impl BoundedLogSink {
    #[must_use]
    pub fn new(maximum_entries: usize, maximum_bytes: usize) -> Self {
        Self::with_target(maximum_entries, maximum_bytes, None)
    }

    #[must_use]
    pub fn with_target(
        maximum_entries: usize,
        maximum_bytes: usize,
        target: Option<Arc<dyn StructuredLogSink>>,
    ) -> Self {
        Self {
            state: Arc::new(Mutex::new(LogSinkState {
                entries: VecDeque::new(),
                bytes: 0,
            })),
            maximum_entries,
            maximum_bytes,
            target,
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> Vec<CapturedLog> {
        self.lock_state()
            .entries
            .iter()
            .map(|entry| entry.entry.clone())
            .collect()
    }

    #[must_use]
    pub fn snapshot_for(&self, activation_id: &ActivationId) -> Vec<CapturedLog> {
        self.lock_state()
            .entries
            .iter()
            .filter(|entry| &entry.entry.activation_id == activation_id)
            .map(|entry| entry.entry.clone())
            .collect()
    }

    pub fn clear(&self) {
        let mut state = self.lock_state();
        state.entries.clear();
        state.bytes = 0;
    }

    fn accept(
        &self,
        entry: CapturedLog,
        encoded: &[u8],
        reservation: BudgetReservation,
    ) -> Result<(), log::LogError> {
        let encoded_bytes = encoded.len();
        if self.maximum_entries == 0 || encoded_bytes > self.maximum_bytes {
            return Err(log::LogError::Unavailable);
        }
        // In particular, exporters may inspect the capture or budget without
        // entering a mutex held by the caller. Failure drops/refunds the grant.
        if let Some(target) = &self.target {
            target
                .try_emit(&entry, encoded)
                .map_err(|_| log::LogError::Unavailable)?;
        }
        reservation
            .commit()
            .map_err(|_| log::LogError::Unavailable)?;
        let mut state = self.lock_state();
        while state.entries.len() >= self.maximum_entries
            || encoded_bytes > self.maximum_bytes - state.bytes
        {
            let evicted = state
                .entries
                .pop_front()
                .expect("capture eviction requires an entry");
            state.bytes -= evicted.encoded_bytes;
        }
        state.bytes += encoded_bytes;
        state.entries.push_back(RetainedLog {
            entry,
            encoded_bytes,
        });
        Ok(())
    }

    fn lock_state(&self) -> MutexGuard<'_, LogSinkState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

/// Holds only counters and accounting; accepted entries live in the
/// node sink, and eviction never refunds an activation's already consumed bytes.
#[derive(Debug)]
pub(crate) struct InvocationLogBuffer {
    pub(super) maximum_entries: usize,
    pub(super) maximum_bytes: usize,
    accepted_entries: usize,
    bytes: usize,
    budget: ActivationBudget,
    sink: BoundedLogSink,
}

impl InvocationLogBuffer {
    pub(crate) fn new(
        maximum_entries: usize,
        configured_maximum_bytes: usize,
        budget: ActivationBudget,
        sink: BoundedLogSink,
    ) -> Self {
        Self {
            maximum_entries,
            maximum_bytes: configured_maximum_bytes
                .min(usize::try_from(budget.granted().log_bytes).unwrap_or(usize::MAX)),
            accepted_entries: 0,
            bytes: 0,
            budget,
            sink,
        }
    }

    pub(crate) fn write(
        &mut self,
        context: &ActivationHostContext,
        level: log::Level,
        message: String,
        fields: &[log::Field],
    ) -> Result<bool, log::LogError> {
        if message.len() > MAX_LOG_MESSAGE_BYTES {
            return Err(log::LogError::InvalidField("message-too-large".to_owned()));
        }
        let mut normalized = validated_fields(fields)?;
        if self.accepted_entries >= self.maximum_entries {
            return Err(log::LogError::BudgetExhausted);
        }
        normalized.insert("latent.activation_id", &context.activation_id.0);
        normalized.insert("latent.trace_id", &context.trace_id);
        normalized.insert("latent.span_id", &context.span_id);
        let level = level_name(level);
        let frame = BorrowedLog {
            activation_id: &context.activation_id.0,
            level,
            message: &message,
            fields: &normalized,
        };
        let mut count = BoundedByteCount {
            bytes: 0,
            maximum: self.maximum_bytes - self.bytes,
        };
        serde_json::to_writer(&mut count, &frame).map_err(|_| log::LogError::BudgetExhausted)?;
        let encoded_bytes = count.bytes;
        let reservation = self
            .budget
            .reserve_log_bytes(
                u64::try_from(encoded_bytes).map_err(|_| log::LogError::BudgetExhausted)?,
            )
            .map_err(|_| log::LogError::BudgetExhausted)?;
        let mut encoded = BoundedEncoding {
            bytes: Vec::with_capacity(encoded_bytes),
            maximum: encoded_bytes,
        };
        serde_json::to_writer(&mut encoded, &frame).map_err(|_| log::LogError::Unavailable)?;
        // The count and reservation precede cloning any trusted correlation
        // into this record. The temporary map contains at most 19 references.
        let entry = CapturedLog {
            activation_id: context.activation_id.clone(),
            level: level.to_owned(),
            message,
            fields: normalized
                .into_iter()
                .map(|(name, value)| (name.to_owned(), value.to_owned()))
                .collect(),
        };
        self.sink.accept(entry, &encoded.bytes, reservation)?;
        self.bytes += encoded_bytes;
        self.accepted_entries += 1;
        Ok(true)
    }

    pub(crate) fn bytes(&self) -> u64 {
        u64::try_from(self.bytes).unwrap_or(u64::MAX)
    }
}

fn validated_fields(fields: &[log::Field]) -> Result<BTreeMap<&str, &str>, log::LogError> {
    if fields.len() > MAX_LOG_FIELDS {
        return Err(log::LogError::InvalidField("too-many-fields".to_owned()));
    }
    let mut normalized = BTreeMap::new();
    for field in fields {
        if field.name.is_empty()
            || field.name.len() > MAX_LOG_FIELD_NAME_BYTES
            || !field
                .name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
        {
            return Err(log::LogError::InvalidField("invalid-field-name".to_owned()));
        }
        if field
            .name
            .as_bytes()
            .get(..7)
            .is_some_and(|prefix| prefix.eq_ignore_ascii_case(b"latent."))
        {
            return Err(log::LogError::InvalidField(
                "reserved-field-name".to_owned(),
            ));
        }
        if field.value.len() > MAX_LOG_FIELD_VALUE_BYTES {
            return Err(log::LogError::InvalidField(field.name.clone()));
        }
        if normalized
            .insert(field.name.as_str(), field.value.as_str())
            .is_some()
        {
            return Err(log::LogError::InvalidField(field.name.clone()));
        }
    }
    Ok(normalized)
}

#[derive(Serialize)]
struct BorrowedLog<'a> {
    activation_id: &'a str,
    level: &'a str,
    message: &'a str,
    fields: &'a BTreeMap<&'a str, &'a str>,
}

struct BoundedByteCount {
    bytes: usize,
    maximum: usize,
}

impl Write for BoundedByteCount {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.maximum - self.bytes {
            return Err(io::Error::other("log encoding exceeds its byte budget"));
        }
        self.bytes += bytes.len();
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

struct BoundedEncoding {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Write for BoundedEncoding {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.maximum - self.bytes.len() {
            return Err(io::Error::other("log encoding exceeds its reservation"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn level_name(level: log::Level) -> &'static str {
    match level {
        log::Level::Trace => "trace",
        log::Level::Debug => "debug",
        log::Level::Info => "info",
        log::Level::Warn => "warn",
        log::Level::Error => "error",
    }
}

impl log::Host for HostState {
    async fn write(
        &mut self,
        level: log::Level,
        message: String,
        fields: Vec<log::Field>,
    ) -> Result<bool, log::LogError> {
        let started = Instant::now();
        let result = self.logs.write(&self.context, level, message, &fields);
        self.record_host_call(started);
        result
    }
}

#[cfg(test)]
mod tests;
