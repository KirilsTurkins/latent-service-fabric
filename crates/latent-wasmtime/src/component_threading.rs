//! Final-byte authentication for the explicit canonical-child profile.
//!
//! A factory may allocate its shared Engine before it has a component. Every
//! component using that Engine is authenticated before compilation or native
//! loading. The private immutable proof then follows InstancePre through reuse.
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparedComponent;

pub(crate) const PROFILE: &str = "rust-context40-sole-consumer-one-task-start-v1";
pub(crate) const C_PROFILE: &str = "c-context144-sync-cooperative-v1";
pub(crate) const METADATA: &str = "component-thread-authentication";

#[derive(Debug)]
pub(crate) enum Authentication {
    Disabled,
    Verified([u8; 32]),
    CVerified([u8; 32]),
}

impl Authentication {
    #[cfg(test)]
    pub(crate) fn verify(enabled: bool, bytes: &[u8]) -> Result<Self, PlatformError> {
        Self::verify_profile(
            enabled.then_some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
            bytes,
            0,
        )
    }

    pub(crate) fn verify_profile(
        profile: Option<crate::NativeThreadProfile>,
        bytes: &[u8],
        prepaid: usize,
    ) -> Result<Self, PlatformError> {
        let Some(profile) = profile else {
            return Ok(Self::Disabled);
        };
        if prepaid < profile.verification_bytes() {
            return Err(crate::containment::platform_error(
                PlatformErrorCode::ResourceExhausted,
                "component-thread-verification-work-not-admitted",
                false,
            ));
        }
        if profile == crate::NativeThreadProfile::CContext144SyncCooperativeV1 {
            let receipt =
                latent_component_threading::c_preimage::verify_embedded_c_original_core(bytes)
                    .map_err(|_| invalid())?;
            return Ok(Self::CVerified(receipt.component_digest));
        }
        let receipt =
            latent_component_threading::verify_component_routing(bytes).map_err(|_| invalid())?;
        Ok(Self::Verified(receipt.component_digest))
    }

    pub(crate) fn retained_bytes(&self) -> usize {
        match self {
            Self::Disabled => 0,
            Self::Verified(_) | Self::CVerified(_) => std::mem::size_of::<Self>(),
        }
    }

    #[cfg(test)]
    pub(crate) fn check(
        &self,
        enabled: bool,
        descriptor: &PreparedComponent,
    ) -> Result<(), PlatformError> {
        self.check_profile(
            enabled.then_some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
            descriptor,
        )
    }

    pub(crate) fn check_profile(
        &self,
        selected: Option<crate::NativeThreadProfile>,
        descriptor: &PreparedComponent,
    ) -> Result<(), PlatformError> {
        match (self, selected, descriptor.metadata.get(METADATA)) {
            (Self::Disabled, None, None) => Ok(()),
            (
                Self::Verified(digest),
                Some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
                Some(profile),
            ) if profile == PROFILE => {
                let expected = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
                if descriptor.metadata.get("component-digest") == Some(&expected) {
                    Ok(())
                } else {
                    Err(invalid())
                }
            }
            (
                Self::CVerified(digest),
                Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1),
                Some(profile),
            ) if profile == C_PROFILE => {
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
        let selected = match descriptor.metadata.get(METADATA).map(String::as_str) {
            None => None,
            Some(PROFILE) => {
                Some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1)
            }
            Some(C_PROFILE) => Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1),
            _ => return Err(invalid()),
        };
        self.check_profile(selected, descriptor)
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
    fn c_profile_requires_prepaid_work_before_reading_proof_and_never_grants_from_data() {
        let profile = Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1);
        let work = latent_component_threading::c_preimage::C_VERIFICATION_WORK_BYTES;
        assert_eq!(work, 48 * 1024 * 1024);
        for prepaid in [0, work - 1] {
            assert_eq!(
                Authentication::verify_profile(profile, b"invalid", prepaid)
                    .unwrap_err()
                    .code,
                PlatformErrorCode::ResourceExhausted
            );
        }
        assert_eq!(
            Authentication::verify_profile(profile, b"invalid", work)
                .unwrap_err()
                .code,
            PlatformErrorCode::CorruptArtifact
        );
        assert!(matches!(
            Authentication::verify_profile(None, b"invalid", 0),
            Ok(Authentication::Disabled)
        ));
    }

    #[test]
    fn c_profile_proof_cannot_replay_as_rust_or_under_default_cache_settings() {
        let proof = Authentication::CVerified([0x11; 32]);
        let mut original = descriptor();
        original.metadata.insert(METADATA.into(), C_PROFILE.into());
        proof
            .check_profile(
                Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1),
                &original,
            )
            .unwrap();
        proof.check_before_instantiation(&original).unwrap();
        assert!(proof.check_profile(None, &original).is_err());
        assert!(
            proof
                .check_profile(
                    Some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
                    &original
                )
                .is_err()
        );
        original.metadata.insert(METADATA.into(), PROFILE.into());
        assert!(proof.check_before_instantiation(&original).is_err());
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
