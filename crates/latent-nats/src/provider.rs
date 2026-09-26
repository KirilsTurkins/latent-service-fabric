use crate::{
    config::text,
    network::{self, Connection},
    protocol, request, EventError, NatsConfig, Result,
};
use latent_capabilities::broker::{
    events::{Event, EventCompletion, EventFuture, EventPublisher, EVENTS_CAPABILITY},
    io::IoMemory,
    pools::{InstalledProvider, ProviderMetadata, ProviderPools, ProviderSetup},
    secrets::TlsProviderCredential,
    AuditProviderOutcome, CapabilityCallCost, CapabilitySession, ProviderBudgetRequirement,
    ProviderConfiguration, ProviderReference,
};
use latent_core::BudgetDimension;
use latent_policy::capability::ResourceTarget;
use sha2::{Digest, Sha256};
use std::{
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

pub const NATS_PUBLISH_PROFILE: &str = "nats-jetstream-publish-v1";
/// None selects token authentication; Some selects that fixed user plus a
/// protected password. Neither the reference nor its value is guest-readable.
pub struct NatsCredential {
    pub username: Option<String>,
    pub secret: Arc<dyn TlsProviderCredential>,
}
#[derive(Clone)]
pub struct NatsPublisher {
    inner: Arc<Inner>,
}
pub(crate) struct Inner {
    pub config: NatsConfig,
    pub tls: Arc<rustls::ClientConfig>,
    credentials: Vec<NatsCredential>,
    pub pools: Arc<ProviderPools>,
    installed: InstalledProvider,
    inbox_namespace: String,
    next: AtomicU64,
    active: AtomicUsize,
    pub connection_attempts: AtomicU64,
    pub connection_reuses: AtomicU64,
    acknowledged: AtomicU64,
    uncertain: AtomicU64,
    _metadata: ProviderMetadata,
}
#[derive(Debug)]
pub struct NatsSnapshot {
    pub configuration_epoch: u64,
    pub topics: usize,
    pub active_publishes: usize,
    pub connection_attempts: u64,
    pub connection_reuses: u64,
    pub acknowledged_publishes: u64,
    pub uncertain_publishes: u64,
}
impl NatsPublisher {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: NatsConfig,
        credentials: Vec<NatsCredential>,
    ) -> Result<Self> {
        config.validate()?;
        if credentials.is_empty() || credentials.capacity() > 16 {
            return Err(EventError::InvalidEvent);
        }
        let metadata = pools.reserve_protocol_metadata(
            65536 + 6 * config.extra_roots.iter().map(Vec::capacity).sum::<usize>(),
        )?;
        let mut hash = Sha256::new();
        hash.update(b"lsf-nats-publish-v1\0");
        hash.update(serde_json::to_vec(&config).map_err(|_| EventError::InvalidEvent)?);
        let destination = config.endpoint.credential_destination();
        for (i, credential) in credentials.iter().enumerate() {
            let scope = credential.secret.scope();
            if scope.provider_id != logical_id
                || scope.destination != destination
                || !text(&scope.tenant.0, 128)
                || !text(credential.secret.reference(), 256)
                || credential
                    .username
                    .as_ref()
                    .is_some_and(|v| !text(v, 128) || v.capacity() > 128)
                || credentials[..i]
                    .iter()
                    .any(|c| c.secret.scope().tenant == scope.tenant)
            {
                return Err(EventError::PermissionDenied);
            }
            for value in [
                scope.tenant.0.as_str(),
                credential.secret.reference(),
                credential.username.as_deref().unwrap_or(""),
            ] {
                hash.update((value.len() as u64).to_le_bytes());
                hash.update(value.as_bytes());
            }
        }
        if config.topics.iter().any(|t| {
            !credentials
                .iter()
                .any(|c| c.secret.scope().tenant.0 == t.tenant)
        }) {
            return Err(EventError::PermissionDenied);
        }
        let tls = network::tls(&config)?;
        let mut entropy = [0_u8; 16];
        getrandom::fill(&mut entropy).map_err(|_| EventError::Unavailable)?;
        let inbox_namespace = format!("_INBOX.LSF.{:032x}", u128::from_le_bytes(entropy));
        let digest = format!("sha256:{:x}", hash.finalize());
        let mut subjects: Vec<_> = config.topics.iter().map(|t| t.topic.as_str()).collect();
        subjects.sort_unstable();
        subjects.dedup();
        let restriction=serde_json::to_vec(&serde_json::json!({"operations":["publish"],"resources":{"kind":"events","subjects":subjects}})).map_err(|_|EventError::InvalidEvent)?;
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: EVENTS_CAPABILITY,
                    profile: NATS_PUBLISH_PROFILE,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[ProviderBudgetRequirement {
                        operation: "publish",
                        dimension: BudgetDimension::OutboundRequests,
                        minimum: 1,
                    }],
                },
            },
            expected_epoch,
        )?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                tls,
                credentials,
                pools,
                installed,
                inbox_namespace,
                next: AtomicU64::new(0),
                active: AtomicUsize::new(0),
                connection_attempts: AtomicU64::new(0),
                connection_reuses: AtomicU64::new(0),
                acknowledged: AtomicU64::new(0),
                uncertain: AtomicU64::new(0),
                _metadata: metadata,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
    #[must_use]
    pub fn snapshot(&self) -> NatsSnapshot {
        NatsSnapshot {
            configuration_epoch: self.reference().configuration_epoch(),
            topics: self.inner.config.topics.len(),
            active_publishes: self.inner.active.load(Ordering::Acquire),
            connection_attempts: self.inner.connection_attempts.load(Ordering::Acquire),
            connection_reuses: self.inner.connection_reuses.load(Ordering::Acquire),
            acknowledged_publishes: self.inner.acknowledged.load(Ordering::Acquire),
            uncertain_publishes: self.inner.uncertain.load(Ordering::Acquire),
        }
    }
}
struct RequestOwner {
    event: Event,
    _input: IoMemory,
}
struct Active(Arc<Inner>);
impl Drop for Active {
    fn drop(&mut self) {
        self.0.active.fetch_sub(1, Ordering::AcqRel);
    }
}
impl EventPublisher for NatsPublisher {
    fn publish(&self, session: &CapabilitySession, event: Event) -> Result<EventFuture> {
        let size = request::validate(&event, self.inner.config.maximum_payload_bytes)?;
        if !session.uses_provider(&self.reference())? {
            return Err(EventError::PermissionDenied);
        }
        let row = self
            .inner
            .config
            .topics
            .iter()
            .position(|row| row.tenant == session.tenant().0 && row.topic == event.topic)
            .ok_or(EventError::PermissionDenied)?;
        let credential = self
            .inner
            .credentials
            .iter()
            .position(|c| c.secret.scope().tenant == *session.tenant())
            .ok_or(EventError::PermissionDenied)?;
        let client = self.inner.pools.client::<Connection>(
            &self.inner.installed,
            u16::try_from(credential).map_err(|_| EventError::InvalidEvent)?,
        )?;
        let deadline = (Instant::now() + Duration::from_millis(self.inner.config.timeout_millis))
            .min(session.deadline()?);
        let admission = self.inner.pools.admit_until(&client, session, deadline)?;
        let owner = RequestOwner {
            event,
            _input: admission.reserve_input(size.retained, 4096)?,
        };
        let digest = request::digest(&owner.event)?;
        let inner = self.inner.clone();
        Ok(Box::pin(async move {
            let ready = admission.wait().await?;
            let cost = CapabilityCallCost::new(2048)
                .with_typed_input_bytes(size.typed)
                .with_typed_request_digest(digest)
                .with_charge(BudgetDimension::OutboundRequests, 1)?;
            let mut call = ready
                .dispatch(
                    EVENTS_CAPABILITY,
                    "publish",
                    ResourceTarget::Events {
                        subject: &owner.event.topic,
                    },
                    &[],
                    cost,
                )
                .await?;
            inner.active.fetch_add(1, Ordering::AcqRel);
            let _active = Active(inner.clone());
            let mut wrote = false;
            let result = async {
                let _scratch = call.io().reserve_scratch(32768, 4096)?;
                let auth = network::current(&inner.credentials[credential])?;
                let mut connection = network::connect(&inner, &client, &call, &auth).await?;
                let sequence = inner
                    .next
                    .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
                    .map_err(|_| EventError::BudgetExhausted)?;
                let inbox = format!("{}.{sequence:016x}", inner.inbox_namespace);
                let event_id = request::message_id(
                    &inner.config.idempotency_namespace,
                    &inner.config.topics[row].tenant,
                    &owner.event,
                );
                protocol::subscribe(connection.resource(), &call, &inbox).await?;
                network::check_current(&inner.credentials[credential], &auth.stamp)?;
                let receipt = protocol::publish(
                    connection.resource(),
                    &call,
                    &owner.event,
                    &inner.config.topics[row],
                    &inbox,
                    &event_id,
                    &mut wrote,
                )
                .await?;
                // Parking failure only closes the socket; a valid acknowledgement
                // remains valid. No driver or activation survives in idle state.
                let _ = connection.park();
                Ok::<_, EventError>(receipt)
            }
            .await;
            call.io_mut()
                .record_provider_outcome(inner.observe(&result, wrote))?;
            call.io_mut().finish_audit().await;
            let receipt = result?;
            call.io().checkpoint()?;
            drop(owner);
            Ok(EventCompletion {
                receipt,
                owner: call,
            })
        }))
    }
}
impl Inner {
    fn observe(
        &self,
        result: &Result<latent_capabilities::broker::events::PublishReceipt>,
        wrote: bool,
    ) -> AuditProviderOutcome {
        match result {
            Ok(_) => {
                tick(&self.acknowledged);
                AuditProviderOutcome::BrokerAcknowledged
            }
            Err(EventError::Uncertain) => {
                tick(&self.uncertain);
                AuditProviderOutcome::Unknown
            }
            Err(_) if !wrote => AuditProviderOutcome::NotStarted,
            Err(_) => AuditProviderOutcome::Rejected,
        }
    }
}
pub(crate) fn tick(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
        Some(n.saturating_add(1))
    });
}
