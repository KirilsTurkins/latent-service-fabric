use super::codec::{self, Answer};
use super::qualification::{QualifiedHttpEndpoint, MAXIMUM_REPLY_BYTES};
use super::request::{self, Operation};
use crate::protocol::{ProtocolFailure, ProtocolResponse, ProtocolScope, ProtocolTransport};
use crate::{HttpError, HttpProvider};
use latent_capabilities::broker::pools::DeferredRequest;
use latent_core::transaction_contract::Value;
use latent_effects::{
    authority::AuthorityError,
    dispatch::{AttemptIdentity, AttemptReceipt, Disposition, RetryProof},
    runtime::{
        AdapterOutcome, EffectTimeSource, ProviderConfirmation, ProviderReconciliationOutcome,
        ProviderReconciliationReason,
    },
};
use std::sync::Arc;

/// Every actual payload, header, socket and reply owner retires before the
/// original provider reservation. No protocol task or driver is detached.
pub(super) struct AcceptedOperation {
    pub provider: HttpProvider,
    pub transport: ProtocolTransport,
    pub endpoint: Arc<QualifiedHttpEndpoint>,
    pub time: Arc<dyn EffectTimeSource>,
    pub value: Value,
    pub body_digest: String,
    pub request: DeferredRequest,
    pub attempt: AttemptIdentity,
    pub horizon: u64,
    pub lookup: bool,
    pub retry_enabled: bool,
}

impl AcceptedOperation {
    pub async fn run(self) -> AdapterOutcome {
        let mut qualified = false;
        // A status lookup cannot erase a possible mutation by an older attempt.
        let mut possible = self.lookup;
        let result = self.perform(&mut qualified, &mut possible).await;
        let outcome = self.outcome(result, qualified, possible);
        drop(self);
        outcome
    }

    pub async fn reconcile(self, version: [u8; 32]) -> ProviderReconciliationOutcome {
        let attempt = self.attempt.clone();
        let outcome = self.run().await;
        // run destroys all native sockets, headers, payload and provider owners
        // before a positive receipt becomes available to the fixed host writer.
        if outcome.receipt.disposition == Disposition::ProviderAcknowledged {
            if let Some(receipt) = outcome.receipt.provider_receipt {
                if let Ok(confirmation) = ProviderConfirmation::new(
                    attempt,
                    version,
                    receipt,
                    outcome.receipt.observed_at_millis,
                ) {
                    return ProviderReconciliationOutcome::Confirmed(confirmation);
                }
            }
        }
        let reason = match outcome.receipt.reason.as_str() {
            "http-lookup-absent" => ProviderReconciliationReason::NotFound,
            "http-idempotency-conflict" => ProviderReconciliationReason::Conflict,
            "http-lookup-expired" => ProviderReconciliationReason::Expired,
            _ => ProviderReconciliationReason::Ambiguous,
        };
        ProviderReconciliationOutcome::Uncertain(reason)
    }

    async fn perform(
        &self,
        qualified: &mut bool,
        possible: &mut bool,
    ) -> Result<Answer, HttpError> {
        self.checkpoint()?;
        let (response, bytes) = self
            .exchange(Operation::Profile)
            .await
            .map_err(|e| e.error)?;
        codec::profile(&response, &bytes, &self.endpoint)?;
        drop(response);
        drop(bytes);
        *qualified = true;
        let lookup = self.lookup;
        let operation = if lookup {
            Operation::Lookup
        } else {
            Operation::Send
        };
        let result = self.exchange(operation).await;
        if !lookup {
            *possible = result
                .as_ref()
                .map_or_else(|failure| failure.request_started, |_| true);
        }
        let (response, bytes) = result.map_err(|failure| failure.error)?;
        // Lookup never falls through into POST, including a trusted "absent"
        // result. Ambiguity remains explicit operator reconciliation work.
        codec::receipt(
            &response,
            &bytes,
            &self.endpoint,
            &format!("lsf-effect-{}", self.request.grant().effect()),
            &self.body_digest,
            lookup,
        )
    }

    async fn exchange(
        &self,
        operation: Operation,
    ) -> Result<(ProtocolResponse, Vec<u8>), ProtocolFailure> {
        self.checkpoint()?;
        self.request.begin_operation().map_err(HttpError::from)?;
        let data = request::build(self, operation)?;
        let mut bytes = Vec::with_capacity(MAXIMUM_REPLY_BYTES);
        let response = self
            .transport
            .exchange_fenced(
                ProtocolScope::Deferred(&self.request),
                data.request,
                MAXIMUM_REPLY_BYTES,
                &mut |chunk| {
                    if bytes
                        .len()
                        .checked_add(chunk.len())
                        .is_none_or(|n| n > MAXIMUM_REPLY_BYTES)
                    {
                        return Err(HttpError::ResponseTooLarge);
                    }
                    bytes.extend_from_slice(chunk);
                    Ok(())
                },
                &mut || {
                    self.checkpoint()?;
                    request::check_credential(self, &data.credential_stamp)
                },
            )
            .await?;
        self.checkpoint().map_err(|error| ProtocolFailure {
            error,
            request_started: operation == Operation::Send,
        })?;
        Ok((response, bytes))
    }

    fn checkpoint(&self) -> Result<(), HttpError> {
        self.request.checkpoint()?;
        let time = self.time.observe();
        if !time.continuity_proven || time.unix_millis < self.request.grant().committed_at_millis()
        {
            return Err(HttpError::PermissionDenied);
        }
        if time.unix_millis >= self.horizon
            || self
                .attempt
                .retry_horizon_millis()
                .is_some_and(|horizon| time.unix_millis >= horizon)
        {
            return Err(HttpError::DeadlineExceeded);
        }
        self.request
            .grant()
            .check_current(time)
            .map_err(|error| match error {
                AuthorityError::Expired => HttpError::DeadlineExceeded,
                _ => HttpError::PermissionDenied,
            })
    }

    fn outcome(
        &self,
        result: Result<Answer, HttpError>,
        qualified: bool,
        possible: bool,
    ) -> AdapterOutcome {
        let (disposition, reason, provider_receipt) = match result {
            Ok(Answer::Accepted {
                sequence,
                duplicate,
            }) => (
                Disposition::ProviderAcknowledged,
                if self.lookup {
                    "http-lookup-confirmed"
                } else {
                    "http-operation-accepted"
                },
                Some(format!(
                    "{}:{sequence}:duplicate={}",
                    self.endpoint.endpoint_incarnation,
                    u8::from(duplicate)
                )),
            ),
            Ok(Answer::Rejected) => (Disposition::KnownFailed, "http-operation-rejected", None),
            Ok(Answer::Absent) => (Disposition::Uncertain, "http-lookup-absent", None),
            Ok(Answer::Conflict) => (Disposition::Uncertain, "http-idempotency-conflict", None),
            Ok(Answer::Expired) => (Disposition::Uncertain, "http-lookup-expired", None),
            Err(_) if possible => (Disposition::Uncertain, "http-reply-unknown", None),
            Err(HttpError::PermissionDenied) => (
                Disposition::PolicyBlocked,
                "http-current-scope-denied",
                None,
            ),
            Err(HttpError::DeadlineExceeded) => {
                (Disposition::Expired, "http-original-deadline-expired", None)
            }
            Err(_) => (Disposition::KnownFailed, "http-operation-not-sent", None),
        };
        let time = self.time.observe();
        let grant = self.request.grant();
        // Only the first possibly sent POST receives one finite recovery step.
        // That step is status lookup, never another mutation. A missing, expired
        // or ambiguous lookup is retained without automatic execution or retry.
        let retry = (self.retry_enabled
            && self.attempt.attempt() == 1
            && qualified
            && possible
            && result.is_err()
            && disposition == Disposition::Uncertain
            && time.continuity_proven
            && time.unix_millis >= grant.committed_at_millis()
            && time
                .unix_millis
                .checked_add(100)
                .is_some_and(|next| next < self.horizon)
            && grant.ceiling().maximum_attempts > 1)
            .then_some((
                RetryProof::QualifiedDeduplication {
                    valid_until_millis: self.horizon,
                    same_payload: true,
                    same_provider_incarnation: true,
                },
                100,
            ));
        AdapterOutcome {
            receipt: AttemptReceipt {
                disposition,
                reason: reason.into(),
                provider_receipt,
                observed_at_millis: time.unix_millis,
            },
            retry,
        }
    }
}
