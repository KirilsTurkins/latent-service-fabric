use std::collections::BTreeMap;

use latent_core::{ArtifactBlobDigest, PackageDigest};
use serde::{Deserialize, Serialize};

/// Package shape; only `Capsule` represents a potentially executable capsule.
/// Kind selection is not authorization or a promise of runtime compatibility.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum PackageKind {
    Capsule,
    BrowserAssets,
    SsrPackage,
}

impl PackageKind {
    #[must_use]
    pub const fn artifact_type(self) -> &'static str {
        match self {
            Self::Capsule => "application/vnd.latent.capsule.v1",
            Self::BrowserAssets => "application/vnd.latent.browser-assets.v1",
            Self::SsrPackage => "application/vnd.latent.ssr-package.v1",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum LayerRole {
    Component,
    CapsuleManifest,
    Contracts,
    WitLock,
    Asset,
    Renderer,
}

impl LayerRole {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Component => "component",
            Self::CapsuleManifest => "capsule-manifest",
            Self::Contracts => "contracts",
            Self::WitLock => "wit-lock",
            Self::Asset => "asset",
            Self::Renderer => "renderer",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageLayer {
    pub path: String,
    pub role: LayerRole,
    pub media_type: String,
    #[serde(with = "blob_digest")]
    pub digest: ArtifactBlobDigest,
    pub size: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageConfig {
    pub format_version: u32,
    pub kind: PackageKind,
    pub name: String,
    pub version: String,
    pub entrypoint: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "optional_blob_digest"
    )]
    pub component_digest: Option<ArtifactBlobDigest>,
    pub layers: Vec<PackageLayer>,
    pub annotations: BTreeMap<String, String>,
}

/// Strict subset of the OCI descriptor. URLs, inline data, platform and unknown
/// fields are unsupported. Config annotations are absent; layer annotations are
/// exactly the package title/role keys.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactDescriptor {
    pub media_type: String,
    #[serde(with = "blob_digest")]
    pub digest: ArtifactBlobDigest,
    pub size: u64,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "optional_annotations"
    )]
    pub annotations: Option<BTreeMap<String, String>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageManifest {
    pub schema_version: u32,
    pub media_type: String,
    pub artifact_type: String,
    pub config: ArtifactDescriptor,
    pub layers: Vec<ArtifactDescriptor>,
    pub annotations: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvidenceKind {
    Signature,
    Provenance,
    Sbom,
}

impl EvidenceKind {
    #[must_use]
    pub const fn artifact_type(self) -> &'static str {
        match self {
            Self::Signature => "application/vnd.latent.signature.v1",
            Self::Provenance => "application/vnd.latent.provenance.v1",
            Self::Sbom => "application/vnd.latent.sbom.v1",
        }
    }
    #[must_use]
    pub const fn payload_media_type(self) -> &'static str {
        match self {
            Self::Signature => "application/vnd.latent.signature.payload.v1+json",
            Self::Provenance => "application/vnd.latent.provenance.payload.v1+json",
            Self::Sbom => "application/vnd.latent.sbom.payload.v1+json",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageSubject {
    pub media_type: String,
    #[serde(with = "package_digest")]
    pub digest: PackageDigest,
    pub size: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReferrerManifest {
    pub schema_version: u32,
    pub media_type: String,
    pub artifact_type: String,
    pub config: ArtifactDescriptor,
    pub layers: Vec<ArtifactDescriptor>,
    pub subject: PackageSubject,
    pub annotations: BTreeMap<String, String>,
}

macro_rules! digest_serde {
    ($module:ident, $ty:ident) => {
        mod $module {
            use latent_core::$ty;
            use serde::Deserialize;
            pub fn serialize<S: serde::Serializer>(
                value: &$ty,
                serializer: S,
            ) -> Result<S::Ok, S::Error> {
                serializer.serialize_str(value.as_str())
            }
            pub fn deserialize<'de, D: serde::Deserializer<'de>>(
                deserializer: D,
            ) -> Result<$ty, D::Error> {
                String::deserialize(deserializer)?
                    .parse()
                    .map_err(serde::de::Error::custom)
            }
        }
    };
}
digest_serde!(blob_digest, ArtifactBlobDigest);
digest_serde!(package_digest, PackageDigest);

mod optional_blob_digest {
    use super::{blob_digest, ArtifactBlobDigest, Serialize};
    // Serde's serialize_with contract requires a reference to the field type.
    #[allow(clippy::ref_option)]
    pub fn serialize<S: serde::Serializer>(
        value: &Option<ArtifactBlobDigest>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value
            .as_ref()
            .map(ArtifactBlobDigest::as_str)
            .serialize(serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Option<ArtifactBlobDigest>, D::Error> {
        // A present null is not an absent optional member.
        blob_digest::deserialize(deserializer).map(Some)
    }
}

fn optional_annotations<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<BTreeMap<String, String>>, D::Error> {
    BTreeMap::deserialize(deserializer).map(Some)
}
