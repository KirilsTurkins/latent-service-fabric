use super::{
    auth, cache, remote, tick, Arc, Inner, Ordering, Result, SecretError, VaultSecretProvider,
};
use latent_capabilities::broker::{
    io::IoMemory,
    pools::PoolCall,
    secrets::{
        SecretDisclosure, SecretFuture, SecretInvoker, SecretLowering, SecretView,
        SECRETS_CAPABILITY,
    },
    AuditProviderOutcome, CapabilityCallCost, CapabilityRequestDigest, CapabilitySession,
};
use latent_core::BudgetDimension;
use latent_policy::capability::ResourceTarget;

struct Active(Arc<Inner>);
impl Drop for Active {
    fn drop(&mut self) {
        self.0.active.fetch_sub(1, Ordering::AcqRel);
    }
}
impl SecretInvoker for VaultSecretProvider {
    #[expect(
        clippy::too_many_lines,
        reason = "keep selection, reserved costs, guarded dispatch, audit and disclosure ownership together"
    )]
    fn read(&self, session: &CapabilitySession, reference: String) -> Result<SecretFuture> {
        if !crate::config::text(&reference, 256)
            || reference.capacity() > 256
            || !session.uses_provider(&self.reference())?
        {
            return Err(SecretError::PermissionDenied);
        }
        self.inner.check()?;
        let admission = self
            .inner
            .transport
            .admit(session)
            .map_err(|_| SecretError::Unavailable)?;
        let input = admission.reserve_input(reference.capacity().max(1), 2048)?;
        let tenant = session.tenant().clone();
        let inner = self.inner.clone();
        let digest =
            CapabilityRequestDigest::from_parts(&[b"vault-kv-v2-read-v1", reference.as_bytes()])?;
        Ok(Box::pin(async move {
            let ready = admission.wait().await?;
            // Selection derives actual costs, but no selection failure or cached
            // data reaches the caller before the original broker grant check.
            let _authentication = inner.pools.reserve_protocol_metadata(32768)?;
            let selection = (|| {
                inner.check()?;
                let index = inner
                    .config
                    .references
                    .iter()
                    .position(|r| r.tenant == tenant.0 && r.reference == reference)
                    .ok_or(SecretError::NotFound)?;
                inner.expiry[index].check(inner.clock.sample())?;
                let auth = auth::Auth::current(&inner, index)?;
                let cached = inner
                    .cache
                    .try_lock()
                    .map_err(|_| SecretError::Unavailable)?
                    .cached(index, &auth.stamp, inner.clock.sample());
                Ok::<_, SecretError>((index, auth, cached))
            })();
            let mut cost = CapabilityCallCost::new(inner.config.limits.maximum_value_bytes + 1024)
                .with_typed_input_bytes(reference.len())
                .with_typed_request_digest(digest);
            if matches!(&selection, Ok((_, _, None))) {
                cost = cost.with_charge(BudgetDimension::OutboundRequests, 1)?;
            }
            let mut call = ready
                .dispatch(
                    SECRETS_CAPABILITY,
                    "read",
                    ResourceTarget::Secrets {
                        reference: &reference,
                    },
                    &[],
                    cost,
                )
                .await?;
            inner.active.fetch_add(1, Ordering::AcqRel);
            let _active = Active(inner.clone());
            let result = async {
                let (index, auth, cached) = selection?;
                inner.check()?;
                call.io().checkpoint()?;
                let value = if let Some(value) = cached {
                    auth::with_current(&inner, index, &auth.stamp, &mut || {
                        inner
                            .cache
                            .try_lock()
                            .map_err(|_| SecretError::Unavailable)?
                            .verify(index, &value, inner.clock.sample())
                    })?;
                    tick(&inner.hits);
                    value
                } else {
                    let sequence = inner
                        .cache
                        .try_lock()
                        .map_err(|_| SecretError::Unavailable)?
                        .begin(index)?;
                    remote::fetch(&inner, &call, index, sequence, auth).await?
                };
                let copy = call.io().reserve_scratch(value.bytes.len() + 1024, 2048)?;
                Ok::<_, SecretError>((index, value, copy))
            }
            .await;
            if result.is_err() {
                tick(&inner.rejected);
            }
            call.io_mut().record_provider_outcome(if result.is_ok() {
                AuditProviderOutcome::SecretResolved
            } else {
                AuditProviderOutcome::Rejected
            })?;
            call.io_mut().finish_audit().await;
            call.io().checkpoint()?;
            let (index, value, copy) = result?;
            drop(input);
            Ok(Box::new(Disclosure {
                inner: inner.clone(),
                index,
                value,
                copy,
                call,
            }) as Box<dyn SecretDisclosure>)
        }))
    }
}
struct Disclosure {
    inner: Arc<Inner>,
    index: usize,
    value: Arc<cache::Value>,
    copy: IoMemory,
    call: PoolCall,
}
impl SecretDisclosure for Disclosure {
    fn disclose(self: Box<Self>, copy: &mut dyn FnMut(SecretView<'_>)) -> Result<SecretLowering> {
        self.inner.check()?;
        self.call.io().checkpoint()?;
        // Fixed lock order: credential generation, then the bounded cache view.
        // Rotation and a newer same-reference result cannot cross the copy fence.
        auth::with_current(&self.inner, self.index, &self.value.token, &mut || {
            let cache = self
                .inner
                .cache
                .try_lock()
                .map_err(|_| SecretError::Unavailable)?;
            self.inner.check()?;
            let now = self.inner.clock.sample();
            self.inner.expiry[self.index].check(now)?;
            cache.verify(self.index, &self.value, now)?;
            self.call.io().checkpoint()?;
            copy(SecretView {
                bytes: &self.value.bytes,
                media_type: &self.inner.config.references[self.index].media_type,
                version: &self.value.version_text,
                expires_at_unix_millis: self.value.expiry.unix,
            });
            Ok(())
        })?;
        Ok(SecretLowering::new(self.call, self.copy))
    }
}
