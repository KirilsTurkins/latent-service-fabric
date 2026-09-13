//! Strict mapping between normalized inventory and the closed `CycloneDX` profile.
use super::{
    SbomDependencyCompleteness, SbomDigestScope, SbomEntryKind, SbomEntryOrigin, SbomInventory,
    SbomInventoryEntry, CYCLONEDX_SPEC_VERSION,
};
use latent_artifacts::package::{artifact_blob_digest, PackageKind};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Document {
    bom_format: String,
    spec_version: String,
    version: u32,
    metadata: Metadata,
    components: Vec<Component>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    component: Root,
    properties: Vec<Property>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Root {
    #[serde(rename = "type")]
    component_type: String,
    #[serde(rename = "bom-ref")]
    bom_ref: String,
    name: String,
    version: String,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Component {
    #[serde(rename = "type")]
    #[allow(clippy::struct_field_names)] // Explicit wire meaning shared with root component.
    component_type: String,
    #[serde(rename = "bom-ref")]
    bom_ref: String,
    name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    hashes: Option<Vec<Hash>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    licenses: Option<Vec<License>>,
    properties: Vec<Property>,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Hash {
    alg: String,
    content: String,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct License {
    expression: String,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Property {
    name: String,
    value: String,
}

fn property(name: &str, value: &str) -> Property {
    Property {
        name: name.to_owned(),
        value: value.to_owned(),
    }
}
pub(super) fn encode(input: &SbomInventory) -> Result<Document, PlatformError> {
    let mut properties = vec![
        property("lsf:profile", "lsf-cyclonedx-embedded-1"),
        property("lsf:subject-kind", "package-content"),
        property(
            "lsf:package-kind",
            match input.package_kind {
                PackageKind::Capsule => "capsule",
                PackageKind::BrowserAssets => "browser-assets",
                PackageKind::SsrPackage => "ssr-package",
            },
        ),
        property(
            "lsf:dependency-completeness",
            input.dependency_completeness.as_str(),
        ),
    ];
    if let Some(digest) = &input.source_snapshot_digest {
        properties.push(property("lsf:source-snapshot-digest", digest.as_str()));
    }
    properties.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(Document {
        bom_format: "CycloneDX".to_owned(),
        spec_version: CYCLONEDX_SPEC_VERSION.to_owned(),
        version: 1,
        metadata: Metadata {
            component: Root {
                component_type: "application".to_owned(),
                bom_ref: "urn:lsf:package:input".to_owned(),
                name: input.package_name.clone(),
                version: input.package_version.clone(),
            },
            properties,
        },
        components: input
            .entries
            .iter()
            .map(component)
            .collect::<Result<_, _>>()?,
    })
}
fn component(row: &SbomInventoryEntry) -> Result<Component, PlatformError> {
    let identity = artifact_blob_digest(&super::json::encode(row, 16_384)?);
    let mut properties = vec![
        property("lsf:role", row.kind.as_str()),
        property("lsf:origin", row.origin.as_str()),
        property(
            "lsf:source-status",
            if row.source.is_some() {
                "declared"
            } else {
                "unavailable"
            },
        ),
        property(
            "lsf:license-status",
            if row.license_expression.is_some() {
                "declared"
            } else {
                "unavailable"
            },
        ),
    ];
    for (key, value) in [
        ("lsf:source", row.source.as_deref()),
        ("lsf:path", row.path.as_deref()),
        (
            "lsf:digest-scope",
            row.digest_scope.map(SbomDigestScope::as_str),
        ),
        (
            "lsf:manifest-digest",
            row.manifest_digest
                .as_ref()
                .map(latent_core::ArtifactBlobDigest::as_str),
        ),
    ] {
        if let Some(value) = value {
            properties.push(property(key, value));
        }
    }
    if let Some(size) = row.size {
        properties.push(property("lsf:size", &size.to_string()));
    }
    if let Some(size) = row.manifest_size {
        properties.push(property("lsf:manifest-size", &size.to_string()));
    }
    properties.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(Component {
        component_type: row.kind.component_type().to_owned(),
        bom_ref: format!("urn:lsf:entry:{identity}"),
        name: row.name.clone(),
        version: row.version.clone(),
        hashes: row.digest.as_ref().map(|digest| {
            vec![Hash {
                alg: "SHA-256".to_owned(),
                content: digest.as_str()[7..].to_owned(),
            }]
        }),
        licenses: row.license_expression.as_ref().map(|expression| {
            vec![License {
                expression: expression.clone(),
            }]
        }),
        properties,
    })
}
pub(super) fn decode(document: Document) -> Result<SbomInventory, PlatformError> {
    if document.bom_format != "CycloneDX"
        || document.spec_version != CYCLONEDX_SPEC_VERSION
        || document.version != 1
        || document.metadata.component.component_type != "application"
        || document.metadata.component.bom_ref != "urn:lsf:package:input"
    {
        return Err(crate::invalid("unsupported-sbom-profile"));
    }
    let mut props = properties(document.metadata.properties)?;
    if take(&mut props, "lsf:profile")? != "lsf-cyclonedx-embedded-1"
        || take(&mut props, "lsf:subject-kind")? != "package-content"
    {
        return Err(crate::invalid("unsupported-sbom-profile"));
    }
    let package_kind = match take(&mut props, "lsf:package-kind")?.as_str() {
        "capsule" => PackageKind::Capsule,
        "browser-assets" => PackageKind::BrowserAssets,
        "ssr-package" => PackageKind::SsrPackage,
        _ => return Err(crate::invalid("invalid-sbom-package-kind")),
    };
    let dependency_completeness =
        SbomDependencyCompleteness::parse(&take(&mut props, "lsf:dependency-completeness")?)
            .ok_or_else(|| crate::invalid("invalid-sbom-completeness"))?;
    let source_snapshot_digest = digest(props.remove("lsf:source-snapshot-digest"))?;
    if !props.is_empty() {
        return Err(crate::invalid("unknown-sbom-property"));
    }
    Ok(SbomInventory {
        format_version: 1,
        package_kind,
        package_name: document.metadata.component.name,
        package_version: document.metadata.component.version,
        dependency_completeness,
        source_snapshot_digest,
        entries: document
            .components
            .into_iter()
            .map(entry)
            .collect::<Result<_, _>>()?,
    })
}
fn entry(mut input: Component) -> Result<SbomInventoryEntry, PlatformError> {
    let mut props = properties(std::mem::take(&mut input.properties))?;
    let kind = SbomEntryKind::parse(&take(&mut props, "lsf:role")?)
        .ok_or_else(|| crate::invalid("invalid-sbom-entry-role"))?;
    let origin = SbomEntryOrigin::parse(&take(&mut props, "lsf:origin")?)
        .ok_or_else(|| crate::invalid("invalid-sbom-entry-origin"))?;
    let source = props.remove("lsf:source");
    let license_expression = match &input.licenses {
        None => None,
        Some(values) if values.len() == 1 => Some(values[0].expression.clone()),
        _ => return Err(crate::invalid("invalid-sbom-license-choice")),
    };
    if take(&mut props, "lsf:source-status")?
        != if source.is_some() {
            "declared"
        } else {
            "unavailable"
        }
        || take(&mut props, "lsf:license-status")?
            != if license_expression.is_some() {
                "declared"
            } else {
                "unavailable"
            }
    {
        return Err(crate::invalid("sbom-attribution-status-mismatch"));
    }
    let hash = match &input.hashes {
        None => None,
        Some(hashes) if hashes.len() == 1 && hashes[0].alg == "SHA-256" => {
            digest(Some(format!("sha256:{}", hashes[0].content)))?
        }
        _ => return Err(crate::invalid("invalid-sbom-hash")),
    };
    let digest_scope = props
        .remove("lsf:digest-scope")
        .map(|value| {
            SbomDigestScope::parse(&value)
                .ok_or_else(|| crate::invalid("invalid-sbom-digest-scope"))
        })
        .transpose()?;
    let row = SbomInventoryEntry {
        kind,
        name: input.name.clone(),
        version: input.version.clone(),
        source,
        license_expression,
        digest: hash,
        digest_scope,
        size: number(props.remove("lsf:size"))?,
        path: props.remove("lsf:path"),
        manifest_digest: digest(props.remove("lsf:manifest-digest"))?,
        manifest_size: number(props.remove("lsf:manifest-size"))?,
        origin,
    };
    if !props.is_empty() {
        return Err(crate::invalid("unknown-sbom-property"));
    }
    let expected = component(&row)?;
    if input.component_type != expected.component_type || input.bom_ref != expected.bom_ref {
        return Err(crate::invalid("sbom-component-identity-mismatch"));
    }
    Ok(row)
}
fn properties(values: Vec<Property>) -> Result<BTreeMap<String, String>, PlatformError> {
    let mut map = BTreeMap::new();
    for value in values {
        if map.insert(value.name, value.value).is_some() {
            return Err(crate::invalid("duplicate-sbom-property"));
        }
    }
    Ok(map)
}
fn take(values: &mut BTreeMap<String, String>, key: &str) -> Result<String, PlatformError> {
    values
        .remove(key)
        .ok_or_else(|| crate::invalid("missing-sbom-property"))
}
fn digest(value: Option<String>) -> Result<Option<latent_core::ArtifactBlobDigest>, PlatformError> {
    value
        .map(|value| {
            value
                .parse()
                .map_err(|_| crate::invalid("invalid-sbom-digest"))
        })
        .transpose()
}
fn number(value: Option<String>) -> Result<Option<u64>, PlatformError> {
    value
        .map(|value| {
            let result = value
                .parse::<u64>()
                .map_err(|_| crate::invalid("invalid-sbom-size"))?;
            if value != result.to_string() {
                return Err(crate::invalid("invalid-sbom-size"));
            }
            Ok(result)
        })
        .transpose()
}
