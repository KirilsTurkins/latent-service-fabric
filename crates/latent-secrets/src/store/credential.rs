use super::{config, Arc, Inner, LocalSecretStore, ProviderMetadata, SecretError, SecretPurpose};
use latent_capabilities::broker::secrets::{CredentialScope, ProviderCredential};

struct Binding {
    owner: Arc<Inner>,
    scope: CredentialScope,
    reference: String,
    _metadata: ProviderMetadata,
}
impl LocalSecretStore {
    /// Operator-only construction. Possession of this opaque object is useful
    /// only to a trusted provider; it cannot be installed as a guest read handle.
    pub fn bind_credential(
        &self,
        scope: CredentialScope,
        reference: String,
    ) -> Result<Arc<dyn ProviderCredential>, SecretError> {
        if !config::text(&scope.tenant.0, 128)
            || scope.tenant.0.capacity() > 128
            || !config::text(&scope.provider_id, 128)
            || scope.provider_id.capacity() > 128
            || !config::text(&reference, 256)
            || reference.capacity() > 256
            || scope.origin.host.capacity() > 256
            || scope.origin.scheme.capacity() > 8
        {
            return Err(SecretError::PermissionDenied);
        }
        let binding = Binding {
            owner: self.inner.clone(),
            scope,
            reference,
            _metadata: self.inner.pools.reserve_protocol_metadata(2048)?,
        };
        binding.with_current_value(&mut |_| Ok(()))?;
        Ok(Arc::new(binding))
    }
}
impl ProviderCredential for Binding {
    fn scope(&self) -> &CredentialScope {
        &self.scope
    }
    fn reference(&self) -> &str {
        &self.reference
    }
    fn with_current_value(
        &self,
        use_value: &mut dyn FnMut(&[u8]) -> Result<(), SecretError>,
    ) -> Result<(), SecretError> {
        let generation = self.owner.generation()?;
        let index = generation
            .entries
            .iter()
            .position(|e| e.spec.tenant == self.scope.tenant && e.spec.reference == self.reference)
            .ok_or(SecretError::NotFound)?;
        self.owner.with_current(&generation, index, |entry| {
            match &entry.spec.purpose {
                SecretPurpose::ProviderCredential {
                    provider_id,
                    origin,
                } if *provider_id == self.scope.provider_id && *origin == self.scope.origin => (),
                _ => return Err(SecretError::PermissionDenied),
            }
            use_value(&entry.bytes)
        })
    }
}
