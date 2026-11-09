//! Final-byte authentication for the explicit canonical-child profile.
//!
//! A factory may allocate its shared Engine before it has a component. Every
//! component using that Engine is authenticated before compilation or native
//! loading. The private immutable proof then follows InstancePre through reuse.
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparedComponent;

pub(crate) const PROFILE: &str = "rust-context40-sole-consumer-one-task-start-v1";
pub(crate) const C_PROFILE: &str = "c-context144-sync-cooperative-v1";
pub(crate) const RUST_SYNC_PROFILE: &str = "rust-context40-sync-cooperative-v1";
#[cfg(feature = "development-rust-http-combined")]
pub(crate) const RUST_COMBINED_HTTP_PROFILE: &str = "rust-context40-combined-http-diagnostic-v1";
// A distinct, conservative experimental reservation from the existing original
// preparation owner. Physical high-water and adversarial bounds are not yet
// qualified; this number must not be promoted as a production cost proof.
#[cfg(feature = "development-rust-http-combined")]
pub(crate) const RUST_COMBINED_HTTP_WORK_BYTES: usize = 96 * 1024 * 1024;
pub(crate) const METADATA: &str = "component-thread-authentication";

#[derive(Debug)]
pub(crate) enum Authentication {
    Disabled,
    Verified([u8; 32]),
    CVerified([u8; 32]),
    RustSyncVerified([u8; 32]),
    #[cfg(feature = "development-rust-http-combined")]
    RustCombinedHttpVerified([u8; 32]),
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
        if profile == crate::NativeThreadProfile::RustContext40SyncCooperativeV1 {
            let receipt =
                latent_component_threading::rust_component::verify_embedded_rust_original_core(
                    bytes,
                )
                .map_err(|_| invalid())?;
            return Ok(Self::RustSyncVerified(receipt.component_digest));
        }
        #[cfg(feature = "development-rust-http-combined")]
        if profile == crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1 {
            let receipt =
                latent_component_threading::rust_component::verify_embedded_combined_diagnostic(
                    bytes,
                )
                .map_err(|_| invalid())?;
            return Ok(Self::RustCombinedHttpVerified(receipt.wrapped_digest));
        }
        let receipt =
            latent_component_threading::verify_component_routing(bytes).map_err(|_| invalid())?;
        Ok(Self::Verified(receipt.component_digest))
    }

    pub(crate) fn retained_bytes(&self) -> usize {
        match self {
            Self::Disabled => 0,
            Self::Verified(_) | Self::CVerified(_) | Self::RustSyncVerified(_) => {
                std::mem::size_of::<Self>()
            }
            #[cfg(feature = "development-rust-http-combined")]
            Self::RustCombinedHttpVerified(_) => std::mem::size_of::<Self>(),
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
            (
                Self::RustSyncVerified(digest),
                Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1),
                Some(profile),
            ) if profile == RUST_SYNC_PROFILE => {
                let expected = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
                if descriptor.metadata.get("component-digest") == Some(&expected) {
                    Ok(())
                } else {
                    Err(invalid())
                }
            }
            #[cfg(feature = "development-rust-http-combined")]
            (
                Self::RustCombinedHttpVerified(digest),
                Some(crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1),
                Some(profile),
            ) if profile == RUST_COMBINED_HTTP_PROFILE => {
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
            Some(RUST_SYNC_PROFILE) => {
                Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1)
            }
            #[cfg(feature = "development-rust-http-combined")]
            Some(RUST_COMBINED_HTTP_PROFILE) => {
                Some(crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1)
            }
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

    #[cfg(feature = "http-upload-window")]
    #[test]
    fn upload_window_host_authentication_rejects_handcrafted_shared_original_memory() {
        use sha2::Digest;
        use std::borrow::Cow;
        use wasm_encoder::{
            Alias, Component, ComponentAliasSection, ComponentImportSection,
            ComponentOuterAliasKind, ComponentTypeRef, ComponentTypeSection, CustomSection,
            InstanceType, PrimitiveValType, TypeBounds,
        };
        use wasmparser::{Parser, Payload, Validator, WasmFeatures};

        let original = latent_component_threading::c_http_upload_window_test_original_core();
        let digest: [u8; 32] = sha2::Sha256::digest(&original).into();
        assert!(
            latent_component_threading::c_abi::transform_c_canonical_abi(&original, digest, "run")
                .is_ok()
        );
        let memory = Parser::new(0)
            .parse_all(&original)
            .find_map(|payload| match payload.unwrap() {
                Payload::MemorySection(reader) => Some(reader.range().start),
                _ => None,
            })
            .expect("one original memory");
        assert_eq!(&original[memory..memory + 4], &[1, 1, 4, 4]);
        let mut shared = original.clone();
        shared[memory + 1] = 3; // same finite memory with the shared flag set
        Validator::new_with_features(WasmFeatures::default() | WasmFeatures::THREADS)
            .validate_all(&shared)
            .unwrap();

        // This deliberately incomplete component contains the actual helper
        // import and nominal resource alias, but no valid final C graph. It
        // isolates authentication; it is not an accepted or signed guest.
        let component = |core: &[u8]| {
            let mut value = Component::new();
            let mut owner = InstanceType::new();
            owner.export("upload", ComponentTypeRef::Type(TypeBounds::SubResource));
            let index = owner.type_count();
            owner
                .ty()
                .function()
                .params([] as [(&str, PrimitiveValType); 0])
                .result(None);
            owner.export("open", ComponentTypeRef::Func(index));
            let mut types = ComponentTypeSection::new();
            types.instance(&owner);
            let mut imports = ComponentImportSection::new();
            imports.import("latent:http/streaming@0.3.0", ComponentTypeRef::Instance(0));
            value.section(&types).section(&imports);
            let mut aliases = ComponentAliasSection::new();
            aliases.alias(Alias::InstanceExport {
                instance: 0,
                kind: wasm_encoder::ComponentExportKind::Type,
                name: "upload",
            });
            value.section(&aliases);
            let mut helper = InstanceType::new();
            let index = helper.type_count();
            helper.alias(Alias::Outer {
                kind: ComponentOuterAliasKind::Type,
                count: 1,
                index: 1,
            });
            helper.export("upload", ComponentTypeRef::Type(TypeBounds::Eq(index)));
            for name in ["prepare", "write"] {
                let index = helper.type_count();
                helper
                    .ty()
                    .function()
                    .params([] as [(&str, PrimitiveValType); 0])
                    .result(None);
                helper.export(name, ComponentTypeRef::Func(index));
            }
            let mut types = ComponentTypeSection::new();
            types.instance(&helper);
            let mut imports = ComponentImportSection::new();
            imports.import(
                "latent:http/upload-window@0.5.0",
                ComponentTypeRef::Instance(2),
            );
            value.section(&types).section(&imports);
            let mut proof = b"LSFCPR01".to_vec();
            proof.extend_from_slice(&1_u32.to_le_bytes());
            proof.extend_from_slice(&3_u32.to_le_bytes());
            proof.extend_from_slice(&u32::try_from(core.len()).unwrap().to_le_bytes());
            proof.extend_from_slice(b"run");
            proof.extend_from_slice(core);
            value.section(&CustomSection {
                name: Cow::Borrowed(latent_component_threading::c_preimage::C_PREIMAGE_SECTION),
                data: Cow::Owned(proof),
            });
            value.finish()
        };
        let normal_component = component(&original);
        let shared_component = component(&shared);
        assert_eq!(
            latent_component_threading::c_preimage::verify_embedded_c_original_core(
                &normal_component
            )
            .unwrap_err(),
            "c-component-one-main-creator"
        );
        assert_eq!(
            latent_component_threading::c_preimage::verify_embedded_c_original_core(
                &shared_component
            )
            .unwrap_err(),
            "c-context-linked-core-shape"
        );
        for value in [&normal_component, &shared_component] {
            let error = Authentication::verify_profile(
                Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1),
                value,
                latent_component_threading::c_preimage::C_VERIFICATION_WORK_BYTES,
            )
            .unwrap_err();
            assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
        }
    }

    #[test]
    fn rust_sync_private_dispatch_executes_production_helper_and_preserves_source_fallback() {
        let raw = latent_component_threading::rust_objects::emitted_dispatch_controls().unwrap();
        let mut config = wasmtime::Config::new();
        config.consume_fuel(true);
        let engine = wasmtime::Engine::new(&config).unwrap();
        let module = wasmtime::Module::new(&engine, raw).unwrap();
        let mut store = wasmtime::Store::new(&engine, ());
        store.set_fuel(10_000).unwrap();
        let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
        for (name, pointer, expected) in [
            ("strict", 0, Some(107)),
            ("strict", 1, None),
            ("release", 0, Some(107)),
            ("release", 1, Some(17)),
            ("ordinary", 0, None),
            ("ordinary", 1, Some(17)),
        ] {
            let function = instance
                .get_typed_func::<(i32, i32), i32>(&mut store, name)
                .unwrap();
            let result = function.call(&mut store, (7, pointer));
            match expected {
                Some(value) => assert_eq!(result.unwrap(), value),
                None => assert_eq!(
                    result.unwrap_err().downcast_ref::<wasmtime::Trap>(),
                    Some(&wasmtime::Trap::UnreachableCodeReached)
                ),
            }
        }
    }

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

    #[cfg(feature = "development-rust-http-combined")]
    #[test]
    fn combined_http_diagnostic_requires_its_distinct_prepaid_profile() {
        let selected = Some(crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1);
        let work = RUST_COMBINED_HTTP_WORK_BYTES;
        assert_eq!(work, 96 * 1024 * 1024);
        for prepaid in [0, work - 1] {
            assert_eq!(
                Authentication::verify_profile(selected, b"invalid", prepaid)
                    .unwrap_err()
                    .code,
                PlatformErrorCode::ResourceExhausted
            );
        }
        assert_eq!(
            Authentication::verify_profile(selected, b"invalid", work)
                .unwrap_err()
                .code,
            PlatformErrorCode::CorruptArtifact
        );
        let mut ordinary = descriptor();
        ordinary
            .metadata
            .insert(METADATA.into(), RUST_SYNC_PROFILE.into());
        assert!(Authentication::RustCombinedHttpVerified([0x11; 32])
            .check_before_instantiation(&ordinary)
            .is_err());
    }

    #[cfg(feature = "development-rust-http-combined")]
    #[test]
    fn combined_http_diagnostic_requires_explicit_original_cache_capacity() {
        use crate::cache::{PrepareAccess, PreparedCache};
        use std::sync::Arc;
        let mut config = crate::WasmtimeConfig::default();
        let sample_component_bytes = 1_629_518usize;
        let work = RUST_COMBINED_HTTP_WORK_BYTES;
        let default = Arc::new(PreparedCache::<u8>::new(config.cache_limits()).unwrap());
        assert!(default
            .begin_with_verification("too-small".into(), sample_component_bytes, 1, work)
            .is_err());
        assert_eq!(default.snapshot().preparing_source_bytes, 0);
        // Test explicit capacity only; the diagnostic profile does not enlarge
        // the configured node cache or create a second owner.
        config.prepared_cache_maximum_source_bytes = work + sample_component_bytes;
        let funded = Arc::new(PreparedCache::<u8>::new(config.cache_limits()).unwrap());
        let PrepareAccess::Compile(reservation) = funded
            .begin_with_verification("funded".into(), sample_component_bytes, 1, work)
            .unwrap()
        else {
            panic!("fresh preparation required")
        };
        assert_eq!(reservation.verification_bytes(), work);
        assert_eq!(
            funded.snapshot().preparing_source_bytes,
            work + sample_component_bytes
        );
        drop(reservation);
        assert_eq!(funded.snapshot().preparing_source_bytes, 0);
    }

    #[cfg(all(
        feature = "development-rust-http-combined",
        target_os = "linux",
        target_arch = "x86_64"
    ))]
    #[test]
    fn combined_http_diagnostic_authenticates_wrapped_final_graph_before_reuse() {
        use sha2::{Digest, Sha256};
        use std::borrow::Cow;
        use wasm_encoder::{CustomSection, Encode, Section};
        const BASE: &[u8] = include_bytes!(
            "../../latent-component-threading/src/rust_catalogue/combined-corrected-v1/combined-final-component.wasm"
        );
        const DELTA: &[u8] = include_bytes!(
            "../../latent-component-threading/src/rust_catalogue/combined-corrected-v1/combined-original-delta.bin"
        );
        let mut wrapped = BASE.to_vec();
        let section = CustomSection {
            name: Cow::Borrowed("latent-rust-original-delta-v1"),
            data: Cow::Borrowed(DELTA),
        };
        wrapped.push(section.id());
        section.encode(&mut wrapped);
        let selected = Some(crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1);
        let result =
            Authentication::verify_profile(selected, &wrapped, RUST_COMBINED_HTTP_WORK_BYTES);
        if !latent_component_threading::rust_component::COMBINED_DIAGNOSTIC_CATALOGUE_AVAILABLE {
            assert_eq!(result.unwrap_err().code, PlatformErrorCode::CorruptArtifact);
            println!("COMBINED_HTTP_CATALOGUE=legacy-refused");
            return;
        }
        println!("COMBINED_HTTP_CATALOGUE=current");
        let proof = result.unwrap();
        assert_eq!(
            Authentication::verify_profile(
                Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1),
                &wrapped,
                latent_component_threading::rust_component::RUST_VERIFICATION_WORK_BYTES,
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::CorruptArtifact
        );
        let mut original = descriptor();
        original
            .metadata
            .insert(METADATA.into(), RUST_COMBINED_HTTP_PROFILE.into());
        let digest: [u8; 32] = Sha256::digest(&wrapped).into();
        original.metadata.insert(
            "component-digest".into(),
            format!("sha256:{:x}", latent_core::digest::HexDigest(&digest)),
        );
        proof.check_profile(selected, &original).unwrap();
        proof.check_before_instantiation(&original).unwrap();
        // Use the actual selected Wasmtime settings after authentication. This
        // proves compilation only, not instantiation or a signed guest result.
        let config = crate::WasmtimeConfig {
            owned_native_threads: true,
            owned_native_stacks: true,
            native_thread_profile:
                crate::NativeThreadProfile::RustContext40CombinedHttpDiagnosticV1,
            activation_runtime: Some(latent_core::activation_runtime::RuntimeLimits {
                tasks: 8,
                executors: 2,
                queued_work: 8,
                waits: 16,
                timers: 8,
                results: 8,
                native_owners: 8,
            }),
            ..crate::WasmtimeConfig::default()
        };
        let engine = config.runtime_engine().unwrap();
        wasmtime::component::Component::new(&engine, &wrapped).unwrap();
        assert!(proof
            .check_profile(
                Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1),
                &original
            )
            .is_err());
        original
            .metadata
            .insert("component-digest".into(), "sha256:forged".into());
        assert!(proof.check_before_instantiation(&original).is_err());
        wrapped[8] ^= 1;
        assert_eq!(
            Authentication::verify_profile(selected, &wrapped, RUST_COMBINED_HTTP_WORK_BYTES)
                .unwrap_err()
                .code,
            PlatformErrorCode::CorruptArtifact
        );
    }

    #[test]
    fn c_profile_requires_prepaid_work_before_reading_proof_and_never_grants_from_data() {
        for selected in [
            crate::NativeThreadProfile::CContext144SyncCooperativeV1,
            crate::NativeThreadProfile::RustContext40SyncCooperativeV1,
        ] {
            let profile = Some(selected);
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
        }
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
        assert!(proof
            .check_profile(
                Some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
                &original
            )
            .is_err());
        original.metadata.insert(METADATA.into(), PROFILE.into());
        assert!(proof.check_before_instantiation(&original).is_err());
        let rust = Authentication::RustSyncVerified([0x11; 32]);
        original
            .metadata
            .insert(METADATA.into(), RUST_SYNC_PROFILE.into());
        rust.check_profile(
            Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1),
            &original,
        )
        .unwrap();
        rust.check_before_instantiation(&original).unwrap();
        for wrong in [
            None,
            Some(crate::NativeThreadProfile::CContext144SyncCooperativeV1),
            Some(crate::NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
        ] {
            assert!(rust.check_profile(wrong, &original).is_err());
        }
        assert!(proof
            .check_profile(
                Some(crate::NativeThreadProfile::RustContext40SyncCooperativeV1),
                &original
            )
            .is_err());
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
