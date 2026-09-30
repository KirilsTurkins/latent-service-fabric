//! Logical intents are staged through an admitted command, never dispatched here.
use crate::bindings::intents as raw;
use crate::state::{Command, Value};
pub use raw::{IntentError, StagedIntent};

/// Host policy chooses the provider, IDs, finite retries and admitted lifetime.
pub struct Intent(raw::Intent);

impl Intent {
    pub fn new(binding: String, operation: String, payload: Value) -> Self {
        Self(raw::Intent {
            binding,
            operation,
            payload,
            expires_at_unix_millis: None,
        })
    }

    #[must_use]
    pub fn expires_at(mut self, unix_millis: u64) -> Self {
        self.0.expires_at_unix_millis = Some(unix_millis);
        self
    }

    pub async fn stage(self, command: &mut Command) -> Result<StagedIntent, IntentError> {
        raw::stage(command.borrow(), self.0).await
    }
}
