//! Verified physical attachments are part of the original complete envelope.
//! Inline provider bytes stay unchanged; this does not dispatch reference DTOs.
use super::{
    incarnation, AdmittedCommand, AtomicError, CompleteEnvelope, EmbeddedStore, Family,
    NamespaceRecord, Outcome, PreparedDisposition, ReadView, TenantId, Usage,
};
use latent_blobs::provider::CapturedLocalPayload;
use latent_capabilities::broker::CapabilitySession;
use latent_effects::{
    authority::DurableEffectAuthority, dispatch_store::effect_payload_key, payload::PayloadRecord,
};
use latent_state::{
    payload_references::{
        PayloadOwner, PayloadOwnerKind, PayloadReference, PreparedPayloadReferences,
        StatePayloadLink, MAX_REFERENCE_UPDATES,
    },
    store_identity::StoreIdentity,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PayloadAttachmentTarget {
    Result,
    Effect(u32),
    State(Vec<u8>),
}
pub struct PayloadAttachment {
    pub target: PayloadAttachmentTarget,
    pub payload: CapturedLocalPayload,
}
impl AdmittedCommand {
    /// The trusted runtime binds its original activation once, before payload
    /// capture. A later activation cannot replace this affine association.
    pub fn bind_payload_session(&mut self, session: &CapabilitySession) -> Result<(), AtomicError> {
        if self.payload_session.is_some() {
            return Err(AtomicError::Conflict);
        }
        session
            .check_liveness()
            .map_err(|_| AtomicError::PermissionDenied)?;
        if session.tenant().0 != self.record.key.tenant
            || !session.uses_publication(&self.record.source.publication)
        {
            return Err(AtomicError::PermissionDenied);
        }
        let binding = session
            .reserve_resource_table(4096)
            .map_err(|error| match error.code {
                latent_core::PlatformErrorCode::ResourceExhausted => AtomicError::Limit,
                latent_core::PlatformErrorCode::Unavailable => AtomicError::Unavailable,
                latent_core::PlatformErrorCode::DeadlineExceeded => AtomicError::Expired,
                _ => AtomicError::PermissionDenied,
            })?;
        self.payload_session = Some(binding);
        Ok(())
    }
}
impl CompleteEnvelope {
    /// Derive ownership from the real terminal command/effect, never a guest
    /// reference count or claimed commit identifier. The same original session
    /// owner and verified bytes must match before any batch plan is changed.
    /// The trusted runtime must have bound the originating attempt to this
    /// session before capture; that association cannot later be replaced.
    pub fn attach_verified_payloads(
        self,
        view: &ReadView,
        original_session: &CapabilitySession,
        attachments: Vec<PayloadAttachment>,
    ) -> Result<Self, AtomicError> {
        if (attachments.is_empty() && self.old_state_payloads.is_empty())
            || attachments
                .len()
                .saturating_add(self.old_state_payloads.len())
                > MAX_REFERENCE_UPDATES
            || !self.payloads.is_empty()
            || self.state_detach_only
            || !matches!(
                self.terminal.outcome,
                Outcome::Committed | Outcome::Rejected
            )
        {
            return Err(AtomicError::Invalid);
        }
        original_session
            .check_liveness()
            .map_err(|_| AtomicError::PermissionDenied)?;
        let binding = self
            .claim
            .payload_session
            .as_ref()
            .ok_or(AtomicError::PermissionDenied)?;
        if !binding.with_session(|session| session.is_same_session(original_session))
            || original_session.tenant().0 != self.terminal.key.tenant
            || !original_session.uses_publication(&self.terminal.source.publication)
            || self
                .state_binding
                .as_ref()
                .is_some_and(|binding| !view.is_bound_to(binding))
        {
            return Err(AtomicError::PermissionDenied);
        }
        self.reconcile_payload_updates(view, Some(original_session), attachments)
    }

    /// Reconcile only old state links displaced by this sealed state plan. This
    /// grants no blob read or physical deletion authority; the same-engine
    /// state commit and the host's current state authority fence remain required.
    pub fn reconcile_replaced_state_payloads(self, view: &ReadView) -> Result<Self, AtomicError> {
        if self.old_state_payloads.is_empty() {
            return Ok(self);
        }
        if !self.payloads.is_empty()
            || self.state_detach_only
            || self.terminal.outcome != Outcome::Committed
            || !self
                .state_binding
                .as_ref()
                .is_some_and(|binding| view.is_bound_to(binding))
        {
            return Err(AtomicError::PermissionDenied);
        }
        let mut envelope = self.reconcile_payload_updates(view, None, Vec::new())?;
        envelope.state_detach_only = true;
        Ok(envelope)
    }

    #[expect(
        clippy::too_many_lines,
        reason = "Validate and charge all payload ownership changes as one atomic envelope"
    )]
    fn reconcile_payload_updates(
        mut self,
        view: &ReadView,
        original_session: Option<&CapabilitySession>,
        attachments: Vec<PayloadAttachment>,
    ) -> Result<Self, AtomicError> {
        let store_identity = StoreIdentity::inspect(view)?.ok_or(AtomicError::Invalid)?;
        let mut updates = Vec::with_capacity(attachments.len() + self.old_state_payloads.len());
        let mut state_links = Vec::new();
        let mut removed_bytes = 0u64;
        for link in &self.old_state_payloads {
            removed_bytes = removed_bytes
                .checked_add(link.reference.payload.size)
                .ok_or(AtomicError::Limit)?;
            updates.push((Some(link.reference.clone()), None));
        }
        let mut payloads = Vec::with_capacity(attachments.len());
        let mut full_bytes = 0u64;
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
        for attachment in attachments {
            let original_session = original_session.ok_or(AtomicError::PermissionDenied)?;
            let payload = attachment.payload;
            if !payload.uses_session(original_session)
                || !payload.uses_store_view(view)
                || payload.identity().tenant != self.terminal.key.tenant
                || payload.store_identity() != store_identity.as_str()
            {
                return Err(AtomicError::PermissionDenied);
            }
            let owner = match attachment.target {
                PayloadAttachmentTarget::Result => {
                    let value = self.result.value().ok_or(AtomicError::Invalid)?;
                    payload
                        .verify_inline_value(value)
                        .map_err(|_| AtomicError::Corrupt)?;
                    PayloadOwner {
                        tenant: self.terminal.key.tenant.clone(),
                        namespace: self.terminal.key.namespace.clone(),
                        incarnation: incarnation(&self.terminal.key)?,
                        kind: PayloadOwnerKind::Result,
                        identity: self.terminal.id.0,
                        generation: self.terminal.attempt,
                        format: self.terminal.source.result_format.clone(),
                    }
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
                    PayloadOwner {
                        tenant: self.terminal.key.tenant.clone(),
                        namespace: self.terminal.key.namespace.clone(),
                        incarnation: incarnation(&self.terminal.key)?,
                        kind: PayloadOwnerKind::Effect,
                        identity: effect.0,
                        generation: self.terminal.attempt,
                        format: authority.profile().payload_format.clone(),
                    }
                }
                PayloadAttachmentTarget::State(key) => {
                    if self.terminal.outcome != Outcome::Committed {
                        return Err(AtomicError::Invalid);
                    }
                    let scope = super::super::record::record_scope(&self.terminal)?;
                    let cell_key = latent_state::session::state_payload_cell_key(&scope, &key)?;
                    let bytes = self
                        .batch
                        .mutations
                        .iter()
                        .find(|row| row.key == cell_key)
                        .and_then(|row| row.value.as_deref())
                        .ok_or(AtomicError::Invalid)?;
                    let (owner, value) =
                        latent_state::session::describe_staged_state_payload_owner(
                            &cell_key, bytes, &namespace,
                        )?;
                    payload
                        .verify_inline_value(&value)
                        .map_err(|_| AtomicError::Corrupt)?;
                    state_links.push((cell_key, owner.clone(), payload.identity().clone()));
                    owner
                }
            };
            full_bytes = full_bytes
                .checked_add(payload.identity().size)
                .ok_or(AtomicError::Limit)?;
            updates.push((
                None,
                Some(PayloadReference {
                    owner,
                    payload: payload.identity().clone(),
                }),
            ));
            payloads.push(payload);
        }
        let mut plan = PreparedPayloadReferences::prepare(view, &updates)?;
        for link in &self.old_state_payloads {
            plan.replace_state_link(view, Some(link), None)?;
        }
        for (cell_key, owner, identity) in state_links {
            plan.replace_state_link(
                view,
                None,
                Some(&StatePayloadLink {
                    reference: PayloadReference {
                        owner,
                        payload: identity,
                    },
                    cell_key,
                }),
            )?;
        }
        let references = updates
            .iter()
            .filter_map(|(_, after)| after.as_ref())
            .filter(|reference| reference.owner.kind != PayloadOwnerKind::State)
            .cloned()
            .collect::<Vec<_>>();
        if !references.is_empty() {
            let links = latent_state::payload_references::PayloadLinks {
                anchor: crate::atomic::payload_links::anchor(&self.terminal)?,
                references,
            };
            plan.replace_links(view, None, Some(&links))?;
        }
        let tenant = TenantId(self.terminal.key.tenant.clone());
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
            .checked_sub(removed_bytes)
            .ok_or(AtomicError::Corrupt)?
            .checked_add(full_bytes)
            .ok_or(AtomicError::Limit)?;
        usage.check(&namespace)?;
        namespace.pins.payload_references = namespace
            .pins
            .payload_references
            .checked_sub(
                u64::try_from(self.old_state_payloads.len()).map_err(|_| AtomicError::Limit)?,
            )
            .ok_or(AtomicError::Corrupt)?
            .checked_add(u64::try_from(payloads.len()).map_err(|_| AtomicError::Limit)?)
            .ok_or(AtomicError::Limit)?;
        self.batch.mutations[usage_position].value = Some(usage.encode()?);
        self.batch.mutations[namespace_position].value =
            Some(namespace.encode().map_err(|_| AtomicError::Corrupt)?);
        plan.append_to(&mut self.batch)?;
        super::super::accounting::apply(view, &tenant, &mut self.batch)?;
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
        self.old_state_payloads.clear();
        Ok(self)
    }
    /// The trusted host must check current captured sessions and provider
    /// bindings in the same acceptance fence as command/effect authority.
    /// The original verified physical pins outlive actual engine completion.
    /// This low-level entry is not yet installed in the production coordinator.
    pub fn publish_with_payloads(
        self,
        store: &EmbeddedStore,
        final_accept: impl FnOnce(
            &[DurableEffectAuthority],
            &[CapturedLocalPayload],
        ) -> Result<(), AtomicError>,
    ) -> PreparedDisposition {
        if !self.old_state_payloads.is_empty()
            || self
                .state_binding
                .as_ref()
                .is_some_and(|binding| !store.is_bound_to(binding))
            || self
                .payloads
                .iter()
                .any(|payload| !payload.uses_store(store))
        {
            return PreparedDisposition::KnownNotCommitted {
                command: Box::new(self.claim),
                reason: AtomicError::PermissionDenied,
            };
        }
        self.publish_inner(
            store,
            |envelope| {
                let binding = envelope
                    .claim
                    .payload_session
                    .as_ref()
                    .ok_or(AtomicError::PermissionDenied)?;
                binding.with_session(|session| {
                    session
                        .check_liveness()
                        .map_err(|_| AtomicError::PermissionDenied)
                })?;
                final_accept(&envelope.authorities, &envelope.payloads)
            },
            || {},
        )
    }

    #[cfg(test)]
    pub(in crate::atomic) fn publish_payload_checkpoint(
        self,
        store: &EmbeddedStore,
        final_accept: impl FnOnce(
            &[DurableEffectAuthority],
            &[CapturedLocalPayload],
        ) -> Result<(), AtomicError>,
        after_commit: impl FnOnce(),
    ) -> PreparedDisposition {
        assert!(self.old_state_payloads.is_empty());
        assert!(self
            .payloads
            .iter()
            .all(|payload| payload.uses_store(store)));
        self.publish_inner(
            store,
            |envelope| {
                let binding = envelope
                    .claim
                    .payload_session
                    .as_ref()
                    .ok_or(AtomicError::PermissionDenied)?;
                binding.with_session(|session| {
                    session
                        .check_liveness()
                        .map_err(|_| AtomicError::PermissionDenied)
                })?;
                final_accept(&envelope.authorities, &envelope.payloads)
            },
            after_commit,
        )
    }
}
