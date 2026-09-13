use super::{blob, frame, invalid, ValidatedAotProfile};
use latent_artifacts::LifecycleScope;
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, TenantId};
use serde::{Serialize, Serializer};
use sha2::{Digest, Sha256};

/// Bounded immutable provenance derived from an exact catalog-owned input.
/// A missing package is explicit trusted-local provenance, never a made-up OCI ID.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AotCompatibilityKey {
    scope: LifecycleScope,
    #[serde(serialize_with = "package", skip_serializing_if = "Option::is_none")]
    package: Option<PackageDigest>,
    #[serde(serialize_with = "artifact")]
    component: ArtifactBlobDigest,
    component_bytes: u64,
    metadata_digest: [u8; 32],
    #[serde(serialize_with = "artifact")]
    engine_profile_digest: ArtifactBlobDigest,
    engine_compatibility: [u8; 32],
    #[serde(serialize_with = "artifact")]
    capability_contract_digest: ArtifactBlobDigest,
    #[serde(serialize_with = "artifact")]
    security_policy_digest: ArtifactBlobDigest,
    compiler_digest: [u8; 32],
    sandbox_digest: [u8; 32],
}
impl AotCompatibilityKey {
    pub(crate) fn from_source(
        source: &super::supervisor::CheckedAotSource,
        profile: &ValidatedAotProfile,
        compiler_digest: [u8; 32],
        sandbox_digest: [u8; 32],
    ) -> Result<Self, PlatformError> {
        Self::checked_parts(
            source.scope(),
            source.package(),
            *source.component_digest(),
            source.component_bytes(),
            *source.metadata_digest(),
            profile,
            compiler_digest,
            sandbox_digest,
        )
    }
    #[allow(clippy::too_many_arguments)]
    fn checked_parts(
        scope: &LifecycleScope,
        package: Option<&PackageDigest>,
        component: [u8; 32],
        component_bytes: u64,
        metadata_digest: [u8; 32],
        profile: &ValidatedAotProfile,
        compiler_digest: [u8; 32],
        sandbox_digest: [u8; 32],
    ) -> Result<Self, PlatformError> {
        scope.validate()?;
        if component_bytes == 0 || (package.is_some() && scope.tenant().is_none()) {
            return Err(invalid());
        }
        let scope = match scope {
            LifecycleScope::Tenant(tenant) => {
                LifecycleScope::Tenant(TenantId(tenant.0.as_str().into()))
            }
            LifecycleScope::LocalUnscoped => LifecycleScope::LocalUnscoped,
        };
        // Strict digest newtypes may own a caller's excessive String capacity.
        // Copy only the validated 71-byte representation into retained storage.
        let package =
            package.map(|value| value.as_str().parse().expect("validated package digest"));
        Ok(Self {
            scope,
            package,
            component: blob(component),
            component_bytes,
            metadata_digest,
            engine_profile_digest: blob(*profile.digest()),
            engine_compatibility: *profile.engine_compatibility(),
            capability_contract_digest: blob(*profile.capability_contract_digest()),
            security_policy_digest: blob(*profile.security_policy_digest()),
            compiler_digest,
            sandbox_digest,
        })
    }
    #[must_use]
    pub fn scope(&self) -> &LifecycleScope {
        &self.scope
    }
    #[must_use]
    pub fn package(&self) -> Option<&PackageDigest> {
        self.package.as_ref()
    }
    #[must_use]
    pub fn component(&self) -> &ArtifactBlobDigest {
        &self.component
    }
    #[must_use]
    pub const fn component_bytes(&self) -> u64 {
        self.component_bytes
    }
    #[must_use]
    pub const fn metadata_digest(&self) -> &[u8; 32] {
        &self.metadata_digest
    }
    #[must_use]
    pub fn engine_profile_digest(&self) -> &ArtifactBlobDigest {
        &self.engine_profile_digest
    }
    #[must_use]
    pub const fn engine_compatibility(&self) -> &[u8; 32] {
        &self.engine_compatibility
    }
    #[must_use]
    pub fn capability_contract_digest(&self) -> &ArtifactBlobDigest {
        &self.capability_contract_digest
    }
    #[must_use]
    pub fn security_policy_digest(&self) -> &ArtifactBlobDigest {
        &self.security_policy_digest
    }
    #[must_use]
    pub const fn compiler_digest(&self) -> &[u8; 32] {
        &self.compiler_digest
    }
    #[must_use]
    pub const fn sandbox_digest(&self) -> &[u8; 32] {
        &self.sandbox_digest
    }
    #[must_use]
    pub fn digest(&self) -> ArtifactBlobDigest {
        let mut digest = Sha256::new();
        digest.update(b"lsf-aot-compatibility-v2\0");
        match &self.scope {
            LifecycleScope::LocalUnscoped => frame(&mut digest, b"local-unscoped"),
            LifecycleScope::Tenant(tenant) => {
                frame(&mut digest, b"tenant");
                frame(&mut digest, tenant.0.as_bytes());
            }
        }
        frame(
            &mut digest,
            self.package
                .as_ref()
                .map_or(b"".as_slice(), |value| value.as_str().as_bytes()),
        );
        frame(&mut digest, self.component.as_str().as_bytes());
        frame(&mut digest, &self.component_bytes.to_le_bytes());
        for value in [
            &self.metadata_digest,
            &self.engine_compatibility,
            &self.compiler_digest,
            &self.sandbox_digest,
        ] {
            frame(&mut digest, value);
        }
        for value in [
            &self.engine_profile_digest,
            &self.capability_contract_digest,
            &self.security_policy_digest,
        ] {
            frame(&mut digest, value.as_str().as_bytes());
        }
        blob(digest.finalize().into())
    }
}
#[allow(
    clippy::ref_option,
    reason = "Serde serialize_with requires a reference to the declared Option field"
)]
fn package<S: Serializer>(value: &Option<PackageDigest>, serializer: S) -> Result<S::Ok, S::Error> {
    value
        .as_ref()
        .map(PackageDigest::as_str)
        .serialize(serializer)
}
fn artifact<S: Serializer>(value: &ArtifactBlobDigest, serializer: S) -> Result<S::Ok, S::Error> {
    value.as_str().serialize(serializer)
}

#[cfg(test)]
pub(super) fn fixture(profile: &ValidatedAotProfile) -> AotCompatibilityKey {
    AotCompatibilityKey::checked_parts(
        &LifecycleScope::LocalUnscoped,
        None,
        [2; 32],
        8,
        [3; 32],
        profile,
        [4; 32],
        [5; 32],
    )
    .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_optional_package_and_metadata_scope_are_bound_without_retained_spare_capacity() {
        let profile = ValidatedAotProfile::from_config(
            &crate::WasmtimeConfig::default(),
            super::super::AotCompilerLimits::default(),
        )
        .unwrap();
        let local = fixture(&profile);
        assert!(local.package().is_none());
        let mut text = String::with_capacity(1024 * 1024);
        text.push_str(&blob([7; 32]).into_string());
        let package = PackageDigest::try_from(text).unwrap();
        let tenant = LifecycleScope::Tenant(TenantId("tenant".into()));
        let packaged = AotCompatibilityKey::checked_parts(
            &tenant,
            Some(&package),
            [2; 32],
            8,
            [3; 32],
            &profile,
            [4; 32],
            [5; 32],
        )
        .unwrap();
        assert_ne!(packaged.digest(), local.digest());
        let mut changed = packaged.clone();
        changed.metadata_digest[0] ^= 1;
        assert_ne!(changed.digest(), packaged.digest());
        assert_eq!(packaged.package.unwrap().into_string().capacity(), 71);
        assert!(AotCompatibilityKey::checked_parts(
            &LifecycleScope::LocalUnscoped,
            Some(&package),
            [2; 32],
            8,
            [3; 32],
            &profile,
            [4; 32],
            [5; 32]
        )
        .is_err());
    }
}
