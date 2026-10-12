//! Trusted installation captures the actual original secret generation. A
//! copied configuration epoch never supplies this owner or its currentness.
use super::{config, Arc, Generation, Inner, LocalSecretStore, ProviderMetadata, SecretError};
use crate::SecretPurpose;
use latent_capabilities::broker::secrets::{
    CredentialScope, ProviderCredential, TlsCredentialScope, TlsProviderCredential,
};

/// Opaque HTTP provider authentication from one actual original generation.
/// Retaining it keeps that generation's existing physical charge and zeroizing
/// bytes; no credential copy or independent generation reservation is created.
/// It never implements guest disclosure, serialization or Debug.
pub struct ProviderCredentialGeneration {
    owner: Arc<Inner>,
    generation: Arc<Generation>,
    index: usize,
    scope: CredentialScope,
    reference: String,
    // LAST: strings and original generation bytes drop before this metadata.
    _metadata: ProviderMetadata,
}

impl ProviderCredentialGeneration {
    /// Descriptive identity of the original installed generation. Recheck before
    /// installation; possession of the number does not authorize dispatch.
    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation.number
    }

    /// No-I/O installation fence: the same original owner, generation pointer,
    /// number, scope and expiry must still be current. No value is exposed.
    pub fn with_current_generation(
        &self,
        action: &mut dyn FnMut(u64) -> Result<(), SecretError>,
    ) -> Result<(), SecretError> {
        self.owner
            .with_current(&self.generation, self.index, |entry| {
                match &entry.spec.purpose {
                    SecretPurpose::ProviderCredential {
                        provider_id,
                        origin,
                    } if *provider_id == self.scope.provider_id && *origin == self.scope.origin => {
                    }
                    _ => return Err(SecretError::PermissionDenied),
                }
                action(self.generation.number)
            })
    }
}

impl ProviderCredential for ProviderCredentialGeneration {
    fn scope(&self) -> &CredentialScope {
        &self.scope
    }
    fn reference(&self) -> &str {
        &self.reference
    }
    fn with_current_value(
        &self,
        action: &mut dyn FnMut(&[u8]) -> Result<(), SecretError>,
    ) -> Result<(), SecretError> {
        self.owner
            .with_current(&self.generation, self.index, |entry| {
                match &entry.spec.purpose {
                    SecretPurpose::ProviderCredential {
                        provider_id,
                        origin,
                    } if *provider_id == self.scope.provider_id && *origin == self.scope.origin => {
                    }
                    _ => return Err(SecretError::PermissionDenied),
                }
                action(&entry.bytes)
            })
    }
}

/// A TLS protocol purpose/destination remains separate from HTTP credentials.
/// The retained generation is the original charged object, never a refreshed
/// lookup into a later generation at adapter acceptance.
pub struct TlsProviderCredentialGeneration {
    owner: Arc<Inner>,
    generation: Arc<Generation>,
    index: usize,
    scope: TlsCredentialScope,
    reference: String,
    _metadata: ProviderMetadata,
}

impl TlsProviderCredentialGeneration {
    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation.number
    }

    /// Recheck currentness without copying or exposing credential bytes. The
    /// bounded callback must not wait, perform I/O or reenter the secret owner.
    pub fn with_current_generation(
        &self,
        action: &mut dyn FnMut(u64) -> Result<(), SecretError>,
    ) -> Result<(), SecretError> {
        self.owner
            .with_current(&self.generation, self.index, |entry| {
                match &entry.spec.purpose {
                    SecretPurpose::TlsProviderCredential {
                        provider_id,
                        destination,
                    } if *provider_id == self.scope.provider_id
                        && *destination == self.scope.destination => {}
                    _ => return Err(SecretError::PermissionDenied),
                }
                action(self.generation.number)
            })
    }
}

impl TlsProviderCredential for TlsProviderCredentialGeneration {
    fn scope(&self) -> &TlsCredentialScope {
        &self.scope
    }
    fn reference(&self) -> &str {
        &self.reference
    }
    fn with_current_value(
        &self,
        action: &mut dyn FnMut(&[u8]) -> Result<(), SecretError>,
    ) -> Result<(), SecretError> {
        self.owner
            .with_current(&self.generation, self.index, |entry| {
                match &entry.spec.purpose {
                    SecretPurpose::TlsProviderCredential {
                        provider_id,
                        destination,
                    } if *provider_id == self.scope.provider_id
                        && *destination == self.scope.destination => {}
                    _ => return Err(SecretError::PermissionDenied),
                }
                action(&entry.bytes)
            })
    }
}

impl LocalSecretStore {
    /// Trusted startup/control producer. Fixed metadata is prepaid before the
    /// original generation is captured; no environment/file read or value copy
    /// occurs. Rotation never silently retargets an already installed capture.
    pub fn capture_provider_credential(
        &self,
        scope: CredentialScope,
        reference: String,
    ) -> Result<Arc<ProviderCredentialGeneration>, SecretError> {
        check_identities(&scope.tenant.0, &scope.provider_id, &reference)?;
        if scope.origin.host.capacity() > 256 || scope.origin.scheme.capacity() > 8 {
            return Err(SecretError::PermissionDenied);
        }
        let metadata = self.inner.pools.reserve_protocol_metadata(2048)?;
        let generation = self.inner.generation()?;
        let index = generation
            .entries
            .iter()
            .position(|entry| {
                entry.spec.tenant == scope.tenant && entry.spec.reference == reference
            })
            .ok_or(SecretError::NotFound)?;
        let captured = ProviderCredentialGeneration {
            owner: Arc::clone(&self.inner),
            generation,
            index,
            scope,
            reference,
            _metadata: metadata,
        };
        captured.with_current_generation(&mut |_| Ok(()))?;
        Ok(Arc::new(captured))
    }

    pub fn capture_tls_provider_credential(
        &self,
        scope: TlsCredentialScope,
        reference: String,
    ) -> Result<Arc<TlsProviderCredentialGeneration>, SecretError> {
        check_identities(&scope.tenant.0, &scope.provider_id, &reference)?;
        scope.destination.validate()?;
        let metadata = self.inner.pools.reserve_protocol_metadata(2048)?;
        let generation = self.inner.generation()?;
        let index = generation
            .entries
            .iter()
            .position(|entry| {
                entry.spec.tenant == scope.tenant && entry.spec.reference == reference
            })
            .ok_or(SecretError::NotFound)?;
        let captured = TlsProviderCredentialGeneration {
            owner: Arc::clone(&self.inner),
            generation,
            index,
            scope,
            reference,
            _metadata: metadata,
        };
        captured.with_current_generation(&mut |_| Ok(()))?;
        Ok(Arc::new(captured))
    }
}

fn check_identities(
    tenant: &String,
    provider: &String,
    reference: &String,
) -> Result<(), SecretError> {
    if !config::text(tenant, 128)
        || tenant.capacity() > 128
        || !config::text(provider, 128)
        || provider.capacity() > 128
        || !config::text(reference, 256)
        || reference.capacity() > 256
    {
        return Err(SecretError::PermissionDenied);
    }
    Ok(())
}
