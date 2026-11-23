//! Protected configuration for one explicit retry. The original durable abort,
//! current authorization and retry receipt remain owned by the transaction runtime.
use crate::{EventError, Result};
use latent_commit::atomic::{Identity, RetryRequest};
use latent_node::transaction_runtime::TransactionRetrySelection;
use serde::{Deserialize, Serialize};

// Covers the installed selector and its copy on the one bounded delivery.
pub(in crate::triggers) const APPROVED_RETRY_METADATA_BYTES: usize = 2048;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ApprovedInboxRetry {
    pub(super) stream_sequence: String,
    attempt_generation: String,
    request_id: String,
    command_id: String,
    transaction_id: String,
    owner_fence: String,
}

impl ApprovedInboxRetry {
    pub(super) fn validate(&self) -> Result<()> {
        if self.stream_sequence.capacity() > 20
            || self.attempt_generation.capacity() > 20
            || self.request_id.capacity() > 256
            || [&self.command_id, &self.transaction_id, &self.owner_fence]
                .iter()
                .any(|value| value.capacity() > 64)
        {
            return Err(EventError::InvalidEvent);
        }
        positive(&self.stream_sequence)?;
        self.selection().map(drop)
    }

    pub(super) fn selection(&self) -> Result<TransactionRetrySelection> {
        let identity = |value: &str| {
            let id = Identity::parse_hex(value).map_err(|_| EventError::InvalidEvent)?;
            if id.bytes() == [0; 32] {
                return Err(EventError::InvalidEvent);
            }
            Ok(id)
        };
        latent_core::transaction_contract::identity(&self.request_id)
            .map_err(|_| EventError::InvalidEvent)?;
        Ok(TransactionRetrySelection {
            request: RetryRequest {
                request_id: self.request_id.clone(),
                expected_abort: identity(&self.owner_fence)?,
            },
            command: identity(&self.command_id)?,
            attempt: positive(&self.attempt_generation)?,
            transaction: identity(&self.transaction_id)?,
        })
    }
}

fn positive(value: &str) -> Result<u64> {
    let number = value.parse::<u64>().map_err(|_| EventError::InvalidEvent)?;
    if number == 0 || number.to_string() != value {
        return Err(EventError::InvalidEvent);
    }
    Ok(number)
}
