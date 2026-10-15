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
    original_control: Option<crate::TransactionCommitControl>,
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
            original_control: None,
        }
    }

    pub(super) fn original_authorization(&self) -> Arc<StateAuthorization> {
        Arc::clone(&self.authorization)
    }

    pub(super) fn with_pre_host_control(
        mut self,
        control: crate::TransactionCommitControl,
    ) -> Self {
        self.original_control = Some(control);
        self
    }

    #[must_use]
    pub fn reserved_response_bytes(&self) -> u64 {
        self.retention.response_bytes()
    }

    /// Short Policy -> Namespace -> Native fence. Encoding and physical I/O
    /// happen outside the callback except for one bounded nonblocking transport
    /// poll. No waiting or storage I/O is permitted; guest accounting stays closed.
    pub fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        let original_observed = self
            .original_control
            .as_ref()
            .map(|control| {
                control
                    .observe_current()
                    .ok_or_else(super::authorization::denied)
            })
            .transpose()?;
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
        let mut released = false;
        let mut current_publish = || {
            if self
                .original_control
                .as_ref()
                .zip(original_observed)
                .is_none_or(|(control, observed)| control.is_current_at(observed))
            {
                released = true;
                publish();
            }
        };
        self.authorization
            .with_response_current(self.operation, || {
                if self.authorization.cancelled_metadata.is_some() {
                    self.authorization.with_response_native(
                        self.retention.native(),
                        deadline.unwrap_or_else(|| self.retention.native().original_deadline()),
                        &mut current_publish,
                    )
                } else {
                    match deadline {
                        Some(deadline) => self
                            .retention
                            .with_current_until(deadline, &mut current_publish),
                        None => self.retention.with_current(&mut current_publish),
                    }
                }
            })?;
        if released {
            Ok(())
        } else {
            Err(super::authorization::denied())
        }
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
