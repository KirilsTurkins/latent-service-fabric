use crate::{
    store::{Generation, Inner as Store},
    LocalSecretStore, SecretError, SecretPurpose,
};
use latent_capabilities::broker::{
    io::IoMemory,
    pools::{
        InstalledProvider, PoolCall, ProviderClient, ProviderMetadata, ProviderPools, ProviderSetup,
    },
    secrets::{
        SecretDisclosure, SecretFuture, SecretInvoker, SecretLowering, SecretView,
        SECRETS_CAPABILITY,
    },
    AuditProviderOutcome, CapabilityCallCost, CapabilityRequestDigest, CapabilitySession,
    ProviderConfiguration, ProviderReference,
};
use latent_policy::capability::ResourceTarget;
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub const LOCAL_SECRETS_PROFILE: &str = "protected-local-secrets-v1";
#[derive(Clone)]
pub struct LocalSecretProvider {
    inner: Arc<Inner>,
}
struct Inner {
    store: Arc<Store>,
    pools: Arc<ProviderPools>,
    installed: InstalledProvider,
    client: Arc<ProviderClient<()>>,
    _metadata: ProviderMetadata,
}
impl LocalSecretProvider {
    pub fn install(
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        store: &LocalSecretStore,
    ) -> Result<Self, SecretError> {
        let pools = &store.inner.pools;
        let metadata = pools.reserve_protocol_metadata(32768)?;
        let generation = store.inner.generation()?;
        let mut references: Vec<_> = generation
            .entries
            .iter()
            .filter(|e| matches!(e.spec.purpose, SecretPurpose::GuestValue))
            .map(|e| e.spec.reference.as_str())
            .collect();
        references.sort_unstable();
        references.dedup();
        let restrictions = serde_json::to_vec(&serde_json::json!({
            "operations": ["read"], "resources": {"kind":"secrets", "references": references}
        }))
        .map_err(|_| SecretError::Unavailable)?;
        let mut hash = Sha256::new();
        hash.update(b"protected-local-secrets-v1\0");
        hash.update(store.inner.root.identity().0.to_le_bytes());
        hash.update(store.inner.root.identity().1.to_le_bytes());
        hash.update(&restrictions);
        for n in [
            store.inner.limits.maximum_references,
            store.inner.limits.maximum_value_bytes,
            store.inner.limits.maximum_generation_bytes,
            store.inner.limits.maximum_generations,
            store.inner.limits.maximum_environment_bytes,
        ] {
            hash.update((n as u64).to_le_bytes());
        }
        // No material, version, expiry or hash of a secret enters public identity.
        let digest = format!("sha256:{:x}", hash.finalize());
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: SECRETS_CAPABILITY,
                    profile: LOCAL_SECRETS_PROFILE,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: &restrictions,
                    minimum_call_charges: &[],
                },
            },
            expected_epoch,
        )?;
        let client = pools.client(&installed, 0)?;
        Ok(Self {
            inner: Arc::new(Inner {
                store: store.inner.clone(),
                pools: pools.clone(),
                installed,
                client,
                _metadata: metadata,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
}
impl SecretInvoker for LocalSecretProvider {
    fn read(
        &self,
        session: &CapabilitySession,
        reference: String,
    ) -> Result<SecretFuture, SecretError> {
        if !crate::config::text(&reference, 256)
            || reference.capacity() > 256
            || !session.uses_provider(&self.reference())?
        {
            return Err(SecretError::PermissionDenied);
        }
        self.inner.store.check()?;
        let admission = self.inner.pools.admit(&self.inner.client, session)?;
        let input = admission.reserve_input(reference.capacity().max(1), 2048)?;
        let tenant = session.tenant().clone();
        let digest =
            CapabilityRequestDigest::from_parts(&[b"secret-read-v1", reference.as_bytes()])?;
        let cost = CapabilityCallCost::new(self.inner.store.limits.maximum_value_bytes + 1024)
            .with_typed_input_bytes(reference.len())
            .with_typed_request_digest(digest);
        let inner = self.inner.clone();
        Ok(Box::pin(async move {
            let mut call = admission
                .wait()
                .await?
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
            let result = (|| {
                let generation = inner.store.generation()?;
                let index = generation
                    .entries
                    .iter()
                    .position(|e| e.spec.tenant == tenant && e.spec.reference == reference)
                    .ok_or(SecretError::NotFound)?;
                let size = inner.store.with_current(&generation, index, |entry| {
                    if !matches!(entry.spec.purpose, SecretPurpose::GuestValue) {
                        return Err(SecretError::PermissionDenied);
                    }
                    Ok(entry.bytes.len()
                        + entry.spec.version.len()
                        + entry.spec.media_type.len()
                        + 128)
                })?;
                let copy = call.io().reserve_scratch(size, 2048)?;
                Ok::<_, SecretError>((generation, index, copy))
            })();
            call.io_mut().record_provider_outcome(if result.is_ok() {
                AuditProviderOutcome::SecretResolved
            } else {
                AuditProviderOutcome::Rejected
            })?;
            call.io_mut().finish_audit().await;
            call.io().checkpoint()?;
            let (generation, index, copy) = result?;
            drop(input);
            Ok(Box::new(Disclosure {
                store: inner.store.clone(),
                generation,
                index,
                copy,
                call,
            }) as Box<dyn SecretDisclosure>)
        }))
    }
}
struct Disclosure {
    store: Arc<Store>,
    generation: Arc<Generation>,
    index: usize,
    copy: IoMemory,
    call: PoolCall,
}
impl SecretDisclosure for Disclosure {
    fn disclose(
        self: Box<Self>,
        copy: &mut dyn FnMut(SecretView<'_>),
    ) -> Result<SecretLowering, SecretError> {
        self.call.io().checkpoint()?;
        self.store
            .with_current(&self.generation, self.index, |entry| {
                self.call.io().checkpoint()?;
                copy(SecretView {
                    bytes: &entry.bytes,
                    media_type: &entry.spec.media_type,
                    version: &entry.spec.version,
                    expires_at_unix_millis: entry.spec.expires_at_unix_millis,
                });
                Ok(())
            })?;
        Ok(SecretLowering::new(self.call, self.copy))
    }
}
