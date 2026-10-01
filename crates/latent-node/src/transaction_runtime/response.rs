//! Original data permission and prepaid buffers after physical guest retirement.
use super::{StateAuthorization, TransactionCompletionResult, TransactionRetention};
use latent_core::PlatformError;
use std::sync::Arc;

/// Holds no guest Store, cell or state view. It keeps the original finite
/// reservation and checks current data permission before a transport releases
/// bytes. It cannot admit execution or refresh any original source/deadline.
pub struct TransactionResponseAuthority {
    authorization: Arc<StateAuthorization>,
    retention: Arc<TransactionRetention>,
    operation: &'static str,
}

impl TransactionResponseAuthority {
    pub(super) fn new(
        authorization: Arc<StateAuthorization>,
        retention: Arc<TransactionRetention>,
        query: bool,
    ) -> Self {
        Self {
            authorization,
            retention,
            operation: if query { "query-info" } else { "read-result" },
        }
    }

    #[must_use]
    pub fn reserved_response_bytes(&self) -> u64 {
        self.retention.response_bytes()
    }

    /// Short Policy -> Namespace -> Native fence. Encoding and physical I/O
    /// happen outside the callback; original closed guest accounting stays closed.
    pub fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.authorization
            .with_response_current(self.operation, || self.retention.with_current(publish))
    }
}

pub struct OwnedTransactionCompletion {
    pub result: TransactionCompletionResult,
    pub authority: Arc<TransactionResponseAuthority>,
}
