//! Exact Phase 2 AOT compatibility identity and sealed trusted-local output binding.
//!
//! This module does not launch or supervise an isolated compiler process. It
//! provides the bounded identity and host-owned output seal that such a launcher
//! must use before persistent/native reuse can be considered.

use std::fmt;

use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

use crate::WasmtimeEngineProfile;

const MAX_OUTPUT_BYTES_HARD: usize = 512 * 1024 * 1024;
const MAX_PROFILE_ENTRIES_HARD: usize = 512;
const MAX_PROFILE_BYTES_HARD: usize = 512 * 1024;
const MAX_IDENTITY_BYTES_HARD: usize = 4096;
const KEY_DOMAIN: &[u8] = b"lsf-aot-compatibility-v1\0";
const SEAL_DOMAIN: &[u8] = b"lsf-aot-output-seal-v1\0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotCompilerLimits {
    pub maximum_output_bytes: usize,
    pub maximum_profile_entries: usize,
    pub maximum_profile_bytes: usize,
    pub maximum_identity_bytes: usize,
}

impl Default for AotCompilerLimits {
    fn default() -> Self {
        Self {
            maximum_output_bytes: 128 * 1024 * 1024,
            maximum_profile_entries: 256,
            maximum_profile_bytes: 256 * 1024,
            maximum_identity_bytes: 1024,
        }
    }
}

impl AotCompilerLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if self.maximum_output_bytes == 0
            || self.maximum_output_bytes > MAX_OUTPUT_BYTES_HARD
            || self.maximum_profile_entries == 0
            || self.maximum_profile_entries > MAX_PROFILE_ENTRIES_HARD
            || self.maximum_profile_bytes == 0
            || self.maximum_profile_bytes > MAX_PROFILE_BYTES_HARD
            || self.maximum_identity_bytes == 0
            || self.maximum_identity_bytes > MAX_IDENTITY_BYTES_HARD
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-aot-compiler-limits",
            ));
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AotCompatibilityKey {
    package: PackageDigest,
    component: ArtifactBlobDigest,
    backend_id: Box<str>,
    wasmtime_version: Box<str>,
    target_triple: Box<str>,
    cpu_feature_set: Box<str>,
    engine_profile_digest: ArtifactBlobDigest,
    capability_contract_digest: ArtifactBlobDigest,
    security_policy_digest: ArtifactBlobDigest,
}

impl AotCompatibilityKey {
    pub fn from_profile(
        package: PackageDigest,
        component: ArtifactBlobDigest,
        profile: &WasmtimeEngineProfile,
        capability_contract_digest: ArtifactBlobDigest,
        security_policy_digest: ArtifactBlobDigest,
        limits: AotCompilerLimits,
    ) -> Result<Self, PlatformError> {
        let limits = limits.validate()?;
        validate_identity(&profile.id, limits)?;
        validate_identity(&profile.wasmtime_version, limits)?;
        validate_identity(&profile.target_triple, limits)?;
        validate_identity(&profile.cpu_feature_set, limits)?;
        let engine_profile_digest = profile_digest(profile, limits)?;
        Ok(Self {
            package,
            component,
            backend_id: profile.id.clone().into_boxed_str(),
            wasmtime_version: profile.wasmtime_version.clone().into_boxed_str(),
            target_triple: profile.target_triple.clone().into_boxed_str(),
            cpu_feature_set: profile.cpu_feature_set.clone().into_boxed_str(),
            engine_profile_digest,
            capability_contract_digest,
            security_policy_digest,
        })
    }

    #[must_use]
    pub fn package(&self) -> &PackageDigest {
        &self.package
    }

    #[must_use]
    pub fn component(&self) -> &ArtifactBlobDigest {
        &self.component
    }

    #[must_use]
    pub fn engine_profile_digest(&self) -> &ArtifactBlobDigest {
        &self.engine_profile_digest
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
    pub fn digest(&self) -> ArtifactBlobDigest {
        let mut digest = Sha256::new();
        digest.update(KEY_DOMAIN);
        for value in [
            self.package.as_str(),
            self.component.as_str(),
            &self.backend_id,
            &self.wasmtime_version,
            &self.target_triple,
            &self.cpu_feature_set,
            self.engine_profile_digest.as_str(),
            self.capability_contract_digest.as_str(),
            self.security_policy_digest.as_str(),
        ] {
            frame_sha256(&mut digest, value.as_bytes());
        }
        let bytes = digest.finalize();
        artifact_digest(bytes.as_ref())
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct TrustedAotCompilerAuthority {
    compiler_identity: Box<str>,
    seal_key: [u8; 32],
    limits: AotCompilerLimits,
}

impl fmt::Debug for TrustedAotCompilerAuthority {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedAotCompilerAuthority")
            .field("compiler_identity", &self.compiler_identity)
            .field("seal_key", &"[redacted]")
            .field("limits", &self.limits)
            .finish()
    }
}

impl TrustedAotCompilerAuthority {
    pub fn new(
        compiler_identity: impl Into<Box<str>>,
        seal_key: [u8; 32],
        limits: AotCompilerLimits,
    ) -> Result<Self, PlatformError> {
        let limits = limits.validate()?;
        let compiler_identity = compiler_identity.into();
        validate_identity(&compiler_identity, limits)?;
        if seal_key.iter().all(|byte| *byte == 0) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-aot-seal-key",
            ));
        }
        Ok(Self {
            compiler_identity,
            seal_key,
            limits,
        })
    }

    pub fn seal(
        &self,
        compatibility: AotCompatibilityKey,
        output: Vec<u8>,
    ) -> Result<TrustedAotOutput, PlatformError> {
        if output.is_empty() || output.len() > self.limits.maximum_output_bytes {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "aot-output-size-out-of-bounds",
            ));
        }
        let output = output.into_boxed_slice();
        let output_digest = sha256_digest(&output);
        let seal = self.seal_value(&compatibility, &output_digest, output.len());
        Ok(TrustedAotOutput {
            compatibility,
            output,
            output_digest,
            compiler_identity: self.compiler_identity.clone(),
            seal,
        })
    }

    pub fn verify(
        &self,
        output: &TrustedAotOutput,
        expected: &AotCompatibilityKey,
    ) -> Result<(), PlatformError> {
        if output.compatibility != *expected || output.compiler_identity != self.compiler_identity {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "aot-output-authority-mismatch",
            ));
        }
        if output.output.is_empty() || output.output.len() > self.limits.maximum_output_bytes {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "aot-output-size-out-of-bounds",
            ));
        }
        let actual = sha256_digest(&output.output);
        if actual != output.output_digest {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "aot-output-digest-mismatch",
            ));
        }
        let expected_seal = self.seal_value(expected, &actual, output.output.len());
        if expected_seal != output.seal {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "aot-output-seal-mismatch",
            ));
        }
        Ok(())
    }

    fn seal_value(
        &self,
        compatibility: &AotCompatibilityKey,
        output_digest: &ArtifactBlobDigest,
        output_size: usize,
    ) -> [u8; 32] {
        let mut hasher = blake3::Hasher::new_keyed(&self.seal_key);
        hasher.update(SEAL_DOMAIN);
        frame_blake3(&mut hasher, compatibility.digest().as_str().as_bytes());
        frame_blake3(&mut hasher, output_digest.as_str().as_bytes());
        frame_blake3(&mut hasher, &(output_size as u64).to_le_bytes());
        frame_blake3(&mut hasher, self.compiler_identity.as_bytes());
        *hasher.finalize().as_bytes()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrustedAotOutput {
    compatibility: AotCompatibilityKey,
    output: Box<[u8]>,
    output_digest: ArtifactBlobDigest,
    compiler_identity: Box<str>,
    seal: [u8; 32],
}

impl TrustedAotOutput {
    #[must_use]
    pub fn compatibility(&self) -> &AotCompatibilityKey {
        &self.compatibility
    }

    #[must_use]
    pub fn output(&self) -> &[u8] {
        &self.output
    }

    #[must_use]
    pub fn output_digest(&self) -> &ArtifactBlobDigest {
        &self.output_digest
    }

    #[must_use]
    pub fn compiler_identity(&self) -> &str {
        &self.compiler_identity
    }
}

fn profile_digest(
    profile: &WasmtimeEngineProfile,
    limits: AotCompilerLimits,
) -> Result<ArtifactBlobDigest, PlatformError> {
    if profile.configuration.len() > limits.maximum_profile_entries {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "aot-profile-entry-limit",
        ));
    }
    let mut retained = 0usize;
    let mut digest = Sha256::new();
    digest.update(b"lsf-aot-engine-profile-v1\0");
    for value in [
        profile.id.as_str(),
        profile.wasmtime_version.as_str(),
        profile.target_triple.as_str(),
        profile.cpu_feature_set.as_str(),
    ] {
        validate_identity(value, limits)?;
        retained = retained.checked_add(value.len()).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "aot-profile-byte-limit",
            )
        })?;
        frame_sha256(&mut digest, value.as_bytes());
    }
    digest.update([
        u8::from(profile.pooling_allocator),
        u8::from(profile.copy_on_write_images),
        u8::from(profile.async_support),
        u8::from(profile.fuel_enabled),
        u8::from(profile.epoch_interruption_enabled),
    ]);
    for (name, value) in &profile.configuration {
        validate_identity(name, limits)?;
        validate_identity(value, limits)?;
        retained = retained
            .checked_add(name.len())
            .and_then(|total| total.checked_add(value.len()))
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "aot-profile-byte-limit",
                )
            })?;
        if retained > limits.maximum_profile_bytes {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "aot-profile-byte-limit",
            ));
        }
        frame_sha256(&mut digest, name.as_bytes());
        frame_sha256(&mut digest, value.as_bytes());
    }
    if retained > limits.maximum_profile_bytes {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "aot-profile-byte-limit",
        ));
    }
    let bytes = digest.finalize();
    Ok(artifact_digest(bytes.as_ref()))
}

fn validate_identity(value: &str, limits: AotCompilerLimits) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > limits.maximum_identity_bytes || value.contains('\0') {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-aot-identity",
        ));
    }
    Ok(())
}

fn sha256_digest(bytes: &[u8]) -> ArtifactBlobDigest {
    let digest = Sha256::digest(bytes);
    artifact_digest(digest.as_ref())
}

fn artifact_digest(bytes: &[u8]) -> ArtifactBlobDigest {
    let mut hex = String::with_capacity(71);
    hex.push_str("sha256:");
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut hex, "{byte:02x}").expect("writing to String cannot fail");
    }
    hex.parse().expect("internal SHA-256 digest is canonical")
}

fn frame_sha256(digest: &mut Sha256, bytes: &[u8]) {
    digest.update((bytes.len() as u64).to_le_bytes());
    digest.update(bytes);
}

fn frame_blake3(digest: &mut blake3::Hasher, bytes: &[u8]) {
    digest.update(&(bytes.len() as u64).to_le_bytes());
    digest.update(bytes);
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::Metadata;

    fn digest(byte: char) -> ArtifactBlobDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn package(byte: char) -> PackageDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn profile() -> WasmtimeEngineProfile {
        WasmtimeEngineProfile {
            id: "wasmtime-component-phase-1".to_owned(),
            wasmtime_version: "47.0.3".to_owned(),
            target_triple: "x86_64-unknown-linux-gnu".to_owned(),
            cpu_feature_set: "host-baseline".to_owned(),
            pooling_allocator: false,
            copy_on_write_images: true,
            async_support: true,
            fuel_enabled: true,
            epoch_interruption_enabled: true,
            configuration: Metadata::from([("fuel".to_owned(), "enabled".to_owned())]),
        }
    }

    fn key(profile: &WasmtimeEngineProfile) -> AotCompatibilityKey {
        AotCompatibilityKey::from_profile(
            package('1'),
            digest('2'),
            profile,
            digest('3'),
            digest('4'),
            AotCompilerLimits::default(),
        )
        .unwrap()
    }

    #[test]
    fn compatibility_key_changes_with_engine_contract_and_policy_inputs() {
        let original = profile();
        let baseline = key(&original).digest();
        let mut changed = original.clone();
        changed.cpu_feature_set = "host-avx2".to_owned();
        assert_ne!(key(&changed).digest(), baseline);
        changed = original.clone();
        changed
            .configuration
            .insert("fuel".to_owned(), "other".to_owned());
        assert_ne!(key(&changed).digest(), baseline);

        let contract_changed = AotCompatibilityKey::from_profile(
            package('1'),
            digest('2'),
            &original,
            digest('5'),
            digest('4'),
            AotCompilerLimits::default(),
        )
        .unwrap();
        assert_ne!(contract_changed.digest(), baseline);
        let policy_changed = AotCompatibilityKey::from_profile(
            package('1'),
            digest('2'),
            &original,
            digest('3'),
            digest('5'),
            AotCompilerLimits::default(),
        )
        .unwrap();
        assert_ne!(policy_changed.digest(), baseline);
    }

    #[test]
    fn sealed_output_is_bound_to_exact_bytes_key_and_authority() {
        let authority = TrustedAotCompilerAuthority::new(
            "trusted-local-wasmtime-aot-v1",
            [7; 32],
            AotCompilerLimits::default(),
        )
        .unwrap();
        let expected = key(&profile());
        let output = authority
            .seal(expected.clone(), b"native-image".to_vec())
            .unwrap();
        authority.verify(&output, &expected).unwrap();

        let other = TrustedAotCompilerAuthority::new(
            "trusted-local-wasmtime-aot-v1",
            [8; 32],
            AotCompilerLimits::default(),
        )
        .unwrap();
        assert_eq!(
            other.verify(&output, &expected).unwrap_err().code,
            PlatformErrorCode::PermissionDenied
        );

        let mut changed_profile = profile();
        changed_profile.target_triple = "aarch64-unknown-linux-gnu".to_owned();
        let wrong_key = key(&changed_profile);
        assert_eq!(
            authority.verify(&output, &wrong_key).unwrap_err().code,
            PlatformErrorCode::PermissionDenied
        );
    }

    #[test]
    fn excessive_output_and_profile_are_rejected_before_retention() {
        let limits = AotCompilerLimits {
            maximum_output_bytes: 4,
            ..AotCompilerLimits::default()
        };
        let expected = AotCompatibilityKey::from_profile(
            package('1'),
            digest('2'),
            &profile(),
            digest('3'),
            digest('4'),
            limits,
        )
        .unwrap();
        let authority = TrustedAotCompilerAuthority::new("compiler", [9; 32], limits).unwrap();
        assert_eq!(
            authority.seal(expected, vec![0; 5]).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );

        let mut too_large = profile();
        too_large
            .configuration
            .insert("x".repeat(1025), "y".to_owned());
        assert_eq!(
            AotCompatibilityKey::from_profile(
                package('1'),
                digest('2'),
                &too_large,
                digest('3'),
                digest('4'),
                AotCompilerLimits::default(),
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::InvalidArgument
        );
    }

    #[test]
    fn zero_seal_key_is_rejected() {
        assert_eq!(
            TrustedAotCompilerAuthority::new("compiler", [0; 32], AotCompilerLimits::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::InvalidArgument
        );
    }
}
