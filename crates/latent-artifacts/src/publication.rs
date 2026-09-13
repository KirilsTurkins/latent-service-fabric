//! Explicit publication selection and the RFC-0002 identity construction.

use crate::LifecycleScope;
use latent_core::{
    ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode, PublicationId,
    ReleaseDigest,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// An exact immutable association in one authenticated catalog scope.
/// Knowing this reference does not grant permission to use or inspect it.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationRef {
    #[serde(with = "id_codec")]
    pub id: PublicationId,
    pub scope: LifecycleScope,
}

impl PublicationRef {
    pub fn package(scope: LifecycleScope, package: &PackageDigest) -> Result<Self, PlatformError> {
        if scope.tenant().is_none() {
            return Err(invalid());
        }
        Self::derive(scope, b"package", package.as_str().as_bytes())
    }

    /// The digest is of the exact canonical immutable version-1 COMPLETE bytes.
    /// This constructor does not manufacture package or publisher identity.
    pub(crate) fn trusted_local(
        scope: LifecycleScope,
        completion: &[u8; 32],
    ) -> Result<Self, PlatformError> {
        let identity = format!("sha256:{}", hex(completion));
        Self::derive(scope, b"trusted-local", identity.as_bytes())
    }

    fn derive(scope: LifecycleScope, kind: &[u8], content: &[u8]) -> Result<Self, PlatformError> {
        scope.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"lsf-publication-v1\0");
        let (scope_kind, scope_value): (&[u8], &[u8]) = match &scope {
            LifecycleScope::Tenant(tenant) => (b"tenant", tenant.0.as_bytes()),
            LifecycleScope::LocalUnscoped => (b"local-unscoped", b""),
        };
        for bytes in [scope_kind, scope_value, kind, content] {
            hash.update((bytes.len() as u64).to_le_bytes());
            hash.update(bytes);
        }
        let id = format!("publication:sha256:{}", hex(&hash.finalize()))
            .parse()
            .map_err(|_| invalid())?;
        Ok(Self { id, scope })
    }
}

/// A caller must supply either exact publication identity or a legacy component.
/// Scope authorization is independent and precedes resolution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PublicationSelector {
    Publication(PublicationRef),
    LegacyComponent(ReleaseDigest),
}

pub(crate) fn ambiguous() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::StateConflict,
        message: "publication-selector-ambiguous".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn invalid() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: "invalid-publication-reference".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut text, "{byte:02x}").expect("writing a String cannot fail");
    }
    text
}

pub(crate) mod id_codec {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &PublicationId,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(value.as_str())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<PublicationId, D::Error> {
        String::deserialize(deserializer)?
            .parse()
            .map_err(serde::de::Error::custom)
    }
}

pub(crate) mod optional_id_codec {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &Option<PublicationId>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value
            .as_ref()
            .map(PublicationId::as_str)
            .serialize(serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<PublicationId>, D::Error> {
        Option::<String>::deserialize(deserializer)?
            .map(|s| s.parse().map_err(serde::de::Error::custom))
            .transpose()
    }
}

pub(crate) fn validate_component(value: &ReleaseDigest) -> Result<(), PlatformError> {
    value
        .0
        .parse::<ArtifactBlobDigest>()
        .map_err(|_| invalid())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::TenantId;

    #[test]
    fn package_scope_and_local_content_are_separate_identity_domains() {
        let p: PackageDigest = format!("sha256:{}", "00".repeat(32)).parse().unwrap();
        let tenant = |s: &str| LifecycleScope::Tenant(TenantId(s.into()));
        let a = PublicationRef::package(tenant("a"), &p).unwrap();
        assert_eq!(a, PublicationRef::package(tenant("a"), &p).unwrap());
        assert_ne!(a, PublicationRef::package(tenant("A"), &p).unwrap());
        assert_ne!(
            a,
            PublicationRef::trusted_local(tenant("a"), &[0; 32]).unwrap()
        );
        assert_ne!(a, PublicationRef::package(tenant("b"), &p).unwrap());
        assert!(PublicationRef::package(LifecycleScope::LocalUnscoped, &p).is_err());
        let bytes = serde_json::to_vec(&a).unwrap();
        assert_eq!(serde_json::from_slice::<PublicationRef>(&bytes).unwrap(), a);
    }
}
