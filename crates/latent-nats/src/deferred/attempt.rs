use super::JetStreamQualification;
use crate::{
    network::{self, Connection, Dial, Scope},
    protocol,
    provider::{Active, Inner},
    triggers::wire,
    EventError,
};
use latent_capabilities::broker::{
    events::{Event, PublishReceipt},
    pools::{DeferredRequest, ProviderClient},
};
use latent_effects::{
    dispatch::{AttemptIdentity, AttemptReceipt, Disposition, RetryProof},
    runtime::{AdapterOutcome, EffectTimeSource},
};
use std::sync::{atomic::Ordering, Arc};

/// Owns real input, request permits and socket future until their destruction.
pub(super) struct AcceptedPublish {
    pub inner: Arc<Inner>,
    pub client: Arc<ProviderClient<Connection>>,
    pub qualification: JetStreamQualification,
    pub row: usize,
    pub credential: usize,
    pub time: Arc<dyn EffectTimeSource>,
    pub event: Event,
    pub request: DeferredRequest,
    pub attempt: AttemptIdentity,
    pub horizon: u64,
}

impl AcceptedPublish {
    pub async fn run(self) -> AdapterOutcome {
        self.inner.active.fetch_add(1, Ordering::AcqRel);
        let active = Active(Arc::clone(&self.inner));
        let mut wrote = false;
        let mut qualified = false;
        let result = self.publish(&mut wrote, &mut qualified).await;
        let _ = self.inner.observe(&result, wrote);
        let outcome = self.outcome(result, qualified);
        // No driver is spawned: completion follows actual socket/buffer drop
        // or a validated-ack socket transfer into the charged shared idle pool.
        drop(self);
        drop(active);
        outcome
    }

    async fn publish(
        &self,
        wrote: &mut bool,
        qualified: &mut bool,
    ) -> crate::Result<PublishReceipt> {
        self.request.checkpoint()?;
        let auth = network::current(&self.inner.credentials[self.credential])?;
        let mut connection = network::connect_to(
            Dial {
                pools: &self.inner.pools,
                endpoint: &self.inner.config.endpoint,
                tls: &self.inner.tls,
                attempts: &self.inner.connection_attempts,
                reuses: &self.inner.connection_reuses,
            },
            &self.client,
            Scope::from(&self.request),
            &auth,
        )
        .await?;
        if connection.resource().server_version.as_deref()
            != Some(&self.qualification.server_version)
        {
            return Err(EventError::PermissionDenied);
        }
        self.qualify(connection.resource()).await?;
        *qualified = true;
        let now = self.time.observe();
        if !now.continuity_proven
            || now.unix_millis < self.request.grant().committed_at_millis()
            || now.unix_millis >= self.request.grant().expires_at_millis()
            || self
                .attempt
                .retry_horizon_millis()
                .is_some_and(|approved| now.unix_millis >= approved)
        {
            return Err(EventError::PermissionDenied);
        }
        self.request.begin_operation()?;
        let publish_inbox = inbox(&self.inner)?;
        protocol::subscribe(connection.resource(), &self.request, &publish_inbox).await?;
        network::check_current(&self.inner.credentials[self.credential], &auth.stamp)?;
        let receipt = protocol::publish(
            connection.resource(),
            &self.request,
            &self.event,
            &self.inner.config.topics[self.row],
            &publish_inbox,
            &self.event.idempotency_key,
            wrote,
        )
        .await?;
        let _ = connection.park();
        Ok(receipt)
    }

    async fn qualify(&self, connection: &mut Connection) -> crate::Result<()> {
        self.request.begin_operation()?;
        let query_inbox = inbox(&self.inner)?;
        protocol::subscribe(connection, &self.request, &query_inbox).await?;
        wire::send(
            connection,
            Scope::from(&self.request),
            &format!(
                "$JS.API.STREAM.INFO.{}",
                self.inner.config.topics[self.row].stream
            ),
            &query_inbox,
            b"",
        )
        .await?;
        let response = wire::receive(
            connection,
            Scope::from(&self.request),
            &[&query_inbox],
            8192,
        )
        .await?;
        if response.reply.is_some() || response.headers != 0 {
            return Err(EventError::Unavailable);
        }
        super::qualification::validate_response(
            response.payload(),
            &self.qualification,
            &self.inner.config.topics[self.row],
            &self.inner.config,
        )
    }

    fn outcome(&self, result: crate::Result<PublishReceipt>, qualified: bool) -> AdapterOutcome {
        let (disposition, reason, provider_receipt) = match result {
            Ok(receipt) => (
                Disposition::ProviderAcknowledged,
                if receipt.duplicate {
                    "jetstream-duplicate-accepted"
                } else {
                    "jetstream-accepted"
                },
                Some(format!(
                    "{}@{}:{}:duplicate={}",
                    receipt.stream_name,
                    self.qualification.stream_created,
                    receipt.sequence,
                    u8::from(receipt.duplicate)
                )),
            ),
            Err(EventError::PermissionDenied) => {
                (Disposition::PolicyBlocked, "jetstream-scope-blocked", None)
            }
            // These are explicit negative protocol outcomes. All ambiguous
            // post-write I/O and malformed receipts are mapped to Uncertain
            // by the maintained publisher before reaching this classification.
            Err(
                EventError::InvalidEvent | EventError::BudgetExhausted | EventError::Unavailable,
            ) => (Disposition::KnownFailed, "jetstream-publish-rejected", None),
            Err(EventError::Uncertain) => (Disposition::Uncertain, "jetstream-ack-unknown", None),
            Err(_) => (Disposition::KnownFailed, "jetstream-not-published", None),
        };
        let time = self.time.observe();
        let grant = self.request.grant();
        let delay = 100 * (1_u64 << self.attempt.attempt().saturating_sub(1).min(3));
        let horizon = self.horizon.min(grant.expires_at_millis());
        let retry = (qualified
            && time.continuity_proven
            && time.unix_millis >= grant.committed_at_millis()
            && matches!(
                disposition,
                Disposition::KnownFailed | Disposition::Uncertain
            )
            && time
                .unix_millis
                .checked_add(delay)
                .is_some_and(|next| next < horizon)
            && self.attempt.attempt() < grant.ceiling().maximum_attempts)
            .then_some((
                RetryProof::QualifiedDeduplication {
                    valid_until_millis: horizon,
                    same_payload: true,
                    same_provider_incarnation: true,
                },
                delay,
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

fn inbox(inner: &Inner) -> crate::Result<String> {
    let sequence = inner
        .next
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |number| {
            number.checked_add(1)
        })
        .map_err(|_| EventError::BudgetExhausted)?;
    Ok(format!("{}.{sequence:016x}", inner.inbox_namespace))
}
