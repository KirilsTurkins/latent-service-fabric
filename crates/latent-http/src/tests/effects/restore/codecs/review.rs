use super::*;

impl Codecs {
    // Called only by this installed synthetic operator fixture AFTER the real
    // remote receipt/counter observation. Neither snapshot nor request bytes
    // can install this decision. The worker never contacts a provider.
    pub(in super::super) fn approve_reconciliation(
        &self,
        guard: &RecoveryGuard,
        receipt: &str,
    ) -> [u8; 32] {
        assert_eq!(receipt.len(), 64);
        assert!(receipt
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)));
        let mut hash = Sha256::new();
        hash.update(b"latent.http-restore.operator-review.v1\0");
        hash.update(guard.encode().unwrap());
        for bytes in [
            self.authority.link().effect.as_bytes(),
            self.authority.payload_digest().as_bytes(),
            receipt.as_bytes(),
        ] {
            hash.update((bytes.len() as u64).to_le_bytes());
            hash.update(bytes);
        }
        hash.update(self.authority.expires_at_millis().to_le_bytes());
        let digest = hash.finalize().into();
        *self.reconciliation.lock().unwrap() = Some((guard.clone(), digest));
        digest
    }
    pub(super) fn check_reconciliation(
        &self,
        request: &RecoveryReviewRequest,
    ) -> Result<(), StoreError> {
        let expected = self
            .reconciliation
            .lock()
            .map_err(|_| StoreError::Unavailable)?;
        let Some((guard, digest)) = &*expected else {
            return Err(StoreError::Unavailable);
        };
        if guard != &request.expected_guard {
            return Err(StoreError::Conflict);
        }
        self.check_review(&request.operator_id, request.review_digest, *digest)
    }
    pub(super) fn check_operator(&self, operator: &str) -> Result<(), StoreError> {
        if operator != "operator" || !self.clock.observe().continuity_proven {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
    pub(super) fn check_review(
        &self,
        operator: &str,
        actual: [u8; 32],
        expected: [u8; 32],
    ) -> Result<(), StoreError> {
        self.check_operator(operator)?;
        if actual != expected {
            return Err(StoreError::Unavailable);
        }
        self.owner
            .commit_fence(std::slice::from_ref(&self.authority), self.clock.observe())
            .map(drop)
            .map_err(|_| StoreError::Unavailable)
    }
}

pub(super) fn reconcile(
    codecs: &Codecs,
    view: &ReadView,
    request: &RecoveryReviewRequest,
) -> Result<(), StoreError> {
    codecs.accept_reconciliation(request)?;
    codecs.validate_view(view)?;
    let actual = RecoveryGuard::capture(view)?.ok_or(StoreError::Corrupt)?;
    if actual != request.expected_guard {
        return Err(StoreError::Conflict);
    }
    // This explicit synthetic operator decision acknowledges that the remote
    // mutation was independently observed after the backup. The physical
    // worker performs no TLS lookup and does not resume or dispatch anything.
    let record = view
        .get(&latent_effects::dispatch_store::effect_row_key(
            &codecs.authority.link().effect,
        )?)?
        .ok_or(StoreError::Corrupt)?;
    if EffectRecord::decode(&record)
        .map_err(|_| StoreError::Corrupt)?
        .disposition()
        != Disposition::Pending
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}

pub(super) fn resume(
    codecs: &Codecs,
    view: &ReadView,
    request: &NamespaceResumeRequest,
    observed: latent_state::recovery::resume::NamespaceResumeObservation<'_>,
) -> Result<(), StoreError> {
    codecs.accept_namespace_resume(request)?;
    codecs.validate_view(view)?;
    let original = &codecs.authority.scope();
    if observed.namespace.tenant.0 != original.tenant
        || observed.namespace.id.0 != original.namespace
        || observed.namespace.version.incarnation != original.incarnation
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}
