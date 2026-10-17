//! Final-byte authentication for the explicit canonical-child profile.
//!
//! A factory may allocate its shared Engine before it has a component. Every
//! component using that Engine is authenticated before compilation or native
//! loading. The private immutable proof then follows InstancePre through reuse.
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparedComponent;

pub(crate) const PROFILE: &str = "rust-context40-sole-consumer-one-task-start-v1";
pub(crate) const METADATA: &str = "component-thread-authentication";

#[derive(Debug)]
pub(crate) enum Authentication {
    Disabled,
    Verified([u8; 32]),
}

impl Authentication {
    pub(crate) fn verify(enabled: bool, bytes: &[u8]) -> Result<Self, PlatformError> {
        if !enabled {
            return Ok(Self::Disabled);
        }
        let receipt =
            latent_component_threading::verify_component_routing(bytes).map_err(|_| invalid())?;
        Ok(Self::Verified(receipt.component_digest))
    }

    pub(crate) fn retained_bytes(&self) -> usize {
        match self {
            Self::Disabled => 0,
            Self::Verified(_) => std::mem::size_of::<Self>(),
        }
    }

    pub(crate) fn check(
        &self,
        enabled: bool,
        descriptor: &PreparedComponent,
    ) -> Result<(), PlatformError> {
        match (self, enabled, descriptor.metadata.get(METADATA)) {
            (Self::Disabled, false, None) => Ok(()),
            (Self::Verified(digest), true, Some(profile)) if profile == PROFILE => {
                let expected = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
                if descriptor.metadata.get("component-digest") == Some(&expected) {
                    Ok(())
                } else {
                    Err(invalid())
                }
            }
            _ => Err(invalid()),
        }
    }

    pub(crate) fn check_before_instantiation(
        &self,
        descriptor: &PreparedComponent,
    ) -> Result<(), PlatformError> {
        // Descriptor and proof are both private immutable fields of the same
        // PreparedRuntime; the factory additionally checks its selected profile
        // on every cache/readiness/start boundary.
        self.check(descriptor.metadata.contains_key(METADATA), descriptor)
    }
}

fn invalid() -> PlatformError {
    crate::containment::platform_error(
        PlatformErrorCode::CorruptArtifact,
        "component-thread-authentication-failed",
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{Metadata, ReleaseDigest};
    use latent_executor::PreparationKey;

    fn descriptor() -> PreparedComponent {
        PreparedComponent {
            key: PreparationKey {
                release: ReleaseDigest(format!("sha256:{}", "1".repeat(64))),
                publication: None,
                engine_version: "test".into(),
                engine_configuration_digest: "test".into(),
                target_triple: "test".into(),
                cpu_feature_set: "test".into(),
            },
            backend: "test".into(),
            opaque_handle: "test".into(),
            metadata: Metadata::from([
                (METADATA.into(), PROFILE.into()),
                (
                    "component-digest".into(),
                    format!("sha256:{}", "1".repeat(64)),
                ),
            ]),
        }
    }

    #[test]
    fn enabled_profile_never_falls_back_when_final_byte_verification_fails() {
        for bytes in [b"invalid".as_slice(), b"\0asm\x0d\0\x01\0".as_slice()] {
            assert_eq!(
                Authentication::verify(true, bytes).unwrap_err().code,
                PlatformErrorCode::CorruptArtifact
            );
            assert!(matches!(
                Authentication::verify(false, bytes),
                Ok(Authentication::Disabled)
            ));
        }
    }

    #[test]
    fn immutable_proof_rejects_cache_digest_profile_and_default_replay() {
        // Exercise proof consumption; a production Verified value can only
        // originate from the shared final-byte verifier above.
        let proof = Authentication::Verified([0x11; 32]);
        let original = descriptor();
        proof.check(true, &original).unwrap();
        proof.check_before_instantiation(&original).unwrap();
        assert!(proof.check(false, &original).is_err());
        assert!(Authentication::Disabled.check(true, &original).is_err());
        for key in [METADATA, "component-digest"] {
            let mut altered = original.clone();
            altered.metadata.remove(key);
            assert!(proof.check_before_instantiation(&altered).is_err());
            altered.metadata.insert(key.into(), "forged".into());
            assert!(proof.check_before_instantiation(&altered).is_err());
        }
        let mut default = original;
        default.metadata.remove(METADATA);
        Authentication::Disabled.check(false, &default).unwrap();
        assert!(Authentication::Disabled.check(true, &default).is_err());
    }
}
