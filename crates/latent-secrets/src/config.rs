use crate::SecretError;
use latent_core::TenantId;
use latent_policy::capability::{HttpOrigin, ResourceConstraint};

#[derive(Clone, Copy, Debug)]
pub struct SecretLimits {
    pub maximum_references: usize,
    pub maximum_value_bytes: usize,
    pub maximum_generation_bytes: usize,
    pub maximum_generations: usize,
    pub maximum_environment_bytes: usize,
}
impl Default for SecretLimits {
    fn default() -> Self {
        Self {
            maximum_references: latent_policy::capability::MAX_SET_ENTRIES,
            maximum_value_bytes: 16384,
            maximum_generation_bytes: 512 * 1024,
            maximum_generations: 2,
            maximum_environment_bytes: 128 * 1024,
        }
    }
}
impl SecretLimits {
    pub(crate) fn validate(self) -> Result<(), SecretError> {
        if !(1..=latent_policy::capability::MAX_SET_ENTRIES).contains(&self.maximum_references)
            || !(1..=32768).contains(&self.maximum_value_bytes)
            || !(1..=1024 * 1024).contains(&self.maximum_generation_bytes)
            || self.maximum_generation_bytes < self.maximum_value_bytes
            || !(2..=8).contains(&self.maximum_generations)
            || !(1..=1024 * 1024).contains(&self.maximum_environment_bytes)
        {
            return Err(SecretError::Unavailable);
        }
        Ok(())
    }
}

pub enum SecretSource {
    File {
        name: String,
    },
    /// Only explicitly allowlisted keys from the initial process environment.
    Environment {
        key: String,
    },
}
pub enum SecretPurpose {
    TlsProviderCredential {
        provider_id: String,
        destination: latent_capabilities::broker::secrets::TlsCredentialDestination,
    },
    GuestValue,
    ProviderCredential {
        provider_id: String,
        origin: HttpOrigin,
    },
}
pub struct SecretSpec {
    pub tenant: TenantId,
    pub reference: String,
    pub source: SecretSource,
    pub purpose: SecretPurpose,
    pub media_type: String,
    pub version: String,
    pub expires_at_unix_millis: Option<u64>,
}

pub(crate) fn text(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && value.bytes().all(|b| (0x21..=0x7e).contains(&b))
}
pub(crate) fn environment_key(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_')
        && !value.as_bytes()[0].is_ascii_digit()
}
pub(crate) fn leaf(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 255
        && !matches!(value, "." | "..")
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
}
pub(crate) fn validate_specs(
    specs: &[SecretSpec],
    limits: SecretLimits,
    allowlist: &[String],
) -> Result<(), SecretError> {
    if specs.len() > limits.maximum_references {
        return Err(SecretError::Unavailable);
    }
    for (index, spec) in specs.iter().enumerate() {
        if !text(&spec.tenant.0, 128)
            || spec.tenant.0.capacity() > 128
            || !text(&spec.reference, 256)
            || !spec
                .reference
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.:/@".contains(&b))
            || spec.reference.capacity() > 256
            || !text(&spec.media_type, 128)
            || spec.media_type.capacity() > 128
            || !text(&spec.version, 128)
            || spec.version.capacity() > 128
            || specs[..index]
                .iter()
                .any(|s| s.tenant == spec.tenant && s.reference == spec.reference)
        {
            return Err(SecretError::Unavailable);
        }
        match &spec.source {
            SecretSource::File { name } if leaf(name) && name.capacity() <= 255 => (),
            SecretSource::Environment { key }
                if environment_key(key) && key.capacity() <= 128 && allowlist.contains(key) => {}
            _ => return Err(SecretError::PermissionDenied),
        }
        if let SecretPurpose::TlsProviderCredential {
            provider_id,
            destination,
        } = &spec.purpose
        {
            if !text(provider_id, 128) || provider_id.capacity() > 128 {
                return Err(SecretError::PermissionDenied);
            }
            destination.validate()?;
        }
        if let SecretPurpose::ProviderCredential {
            provider_id,
            origin,
        } = &spec.purpose
        {
            if !text(provider_id, 128)
                || provider_id.capacity() > 128
                || origin.scheme.capacity() > 8
                || origin.host.capacity() > 256
            {
                return Err(SecretError::PermissionDenied);
            }
            ResourceConstraint::Http {
                origins: vec![origin.clone()],
                methods: vec!["GET".into()],
                paths: vec!["/".into()],
                path_prefixes: vec![],
            }
            .validate()?;
        }
    }
    Ok(())
}
