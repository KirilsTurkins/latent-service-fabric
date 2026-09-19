use super::{invalid, IMMUTABLE_ASSET_PREFIX};
use crate::PublicationRef;
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError};
use serde::{Deserialize, Serialize};

/// Supplied immutable metadata. Deserialization never constructs an admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebApplicationManifest {
    pub format_version: u32,
    pub profile: String,
    pub assets_digest: String,
    pub assets: Vec<WebAsset>,
    pub routes: Vec<WebRoute>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub renderer: Option<WebRenderer>,
}

/// Only these explicit entries may become public assets. Other Asset-role
/// layers (including SBOMs, build material and server metadata) stay private.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebAsset {
    pub path: String,
    pub layer: String,
    pub digest: String,
    pub size: u64,
    pub media_type: String,
}

pub use latent_manifest::RendererProfile as WebRendererProfile;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebRenderer {
    pub layer: String,
    pub digest: String,
    pub size: u64,
    pub profile: WebRendererProfile,
    pub profile_digest: String,
    pub assets_digest: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum WebRenderMode {
    Client,
    Prerender,
    Server,
}

/// Exact paths only. Host/tenant routing and authentication are deployment
/// policy; this signed package cannot claim a public hostname or principal.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebRoute {
    pub path: String,
    pub mode: WebRenderMode,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub asset: Option<String>,
}

/// Immutable association of checked package descriptors and web metadata.
/// Content-byte validation and current admission remain independent gates.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckedWebLayout {
    pub(super) package: PackageDigest,
    pub(super) name: String,
    pub(super) version: String,
    pub(super) manifest_digest: ArtifactBlobDigest,
    pub(super) assets_digest: ArtifactBlobDigest,
    pub(super) manifest: WebApplicationManifest,
}

impl CheckedWebLayout {
    #[must_use]
    pub fn package(&self) -> &PackageDigest {
        &self.package
    }

    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    #[must_use]
    pub fn manifest_digest(&self) -> &ArtifactBlobDigest {
        &self.manifest_digest
    }

    #[must_use]
    pub fn assets_digest(&self) -> &ArtifactBlobDigest {
        &self.assets_digest
    }

    #[must_use]
    pub fn manifest(&self) -> &WebApplicationManifest {
        &self.manifest
    }

    #[must_use]
    pub fn asset(&self, path: &str) -> Option<&WebAsset> {
        self.manifest
            .assets
            .binary_search_by(|asset| asset.path.as_str().cmp(path))
            .ok()
            .map(|index| &self.manifest.assets[index])
    }

    /// Constructs an immutable locator, not a serving authorization. The
    /// request's authenticated tenant and current publication must still match.
    pub fn asset_url(
        &self,
        publication: &PublicationRef,
        path: &str,
    ) -> Result<String, PlatformError> {
        let expected = PublicationRef::package(publication.scope.clone(), &self.package)?;
        if publication != &expected || publication.scope.tenant().is_none() {
            return Err(invalid("web-publication-association"));
        }
        let asset = self
            .asset(path)
            .ok_or_else(|| invalid("web-asset-not-public"))?;
        Ok(format!(
            "{IMMUTABLE_ASSET_PREFIX}{}{path}",
            publication.id,
            path = asset.path
        ))
    }

    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let mut bytes = std::mem::size_of::<Self>()
            + 1024
            + self.name.capacity()
            + self.version.capacity()
            + self.manifest.profile.capacity()
            + self.manifest.assets_digest.capacity();
        bytes += self.manifest.assets.capacity() * std::mem::size_of::<WebAsset>();
        for asset in &self.manifest.assets {
            bytes += asset.path.capacity()
                + asset.layer.capacity()
                + asset.digest.capacity()
                + asset.media_type.capacity();
        }
        bytes += self.manifest.routes.capacity() * std::mem::size_of::<WebRoute>();
        for route in &self.manifest.routes {
            bytes += route.path.capacity() + route.asset.as_ref().map_or(0, String::capacity);
        }
        if let Some(renderer) = &self.manifest.renderer {
            bytes += renderer.layer.capacity()
                + renderer.digest.capacity()
                + renderer.profile_digest.capacity()
                + renderer.assets_digest.capacity();
        }
        bytes
    }
}
