//! Verified physical attachments are part of the original complete envelope.
//! Inline provider bytes stay unchanged; this does not dispatch reference DTOs.
use super::{
    incarnation, AtomicError, CompleteEnvelope, EmbeddedStore, Family, NamespaceRecord, Outcome,
    PreparedDisposition, ReadView, TenantId, Usage,
};
use latent_blobs::provider::CapturedLocalPayload;
use latent_capabilities::broker::CapabilitySession;
use latent_effects::{
    authority::DurableEffectAuthority, dispatch_store::effect_payload_key, payload::PayloadRecord,
};
use latent_state::{
    payload_references::{
        PayloadOwner, PayloadOwnerKind, PayloadReference, PreparedPayloadReferences,
        MAX_REFERENCE_UPDATES,
    },
    store_identity::StoreIdentity,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PayloadAttachmentTarget {
    Result,
    Effect(u32),
}
pub struct PayloadAttachment {
    pub target: PayloadAttachmentTarget,
    pub payload: CapturedLocalPayload,
}
impl CompleteEnvelope {
    /// Derive ownership from the real terminal command/effect, never a guest
    /// reference count or claimed commit identifier. The same original session
    /// owner and verified bytes must match before any batch plan is changed.
    pub fn attach_verified_payloads(
        mut self,
        view: &ReadView,
        original_session: &CapabilitySession,
        attachments: Vec<PayloadAttachment>,
    ) -> Result<Self, AtomicError> {
        if attachments.is_empty()
            || attachments.len() > MAX_REFERENCE_UPDATES
            || !self.payloads.is_empty()
            || !matches!(
                self.terminal.outcome,
                Outcome::Committed | Outcome::Rejected
            )
        {
            return Err(AtomicError::Invalid);
        }
        let store_identity = StoreIdentity::inspect(view)?.ok_or(AtomicError::Invalid)?;
        original_session
            .check_liveness()
            .map_err(|_| AtomicError::PermissionDenied)?;
        if original_session.tenant().0 != self.terminal.key.tenant
            || !original_session.uses_publication(&self.terminal.source.publication)
        {
            return Err(AtomicError::PermissionDenied);
        }
        let mut updates = Vec::with_capacity(attachments.len());
        let mut payloads = Vec::with_capacity(attachments.len());
        let mut full_bytes = 0u64;
        for attachment in attachments {
            let payload = attachment.payload;
            if !payload.uses_session(original_session)
                || payload.identity().tenant != self.terminal.key.tenant
                || payload.store_identity() != store_identity.as_str()
            {
                return Err(AtomicError::PermissionDenied);
            }
            let (identity, kind, format) = match attachment.target {
                PayloadAttachmentTarget::Result => {
                    let value = self.result.value().ok_or(AtomicError::Invalid)?;
                    payload
                        .verify_inline_value(value)
                        .map_err(|_| AtomicError::Corrupt)?;
                    (
                        self.terminal.id.0,
                        PayloadOwnerKind::Result,
                        self.terminal.source.result_format.clone(),
                    )
                }
                PayloadAttachmentTarget::Effect(sequence) => {
                    if self.terminal.outcome != Outcome::Committed {
                        return Err(AtomicError::Invalid);
                    }
                    let index = usize::try_from(sequence).map_err(|_| AtomicError::Invalid)?;
                    let effect = self
                        .terminal
                        .effects
                        .get(index)
                        .ok_or(AtomicError::Invalid)?;
                    let authority = self.authorities.get(index).ok_or(AtomicError::Invalid)?;
                    if authority.link().effect != effect.hex()
                        || authority.link().command != self.terminal.id.hex()
                        || authority.link().attempt != self.terminal.attempt
                        || authority.link().commit != self.terminal.disposition_id().hex()
                    {
                        return Err(AtomicError::Corrupt);
                    }
                    let key = effect_payload_key(&effect.hex())?;
                    let bytes = self
                        .batch
                        .mutations
                        .iter()
                        .find(|row| row.key == key)
                        .and_then(|row| row.value.as_deref())
                        .ok_or(AtomicError::Corrupt)?;
                    let stored = PayloadRecord::decode(bytes)?;
                    stored.verify(authority)?;
                    payload
                        .verify_inline_value(stored.value())
                        .map_err(|_| AtomicError::Corrupt)?;
                    (
                        effect.0,
                        PayloadOwnerKind::Effect,
                        authority.profile().payload_format.clone(),
                    )
                }
            };
            full_bytes = full_bytes
                .checked_add(payload.identity().size)
                .ok_or(AtomicError::Limit)?;
            updates.push((
                None,
                Some(PayloadReference {
                    owner: PayloadOwner {
                        tenant: self.terminal.key.tenant.clone(),
                        namespace: self.terminal.key.namespace.clone(),
                        incarnation: incarnation(&self.terminal.key)?,
                        kind,
                        identity,
                        generation: self.terminal.attempt,
                        format,
                    },
                    payload: payload.identity().clone(),
                }),
            ));
            payloads.push(payload);
        }
        let mut plan = PreparedPayloadReferences::prepare(view, &updates)?;
        let links = latent_state::payload_references::PayloadLinks {
            anchor: crate::atomic::payload_links::anchor(&self.terminal)?,
            references: updates
                .iter()
                .map(|(_, after)| after.clone().ok_or(AtomicError::Corrupt))
                .collect::<Result<Vec<_>, _>>()?,
        };
        plan.replace_links(view, None, Some(&links))?;
        let tenant = TenantId(self.terminal.key.tenant.clone());
        let tenant_delta = plan.tenant_delta(&tenant)?;
        let tenant_update = latent_state::tenant::prepare_update(view, &tenant, tenant_delta)?;
        let (_, usage_key, usage_original) = Usage::read(view, &self.terminal.key)?;
        if self
            .batch
            .expectations
            .iter()
            .find(|row| row.key == usage_key)
            .map(|row| &row.value)
            != Some(&usage_original)
        {
            return Err(AtomicError::Conflict);
        }
        let usage_position = self
            .batch
            .mutations
            .iter()
            .position(|row| row.key == usage_key)
            .ok_or(AtomicError::Corrupt)?;
        let mut usage = Usage::decode(
            self.batch.mutations[usage_position]
                .value
                .as_deref()
                .ok_or(AtomicError::Corrupt)?,
        )?;
        let namespace_position = self
            .batch
            .mutations
            .iter()
            .position(|row| {
                row.key.family == Family::Namespace && row.key.key.starts_with(b"ns-v1\0")
            })
            .ok_or(AtomicError::Corrupt)?;
        let mut namespace = NamespaceRecord::decode(
            self.batch.mutations[namespace_position]
                .value
                .as_deref()
                .ok_or(AtomicError::Corrupt)?,
        )
        .map_err(|_| AtomicError::Corrupt)?;
        if namespace.tenant != tenant
            || namespace.id.0 != self.terminal.key.namespace
            || namespace.version.incarnation != incarnation(&self.terminal.key)?
        {
            return Err(AtomicError::Corrupt);
        }
        // Existing result/effect byte ceilings already charged the same exact
        // inline value. External content additionally consumes full payload
        // quota; each actual row consumes engine and tenant metadata capacity.
        usage.payload_bytes = usage
            .payload_bytes
            .checked_add(full_bytes)
            .ok_or(AtomicError::Limit)?;
        usage.check(&namespace)?;
        namespace.pins.payload_references = namespace
            .pins
            .payload_references
            .checked_add(u64::try_from(updates.len()).map_err(|_| AtomicError::Limit)?)
            .ok_or(AtomicError::Limit)?;
        self.batch.mutations[usage_position].value = Some(usage.encode());
        self.batch.mutations[namespace_position].value =
            Some(namespace.encode().map_err(|_| AtomicError::Corrupt)?);
        plan.append_to(&mut self.batch)?;
        tenant_update.append_to(&mut self.batch)?;
        let retained = self
            .batch
            .expectations
            .iter()
            .map(|row| (&row.key, &row.value))
            .chain(
                self.batch
                    .mutations
                    .iter()
                    .map(|row| (&row.key, &row.value)),
            )
            .try_fold(0usize, |n, (key, value)| {
                n.checked_add(key.key.len())
                    .and_then(|n| n.checked_add(value.as_ref().map_or(0, Vec::len)))
                    .ok_or(AtomicError::Limit)
            })?;
        if retained > latent_core::transaction_contract::STAGED_BYTES
            || self.batch.expectations.len() > 1024
            || self.batch.mutations.len() > 1024
        {
            return Err(AtomicError::Limit);
        }
        self.payloads = payloads;
        Ok(self)
    }
    /// The installed coordinator checks current captured sessions and provider
    /// bindings in the SAME short acceptance fence as command/effect authority.
    /// The original verified physical pins outlive actual engine completion.
    pub fn publish_with_payloads(
        self,
        store: &EmbeddedStore,
        final_accept: impl FnOnce(
            &[DurableEffectAuthority],
            &[CapturedLocalPayload],
        ) -> Result<(), AtomicError>,
    ) -> PreparedDisposition {
        self.publish_fenced(store, |envelope| {
            final_accept(&envelope.authorities, &envelope.payloads)
        })
    }
}
