use std::fmt::Write as _;
use std::io::{self, Write};

use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const CYCLONEDX_JSON_MEDIA_TYPE: &str = "application/vnd.cyclonedx+json";
pub const CYCLONEDX_SPEC_VERSION: &str = "1.6";

#[derive(Debug, Clone, Copy)]
pub struct SbomLimits {
    pub max_document_bytes: usize,
    pub max_entries: usize,
    pub max_string_bytes: usize,
}

impl Default for SbomLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: 1024 * 1024,
            max_entries: 4096,
            max_string_bytes: 4096,
        }
    }
}

impl SbomLimits {
    fn validate(self) -> Result<(), PlatformError> {
        if self.max_document_bytes == 0 || self.max_entries == 0 || self.max_string_bytes == 0 {
            return Err(crate::invalid("invalid-sbom-limits"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum SbomEntryKind {
    GuestDependency,
    WitPackage,
    BuildTool,
    Asset,
}

impl SbomEntryKind {
    fn component_type(self) -> &'static str {
        match self {
            Self::GuestDependency | Self::WitPackage => "library",
            Self::BuildTool => "application",
            Self::Asset => "file",
        }
    }

    fn role(self) -> &'static str {
        match self {
            Self::GuestDependency => "guest-dependency",
            Self::WitPackage => "wit-package",
            Self::BuildTool => "build-tool",
            Self::Asset => "asset",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SbomInventoryEntry {
    pub kind: SbomEntryKind,
    pub name: String,
    pub version: Option<String>,
    pub source: Option<String>,
    pub license_expression: Option<String>,
    pub digest: Option<ArtifactBlobDigest>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomInventory {
    pub package_name: String,
    pub package_version: String,
    pub entries: Vec<SbomInventoryEntry>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomDocument {
    pub subject: PackageDigest,
    pub media_type: String,
    pub digest: ArtifactBlobDigest,
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SbomInspection {
    pub subject: PackageDigest,
    pub digest: ArtifactBlobDigest,
    pub package_name: String,
    pub package_version: String,
    pub entry_count: usize,
}

pub fn generate_cyclonedx_sbom(
    subject: PackageDigest,
    inventory: SbomInventory,
    limits: SbomLimits,
) -> Result<SbomDocument, PlatformError> {
    limits.validate()?;
    validate_string(&inventory.package_name, limits, "invalid-sbom-package-name")?;
    validate_string(
        &inventory.package_version,
        limits,
        "invalid-sbom-package-version",
    )?;
    if inventory.entries.len() > limits.max_entries {
        return Err(crate::exceeded("sbom-entry-limit"));
    }

    let mut entries = inventory.entries;
    entries.sort();
    validate_entries(&entries, limits)?;

    let components = entries
        .into_iter()
        .map(component_from_entry)
        .collect::<Vec<_>>();
    let subject_text = subject.as_str().to_owned();
    let document = CycloneDxDocument {
        bom_format: "CycloneDX".to_owned(),
        spec_version: CYCLONEDX_SPEC_VERSION.to_owned(),
        version: 1,
        metadata: CycloneDxMetadata {
            component: CycloneDxComponent {
                component_type: "application".to_owned(),
                bom_ref: Some(format!("urn:lsf:package:{subject_text}")),
                name: inventory.package_name,
                version: Some(inventory.package_version),
                hashes: Vec::new(),
                licenses: Vec::new(),
                properties: vec![property("org.lsf.package.digest", &subject_text)],
            },
            properties: vec![
                property("org.lsf.sbom.profile", "lsf-cyclonedx-1"),
                property("org.lsf.sbom.subject.kind", "oci-package-manifest"),
            ],
        },
        components,
    };
    let bytes = encode_bounded_json(&document, limits.max_document_bytes)?;
    let digest = artifact_digest(&bytes);

    Ok(SbomDocument {
        subject,
        media_type: CYCLONEDX_JSON_MEDIA_TYPE.to_owned(),
        digest,
        bytes,
    })
}

pub fn inspect_cyclonedx_sbom(
    media_type: &str,
    bytes: &[u8],
    expected_subject: &PackageDigest,
    limits: SbomLimits,
) -> Result<SbomInspection, PlatformError> {
    limits.validate()?;
    if media_type != CYCLONEDX_JSON_MEDIA_TYPE {
        return Err(crate::invalid("unsupported-sbom-media-type"));
    }
    if bytes.is_empty() || bytes.len() > limits.max_document_bytes {
        return Err(crate::exceeded("sbom-document-limit"));
    }

    let document: CycloneDxDocument =
        serde_json::from_slice(bytes).map_err(|_| crate::invalid("invalid-sbom-json"))?;
    if document.bom_format != "CycloneDX"
        || document.spec_version != CYCLONEDX_SPEC_VERSION
        || document.version != 1
        || document.metadata.component.component_type != "application"
        || document.components.len() > limits.max_entries
    {
        return Err(crate::invalid("unsupported-sbom-profile"));
    }

    validate_string(
        &document.metadata.component.name,
        limits,
        "invalid-sbom-package-name",
    )?;
    let package_version = document
        .metadata
        .component
        .version
        .as_deref()
        .ok_or_else(|| crate::invalid("missing-sbom-package-version"))?;
    validate_string(
        package_version,
        limits,
        "invalid-sbom-package-version",
    )?;

    let expected_ref = format!("urn:lsf:package:{}", expected_subject.as_str());
    if document.metadata.component.bom_ref.as_deref() != Some(expected_ref.as_str())
        || unique_property(
            &document.metadata.component.properties,
            "org.lsf.package.digest",
        )? != expected_subject.as_str()
        || unique_property(&document.metadata.properties, "org.lsf.sbom.profile")?
            != "lsf-cyclonedx-1"
        || unique_property(&document.metadata.properties, "org.lsf.sbom.subject.kind")?
            != "oci-package-manifest"
    {
        return Err(crate::invalid("sbom-subject-mismatch"));
    }

    validate_components(&document.components, limits)?;

    Ok(SbomInspection {
        subject: expected_subject.clone(),
        digest: artifact_digest(bytes),
        package_name: document.metadata.component.name,
        package_version: package_version.to_owned(),
        entry_count: document.components.len(),
    })
}

fn validate_entries(entries: &[SbomInventoryEntry], limits: SbomLimits) -> Result<(), PlatformError> {
    let mut previous_identity: Option<(SbomEntryKind, &str, Option<&str>)> = None;
    for entry in entries {
        validate_string(&entry.name, limits, "invalid-sbom-entry-name")?;
        validate_optional_string(
            entry.version.as_deref(),
            limits,
            "invalid-sbom-entry-version",
        )?;
        validate_optional_string(entry.source.as_deref(), limits, "invalid-sbom-entry-source")?;
        validate_optional_string(
            entry.license_expression.as_deref(),
            limits,
            "invalid-sbom-entry-license",
        )?;

        let identity = (entry.kind, entry.name.as_str(), entry.version.as_deref());
        if previous_identity == Some(identity) {
            return Err(crate::invalid("duplicate-sbom-entry"));
        }
        previous_identity = Some(identity);
    }
    Ok(())
}

fn validate_components(
    components: &[CycloneDxComponent],
    limits: SbomLimits,
) -> Result<(), PlatformError> {
    let mut identities = Vec::with_capacity(components.len());
    for component in components {
        validate_string(&component.name, limits, "invalid-sbom-entry-name")?;
        validate_optional_string(
            component.version.as_deref(),
            limits,
            "invalid-sbom-entry-version",
        )?;
        let role = unique_property(&component.properties, "org.lsf.inventory.role")?;
        if !matches!(
            role,
            "guest-dependency" | "wit-package" | "build-tool" | "asset"
        ) {
            return Err(crate::invalid("invalid-sbom-entry-role"));
        }
        let source_status = unique_property(&component.properties, "org.lsf.source.status")?;
        if !matches!(source_status, "declared" | "unavailable") {
            return Err(crate::invalid("invalid-sbom-source-status"));
        }
        let license_status = unique_property(&component.properties, "org.lsf.license.status")?;
        if !matches!(license_status, "declared" | "unavailable") {
            return Err(crate::invalid("invalid-sbom-license-status"));
        }
        identities.push((role.to_owned(), component.name.clone(), component.version.clone()));
    }
    identities.sort();
    if identities.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(crate::invalid("duplicate-sbom-entry"));
    }
    Ok(())
}

fn component_from_entry(entry: SbomInventoryEntry) -> CycloneDxComponent {
    let source_status = if entry.source.is_some() {
        "declared"
    } else {
        "unavailable"
    };
    let license_status = if entry.license_expression.is_some() {
        "declared"
    } else {
        "unavailable"
    };
    let mut properties = vec![
        property("org.lsf.inventory.role", entry.kind.role()),
        property("org.lsf.source.status", source_status),
        property("org.lsf.license.status", license_status),
    ];
    if let Some(source) = entry.source {
        properties.push(property("org.lsf.source", &source));
    }
    properties.sort_by(|left, right| left.name.cmp(&right.name));

    let hashes = entry.digest.map_or_else(Vec::new, |digest| {
        vec![CycloneDxHash {
            algorithm: "SHA-256".to_owned(),
            content: digest
                .as_str()
                .strip_prefix("sha256:")
                .expect("artifact digests are canonical sha256 values")
                .to_owned(),
        }]
    });
    let licenses = entry.license_expression.map_or_else(Vec::new, |expression| {
        vec![CycloneDxLicenseChoice { expression }]
    });

    CycloneDxComponent {
        component_type: entry.kind.component_type().to_owned(),
        bom_ref: None,
        name: entry.name,
        version: entry.version,
        hashes,
        licenses,
        properties,
    }
}

fn property(name: &str, value: &str) -> CycloneDxProperty {
    CycloneDxProperty {
        name: name.to_owned(),
        value: value.to_owned(),
    }
}

fn unique_property<'a>(
    properties: &'a [CycloneDxProperty],
    name: &str,
) -> Result<&'a str, PlatformError> {
    let mut values = properties
        .iter()
        .filter(|property| property.name == name)
        .map(|property| property.value.as_str());
    let value = values
        .next()
        .ok_or_else(|| crate::invalid("missing-sbom-property"))?;
    if values.next().is_some() {
        return Err(crate::invalid("duplicate-sbom-property"));
    }
    Ok(value)
}

fn validate_string(
    value: &str,
    limits: SbomLimits,
    reason: &'static str,
) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > limits.max_string_bytes || value.contains('\0') {
        return Err(crate::invalid(reason));
    }
    Ok(())
}

fn validate_optional_string(
    value: Option<&str>,
    limits: SbomLimits,
    reason: &'static str,
) -> Result<(), PlatformError> {
    if let Some(value) = value {
        validate_string(value, limits, reason)?;
    }
    Ok(())
}

fn artifact_digest(bytes: &[u8]) -> ArtifactBlobDigest {
    let mut value = String::with_capacity(71);
    value.push_str("sha256:");
    for byte in Sha256::digest(bytes) {
        write!(&mut value, "{byte:02x}").expect("writing to String cannot fail");
    }
    value
        .parse()
        .expect("locally formatted SHA-256 digest is canonical")
}

fn encode_bounded_json<T: Serialize>(
    value: &T,
    maximum: usize,
) -> Result<Vec<u8>, PlatformError> {
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| crate::exceeded("sbom-document-limit"))?;
    Ok(writer.bytes)
}

struct LimitedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Write for LimitedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let next = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|value| *value <= self.maximum)
            .ok_or_else(|| io::Error::other("sbom document limit"))?;
        if next > self.bytes.capacity() {
            let capacity = next
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxDocument {
    #[serde(rename = "bomFormat")]
    bom_format: String,
    spec_version: String,
    version: u32,
    metadata: CycloneDxMetadata,
    components: Vec<CycloneDxComponent>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxMetadata {
    component: CycloneDxComponent,
    properties: Vec<CycloneDxProperty>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxComponent {
    #[serde(rename = "type")]
    component_type: String,
    #[serde(rename = "bom-ref", skip_serializing_if = "Option::is_none")]
    bom_ref: Option<String>,
    name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    version: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    hashes: Vec<CycloneDxHash>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    licenses: Vec<CycloneDxLicenseChoice>,
    properties: Vec<CycloneDxProperty>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxHash {
    #[serde(rename = "alg")]
    algorithm: String,
    content: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxLicenseChoice {
    expression: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CycloneDxProperty {
    name: String,
    value: String,
}

#[cfg(test)]
mod tests {
    use super::{
        generate_cyclonedx_sbom, inspect_cyclonedx_sbom, SbomEntryKind, SbomInventory,
        SbomInventoryEntry, SbomLimits, CYCLONEDX_JSON_MEDIA_TYPE,
    };
    use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformErrorCode};

    fn package_digest(byte: char) -> PackageDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn blob_digest(byte: char) -> ArtifactBlobDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    fn entry(kind: SbomEntryKind, name: &str) -> SbomInventoryEntry {
        SbomInventoryEntry {
            kind,
            name: name.to_owned(),
            version: Some("1.0.0".to_owned()),
            source: Some(format!("https://example.invalid/{name}")),
            license_expression: Some("Apache-2.0".to_owned()),
            digest: Some(blob_digest('b')),
        }
    }

    #[test]
    fn stable_inventory_order_produces_identical_exact_bytes() {
        let subject = package_digest('a');
        let first = SbomInventory {
            package_name: "demo".to_owned(),
            package_version: "1.0.0".to_owned(),
            entries: vec![
                entry(SbomEntryKind::WitPackage, "wit"),
                entry(SbomEntryKind::GuestDependency, "guest"),
                entry(SbomEntryKind::BuildTool, "tool"),
                entry(SbomEntryKind::Asset, "index.html"),
            ],
        };
        let mut second = first.clone();
        second.entries.reverse();

        let first = generate_cyclonedx_sbom(subject.clone(), first, SbomLimits::default()).unwrap();
        let second = generate_cyclonedx_sbom(subject, second, SbomLimits::default()).unwrap();

        assert_eq!(first.bytes, second.bytes);
        assert_eq!(first.digest, second.digest);
    }

    #[test]
    fn inspection_preserves_subject_and_explicit_unavailable_attribution() {
        let subject = package_digest('c');
        let inventory = SbomInventory {
            package_name: "assets".to_owned(),
            package_version: "2.0.0".to_owned(),
            entries: vec![SbomInventoryEntry {
                kind: SbomEntryKind::Asset,
                name: "app.js".to_owned(),
                version: None,
                source: None,
                license_expression: None,
                digest: Some(blob_digest('d')),
            }],
        };
        let document =
            generate_cyclonedx_sbom(subject.clone(), inventory, SbomLimits::default()).unwrap();
        let text = std::str::from_utf8(&document.bytes).unwrap();

        assert!(text.contains("\"org.lsf.source.status\",\"value\":\"unavailable\""));
        assert!(text.contains("\"org.lsf.license.status\",\"value\":\"unavailable\""));

        let inspected = inspect_cyclonedx_sbom(
            CYCLONEDX_JSON_MEDIA_TYPE,
            &document.bytes,
            &subject,
            SbomLimits::default(),
        )
        .unwrap();
        assert_eq!(inspected.subject, subject);
        assert_eq!(inspected.digest, document.digest);
        assert_eq!(inspected.entry_count, 1);
        assert_eq!(inspected.package_name, "assets");
        assert_eq!(inspected.package_version, "2.0.0");
    }

    #[test]
    fn wrong_subject_unsupported_media_and_duplicates_fail_closed() {
        let subject = package_digest('e');
        let inventory = SbomInventory {
            package_name: "demo".to_owned(),
            package_version: "1".to_owned(),
            entries: vec![entry(SbomEntryKind::GuestDependency, "dep")],
        };
        let document = generate_cyclonedx_sbom(
            subject.clone(),
            inventory.clone(),
            SbomLimits::default(),
        )
        .unwrap();

        let wrong = inspect_cyclonedx_sbom(
            CYCLONEDX_JSON_MEDIA_TYPE,
            &document.bytes,
            &package_digest('f'),
            SbomLimits::default(),
        )
        .unwrap_err();
        assert_eq!(wrong.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(wrong.message, "sbom-subject-mismatch");

        let unsupported = inspect_cyclonedx_sbom(
            "application/json",
            &document.bytes,
            &subject,
            SbomLimits::default(),
        )
        .unwrap_err();
        assert_eq!(unsupported.message, "unsupported-sbom-media-type");

        let duplicate = generate_cyclonedx_sbom(
            subject,
            SbomInventory {
                entries: vec![
                    entry(SbomEntryKind::GuestDependency, "dep"),
                    entry(SbomEntryKind::GuestDependency, "dep"),
                ],
                ..inventory
            },
            SbomLimits::default(),
        )
        .unwrap_err();
        assert_eq!(duplicate.message, "duplicate-sbom-entry");
    }

    #[test]
    fn document_and_entry_limits_are_enforced_before_acceptance() {
        let subject = package_digest('a');
        let inventory = SbomInventory {
            package_name: "demo".to_owned(),
            package_version: "1".to_owned(),
            entries: vec![entry(SbomEntryKind::Asset, "asset")],
        };
        let entry_limited = SbomLimits {
            max_entries: 0,
            ..SbomLimits::default()
        };
        assert_eq!(
            generate_cyclonedx_sbom(subject.clone(), inventory.clone(), entry_limited)
                .unwrap_err()
                .message,
            "invalid-sbom-limits"
        );

        let byte_limited = SbomLimits {
            max_document_bytes: 64,
            ..SbomLimits::default()
        };
        let error = generate_cyclonedx_sbom(subject, inventory, byte_limited).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(error.message, "sbom-document-limit");
    }
}
