//! Trusted input history on the original pull, provider and admission owners.
use super::{config::identifier, wire, TriggerBinding, TriggerConfig};
use crate::{
    config::text,
    deferred::{qualification, JetStreamQualification},
    network::{Connection, Scope},
    protocol, EventError, Result,
};
use latent_capabilities::broker::pools::{IngressRequest, InstalledProvider};
use latent_commit::atomic::{Identity, InboxIdentity};
use latent_core::PlatformError;
use latent_node::{InboundActivationReservation, TransactionActivationAdmission};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::sync::Arc;

/// The existing command identity protection window. An input stream must keep
/// accepted history for at least the same window, or retain it without age eviction.
pub const INBOX_IDENTITY_RETENTION_MILLIS: u64 = 604_800_000;

/// Closed operator opt-in. Credentials, consumer display names, delivery counts
/// and activation IDs never select the durable processing identity.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransactionalBinding {
    pub processing_scope: String,
    pub namespace: String,
    pub incarnation: u64,
    pub qualification: JetStreamQualification,
    pub duplicate_window_millis: u64,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub effect_count: u32,
}
impl TransactionalBinding {
    pub(super) fn validate(&self, binding: &TriggerBinding, config: &TriggerConfig) -> Result<()> {
        if !identifier(&self.processing_scope)
            || self.processing_scope.capacity() > 128
            || !text(&self.namespace, 128)
            || self.namespace.capacity() > 128
            || self.incarnation == 0
            || !(1000..=86_400_000).contains(&self.duplicate_window_millis)
            || binding.budget.child_calls != 0
            || binding.budget.outbound_requests != 0
            || self.state_read_bytes > 8 * 1024 * 1024
            || self.state_write_bytes > 8 * 1024 * 1024
            || self.effect_count > 32
        {
            return Err(EventError::InvalidEvent);
        }
        self.qualification.validate_limits(
            config.maximum_payload_bytes + 5120,
            INBOX_IDENTITY_RETENTION_MILLIS,
        )
    }
}

/// The installed host implements this seam using its normal command factory.
/// The reservation is the original prepaid input/admission owner. The delivery
/// can only be constructed by this provider after authenticated qualification.
pub trait InboxAdmissionFactory: Send + Sync {
    fn admission(
        &self,
        reservation: &InboundActivationReservation,
        delivery: &InboxDelivery,
    ) -> std::result::Result<Arc<dyn TransactionActivationAdmission>, PlatformError>;
}

/// Bounded descriptive identity captured from a trusted broker delivery. It
/// grants no namespace, publication or command authority by itself.
#[derive(Clone, Debug)]
pub struct InboxDelivery {
    tenant: String,
    namespace: String,
    incarnation: u64,
    processing_scope: String,
    client_id: String,
    identity: InboxIdentity,
}
impl InboxDelivery {
    #[must_use]
    pub fn tenant(&self) -> &str {
        &self.tenant
    }
    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.namespace
    }
    #[must_use]
    pub const fn incarnation(&self) -> u64 {
        self.incarnation
    }
    #[must_use]
    pub fn processing_scope(&self) -> &str {
        &self.processing_scope
    }
    #[must_use]
    pub fn client_id(&self) -> &str {
        &self.client_id
    }
    #[must_use]
    pub fn identity(&self) -> &InboxIdentity {
        &self.identity
    }

    pub(super) fn capture(
        provider: &InstalledProvider,
        binding: &TriggerBinding,
        qualified: QualifiedStream,
        sequence: u64,
        payload: &[u8],
    ) -> Result<Self> {
        capture(provider.logical_id(), binding, qualified, sequence, payload)
    }

    pub(super) fn matches(&self, record: &latent_commit::atomic::CommandRecord) -> bool {
        let key = record.key();
        key.tenant == self.tenant
            && key.namespace == self.namespace
            && key.incarnation == self.incarnation.to_string()
            && key.client_key == self.client_id
            && record.inbox_identity() == Some(&self.identity)
    }
}

fn capture(
    provider: &str,
    binding: &TriggerBinding,
    qualified: QualifiedStream,
    sequence: u64,
    payload: &[u8],
) -> Result<InboxDelivery> {
    let selected = binding
        .transaction
        .as_ref()
        .ok_or(EventError::PermissionDenied)?;
    if sequence == 0 || !text(provider, 128) || qualified.binding != binding_identity(binding)? {
        return Err(EventError::PermissionDenied);
    }
    let incarnation = selected.incarnation.to_le_bytes();
    let scope = identity(
        b"lsf-jetstream-input-scope-v1\0",
        &[
            binding.tenant.as_bytes(),
            provider.as_bytes(),
            binding.stream.as_bytes(),
            selected.qualification.stream_created.as_bytes(),
            selected.processing_scope.as_bytes(),
            selected.namespace.as_bytes(),
            &incarnation,
        ],
    );
    let sequence_bytes = sequence.to_le_bytes();
    let client = identity(
        b"lsf-jetstream-input-command-v1\0",
        &[&scope.bytes(), &sequence_bytes],
    );
    let payload_digest = Identity::parse_hex(&format!(
        "{:x}",
        latent_core::digest::HexDigest(Sha256::digest(payload))
    ))
    .map_err(|_| EventError::InvalidEvent)?;
    Ok(InboxDelivery {
        tenant: binding.tenant.clone(),
        namespace: selected.namespace.clone(),
        incarnation: selected.incarnation,
        processing_scope: selected.processing_scope.clone(),
        client_id: format!("inbox-{}", client.hex()),
        identity: InboxIdentity {
            provider: provider.into(),
            binding: scope.hex(),
            message: sequence.to_string(),
            payload_digest,
        },
    })
}

fn identity(domain: &[u8], parts: &[&[u8]]) -> Identity {
    let mut hash = Sha256::new();
    hash.update(domain);
    for part in parts {
        hash.update((part.len() as u64).to_le_bytes());
        hash.update(part);
    }
    Identity::parse_hex(&format!(
        "{:x}",
        latent_core::digest::HexDigest(hash.finalize())
    ))
    .expect("fixed SHA-256 encoding")
}

fn binding_identity(binding: &TriggerBinding) -> Result<Identity> {
    let selected = binding
        .transaction
        .as_ref()
        .ok_or(EventError::PermissionDenied)?;
    let bytes = serde_json::to_vec(&(
        binding.tenant.as_str(),
        binding.stream.as_str(),
        binding.filter_subject.as_str(),
        selected,
    ))
    .map_err(|_| EventError::InvalidEvent)?;
    Ok(identity(b"lsf-qualified-input-binding-v1\0", &[&bytes]))
}

pub(super) struct QualifiedStream {
    binding: Identity,
}

/// Reuse the authenticated transport, literal stream validator and bounded
/// ingress request. No publisher, second connection or cached qualification.
pub(super) async fn qualify(
    connection: &mut Connection,
    request: &IngressRequest,
    binding: &TriggerBinding,
    inbox: &str,
) -> Result<QualifiedStream> {
    let selected = binding
        .transaction
        .as_ref()
        .ok_or(EventError::PermissionDenied)?;
    if connection.server_version.as_deref() != Some(&selected.qualification.server_version) {
        return Err(EventError::PermissionDenied);
    }
    request.begin_operation()?;
    let scope = Scope::from(request);
    protocol::subscribe(connection, scope, inbox).await?;
    wire::send(
        connection,
        scope,
        &format!("$JS.API.STREAM.INFO.{}", binding.stream),
        inbox,
        b"",
    )
    .await?;
    let response = wire::receive(connection, scope, &[inbox], 8192).await?;
    if response.reply.is_some() || response.headers != 0 {
        return Err(EventError::Unavailable);
    }
    qualification::validate_stream_response(
        response.payload(),
        &selected.qualification,
        &binding.stream,
        &[&binding.filter_subject],
        selected.duplicate_window_millis,
    )?;
    Ok(QualifiedStream {
        binding: binding_identity(binding)?,
    })
}

#[cfg(test)]
mod tests;
