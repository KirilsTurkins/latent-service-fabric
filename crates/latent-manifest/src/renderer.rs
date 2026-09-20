//! Portable renderer requirements, separate from publication permission and
//! native engine/target/security identity.
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum RendererProfile {
    WasmWebBufferedV1,
    AngularSsrComponentV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RendererRequirement {
    pub profile: RendererProfile,
    pub profile_digest: String,
}

impl RendererRequirement {
    #[must_use]
    pub fn angular() -> Self {
        Self {
            profile: RendererProfile::AngularSsrComponentV1,
            profile_digest: renderer_profile_digest(RendererProfile::AngularSsrComponentV1)
                .to_string(),
        }
    }

    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.profile_digest.capacity() > 128
            || self.profile_digest.parse::<ArtifactBlobDigest>().is_err()
        {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "invalid-renderer-requirement".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        Ok(())
    }
}

/// Existing buffered Wasm identities are preserved. The Angular profile binds
/// the fixed composition adapter as well as its finite execution contract.
/// Exact application/component/package bytes and native settings are additional
/// immutable preparation inputs; this digest conveys no execution authority.
#[must_use]
pub fn renderer_profile_digest(profile: RendererProfile) -> ArtifactBlobDigest {
    let mut hash = Sha256::new();
    part(&mut hash, b"lsf-web-renderer-compatibility-v1");
    part(
        &mut hash,
        include_bytes!("../../../wit/platform/web/package.wit"),
    );
    part(
        &mut hash,
        include_bytes!("../../../wit/host-abi-phase3-v4.json"),
    );
    part(
        &mut hash,
        b"wasmtime-47.0.4;fresh-store;on-demand;cranelift-speed;buffered-v1",
    );
    match profile {
        RendererProfile::WasmWebBufferedV1 => part(&mut hash, b"wasm-web-buffered-v1"),
        RendererProfile::AngularSsrComponentV1 => {
            part(&mut hash, b"angular-ssr-component-v1;angular-22.1.6;componentize-js-0.22.0;zero-delay-256;microtasks-4096;no-ambient-io;aggregate-memory-268435456;memories-2;instances-32;tables-4;table-elements-131072;stack-2097152;async-stack-4194304;binary-operators-8000000;binary-types-262144;cpu-fuel-2000000000;wall-millis-5000;input-frame-262144;result-frame-1048576;html-131072");
            for source in [
                include_bytes!("../../../tools/angular-renderer-adapter/src/lib.rs").as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/src/wire.rs").as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/src/abi.rs").as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/src/backend.rs").as_slice(),
                include_bytes!("../../../wit/platform/http-v2/package.wit").as_slice(),
                include_bytes!("../../../wit/platform/web-http/package.wit").as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/wit/adapter.wit")
                    .as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/runtime/bridge.js")
                    .as_slice(),
                include_bytes!("../../../tools/angular-renderer-adapter/runtime/timers.js")
                    .as_slice(),
            ] {
                part(&mut hash, source);
            }
        }
    }
    format!("sha256:{:x}", hash.finalize())
        .parse()
        .expect("SHA-256 digest")
}

fn part(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
}
