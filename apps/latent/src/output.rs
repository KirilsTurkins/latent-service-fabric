//! One stable document, with escaped human data and bounded serialization.
#[cfg(test)]
mod tests;

use std::io::{self, Write};

use latent_core::PlatformError;
use serde_json::{json, Value};

use crate::{
    args::OutputFormat,
    error::{platform_value, Failure},
};

const MAX_OUTPUT_BYTES: usize = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Category {
    Success,
    LocalError,
    DomainError,
    PlatformError,
    TransportError,
    NotFound,
    Interrupted,
}
impl Category {
    pub const fn name(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::LocalError => "local-error",
            Self::DomainError => "declared-error",
            Self::PlatformError => "platform-failure",
            Self::TransportError => "transport-failure",
            Self::NotFound => "not-found",
            Self::Interrupted => "interrupted",
        }
    }
    pub const fn exit_code(self) -> i32 {
        match self {
            Self::Success => 0,
            Self::LocalError => 2,
            Self::DomainError => 3,
            Self::PlatformError => 4,
            Self::TransportError => 5,
            Self::NotFound => 6,
            Self::Interrupted => 130,
        }
    }
}

// Keep certainty field names aligned with the public result schema.
#[allow(clippy::struct_field_names)]
#[derive(Debug)]
pub struct Outcome {
    pub category: Category,
    pub data: Value,
    pub error: Option<Value>,
    pub request_dispatched: bool,
    pub outcome_known: bool,
}
impl Outcome {
    fn new(category: Category, data: Value, error: Option<Value>) -> Self {
        Self {
            category,
            data,
            error,
            request_dispatched: false,
            outcome_known: true,
        }
    }
    pub fn success(data: Value) -> Self {
        Self::new(Category::Success, data, None)
    }
    pub fn not_found(data: Value) -> Self {
        Self::new(Category::NotFound, data, None)
    }
    pub fn domain_error(data: Value) -> Self {
        Self::new(Category::DomainError, data, None)
    }
    pub fn platform_failure(data: Value, error: &PlatformError) -> Self {
        Self::new(Category::PlatformError, data, Some(platform_value(error)))
    }
    pub const fn exit_code(&self) -> i32 {
        self.category.exit_code()
    }
    pub fn document(&self, command: &str) -> Value {
        json!({"schemaVersion": "latent.cli.result.v1", "command": command,
            "category": self.category.name(), "data": self.data, "error": self.error,
            "requestDispatched": self.request_dispatched, "outcomeKnown": self.outcome_known})
    }
}
impl From<Failure> for Outcome {
    fn from(value: Failure) -> Self {
        Self {
            category: value.category,
            data: value.data,
            error: Some(value.error),
            request_dispatched: value.request_dispatched,
            outcome_known: value.outcome_known,
        }
    }
}

struct BoundedOutput(Vec<u8>);
impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > MAX_OUTPUT_BYTES.saturating_sub(self.0.len()) {
            return Err(io::Error::other("output limit"));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

pub fn emit(mut outcome: Outcome, command: &str, format: OutputFormat, quiet: bool) -> i32 {
    if quiet
        && format == OutputFormat::Human
        && outcome.category == Category::Success
        && outcome.data.get("payload").is_none()
    {
        return outcome.exit_code();
    }
    let mut bytes = BoundedOutput(Vec::new());
    let serialize = |buffer: &mut BoundedOutput, value: &Outcome| match format {
        OutputFormat::Json => serde_json::to_writer(buffer, &value.document(command)),
        OutputFormat::Human => serde_json::to_writer_pretty(buffer, &value.document(command)),
    };
    if serialize(&mut bytes, &outcome).is_err() {
        let mut failure =
            Failure::local("output-limit", "The result exceeds the CLI output limit.");
        failure.request_dispatched = outcome.request_dispatched;
        failure.outcome_known = outcome.outcome_known;
        failure.data = receipt(&outcome.data);
        outcome = failure.into();
        bytes.0.clear();
        if serialize(&mut bytes, &outcome).is_err() {
            return 2;
        }
    }
    bytes.0.push(b'\n');
    let result = if format == OutputFormat::Json || outcome.category == Category::Success {
        io::stdout().lock().write_all(&bytes.0)
    } else {
        // Requested data belongs on stdout even when the operation failed.
        // Fixed diagnostics and classification belong on stderr in human mode.
        let mut returned = BoundedOutput(Vec::new());
        if outcome
            .data
            .as_object()
            .is_some_and(|data| !data.is_empty())
        {
            if serde_json::to_writer_pretty(&mut returned, &outcome.data).is_err() {
                return 2;
            }
            returned.0.push(b'\n');
        }
        let mut diagnostic = outcome.document(command);
        diagnostic["data"] = json!({});
        bytes.0.clear();
        if serde_json::to_writer_pretty(&mut bytes, &diagnostic).is_err() {
            return 2;
        }
        bytes.0.push(b'\n');
        io::stdout()
            .lock()
            .write_all(&returned.0)
            .and_then(|()| io::stderr().lock().write_all(&bytes.0))
    };
    if result.is_err() {
        2
    } else {
        outcome.exit_code()
    }
}

pub fn receipt(data: &Value) -> Value {
    let mut result = json!({});
    for key in ["activationId", "resolvedRevision"] {
        if let Some(value) = data.get(key) {
            result[key] = value.clone();
        }
    }
    result
}
