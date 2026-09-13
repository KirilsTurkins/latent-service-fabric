use latent_artifacts::package::PackageKind;
use latent_core::ArtifactBlobDigest;
use serde::{Deserialize, Serialize};

macro_rules! vocabulary {
    ($name:ident { $($variant:ident => $text:literal),+ $(,)? }) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
        #[serde(rename_all = "kebab-case")]
        pub enum $name { $($variant),+ }
        impl $name {
            #[must_use] pub const fn as_str(self) -> &'static str { match self { $(Self::$variant => $text),+ } }
            pub(crate) fn parse(value: &str) -> Option<Self> { match value { $($text => Some(Self::$variant),)+ _ => None } }
        }
    };
}
vocabulary!(SbomEntryKind {
    GuestDependency => "guest-dependency", BuildDependency => "build-dependency",
    ProcMacro => "proc-macro", BuildScript => "build-script", WitPackage => "wit-package",
    BuildTool => "build-tool", Asset => "asset", Component => "component", Renderer => "renderer"
});
impl SbomEntryKind {
    pub const ALL: [Self; 9] = [
        Self::GuestDependency,
        Self::BuildDependency,
        Self::ProcMacro,
        Self::BuildScript,
        Self::WitPackage,
        Self::BuildTool,
        Self::Asset,
        Self::Component,
        Self::Renderer,
    ];
    #[must_use]
    pub const fn index(self) -> usize {
        self as usize
    }
    pub(crate) const fn component_type(self) -> &'static str {
        match self {
            Self::BuildTool | Self::Component | Self::Renderer => "application",
            Self::Asset => "file",
            _ => "library",
        }
    }
    pub(crate) const fn is_dependency(self) -> bool {
        matches!(
            self,
            Self::GuestDependency | Self::BuildDependency | Self::ProcMacro | Self::BuildScript
        )
    }
}
vocabulary!(SbomDependencyCompleteness {
    ObservedUnitsIncomplete => "observed-units-incomplete", DeclaredInputsIncomplete => "declared-inputs-incomplete"
});
vocabulary!(SbomDigestScope {
    OutputBytes => "output-bytes", WitSource => "wit-source", ToolExecutable => "tool-executable",
    RegistryArchiveDeclared => "registry-archive-declared", SourceManifest => "source-manifest"
});
vocabulary!(SbomEntryOrigin {
    CapturedSource => "captured-source", ObservedCache => "observed-cache", Toolchain => "toolchain",
    PackageInput => "package-input", Supplied => "supplied"
});

/// Untrusted normalized input. Optional values are omitted, never represented by null.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SbomInventoryEntry {
    pub kind: SbomEntryKind,
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub license_expression: Option<String>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "optional_digest"
    )]
    pub digest: Option<ArtifactBlobDigest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest_scope: Option<SbomDigestScope>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "optional_digest"
    )]
    pub manifest_digest: Option<ArtifactBlobDigest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub manifest_size: Option<u64>,
    pub origin: SbomEntryOrigin,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SbomInventory {
    pub format_version: u32,
    pub package_kind: PackageKind,
    pub package_name: String,
    pub package_version: String,
    pub dependency_completeness: SbomDependencyCompleteness,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "optional_digest"
    )]
    pub source_snapshot_digest: Option<ArtifactBlobDigest>,
    pub entries: Vec<SbomInventoryEntry>,
}

mod optional_digest {
    use super::{ArtifactBlobDigest, Deserialize, Serialize};
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
        decoder: D,
    ) -> Result<Option<ArtifactBlobDigest>, D::Error> {
        String::deserialize(decoder)?
            .parse()
            .map(Some)
            .map_err(serde::de::Error::custom)
    }
}
