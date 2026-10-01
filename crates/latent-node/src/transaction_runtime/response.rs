//! Original data permission and prepaid buffers after physical guest retirement.
use super::{
    CommandTimeSource, StateAuthorization, TransactionCompletionResult, TransactionRetention,
};
use latent_commit::atomic::CommandRecord;
use latent_core::PlatformError;
use std::{
    sync::{Arc, OnceLock},
    time::Duration,
};

struct ResultRetention {
    time: Arc<dyn CommandTimeSource>,
    clock_floor: u64,
    expires_at: u64,
}

/// Holds no guest Store, cell or state view. It keeps the original finite
/// reservation and checks current data permission before a transport releases
/// bytes. It cannot admit execution or refresh any original source/deadline.
pub struct TransactionResponseAuthority {
    authorization: Arc<StateAuthorization>,
    retention: Arc<TransactionRetention>,
    operation: &'static str,
    result_retention: OnceLock<ResultRetention>,
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
            result_retention: OnceLock::new(),
        }
    }

    #[must_use]
    pub fn reserved_response_bytes(&self) -> u64 {
        self.retention.response_bytes()
    }

    /// Short Policy -> Namespace -> Native fence. Encoding and physical I/O
    /// happen outside the callback; original closed guest accounting stays closed.
    pub fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        // Clock observation may consult the original command role. Perform it
        // outside Policy/Namespace/Native bookkeeping locks.
        let observed = self.retention.monotonic_now();
        let deadline = if let Some(result) = self.result_retention.get() {
            let time = result.time.sample();
            if !time.continuity_proven
                || time.unix_millis < result.clock_floor
                || time.unix_millis >= result.expires_at
            {
                return Err(super::authorization::denied());
            }
            Some(
                observed
                    .checked_add(Duration::from_millis(result.expires_at - time.unix_millis))
                    .ok_or_else(super::authorization::denied)?,
            )
        } else {
            None
        };
        self.authorization
            .with_response_current(self.operation, || match deadline {
                Some(deadline) => self.retention.with_current_until(deadline, publish),
                None => self.retention.with_current(publish),
            })
    }

    pub(super) fn bind_result(
        &self,
        record: &CommandRecord,
        payload: bool,
        time: Arc<dyn CommandTimeSource>,
    ) -> Result<(), PlatformError> {
        self.result_retention
            .set(ResultRetention {
                time,
                clock_floor: record.clock_floor(),
                expires_at: if payload {
                    record.result_expires()
                } else {
                    record.identity_expires()
                },
            })
            .map_err(|_| super::authorization::denied())
    }
}

pub struct OwnedTransactionCompletion {
    pub result: TransactionCompletionResult,
    pub authority: Arc<TransactionResponseAuthority>,
}
