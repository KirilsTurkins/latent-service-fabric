//! Explicit detached-evidence files kept outside the exact package inventory.
use cap_fs_ext::DirExt;
use latent_artifacts::package::{
    artifact_blob_digest, validate_package_json, validate_package_path, PackageLimits,
};
use latent_artifacts::{AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::{PackageDigest, PlatformError};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::Path;

const MAX_TOTAL: usize = 16 * 1024 * 1024;
const MAX_ENTRIES: usize = 8;

/// Closed client file selection; data and referrer identity remain untrusted.
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageEvidenceIndex {
    pub format_version: u32,
    pub package_digest: String,
    pub signatures: Vec<PackageEvidenceFiles>,
    pub provenance: Vec<PackageEvidenceFiles>,
    pub sboms: Vec<PackageEvidenceFiles>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PackageEvidenceFiles {
    pub manifest: String,
    pub configuration: String,
    pub payload: String,
}

fn limits() -> PackageLimits {
    PackageLimits {
        max_document_bytes: 16 * 1024,
        max_depth: 8,
        max_nodes: 256,
        max_string_bytes: 240,
        ..PackageLimits::default()
    }
}

/// Reads only named regular descendants from one capability root. Each file is
/// bounded before allocation; exact detached association/trust is checked later
/// by the existing signature/provenance/SBOM codecs and admission policy.
pub fn read_package_evidence(
    root: &Path,
    index_bytes: &[u8],
    expected: &PackageDigest,
    maximum_bytes: usize,
) -> Result<ReleaseEvidenceUpload, PlatformError> {
    check_maximum(maximum_bytes)?;
    validate_package_json(index_bytes, limits())?;
    let index: PackageEvidenceIndex = serde_json::from_slice(index_bytes)
        .map_err(|_| crate::invalid("invalid-package-evidence-index"))?;
    check_index(&index, expected)?;
    let root = super::open_root(root)?;
    let mut remaining = maximum_bytes;
    let mut read = |entries: &[PackageEvidenceFiles], payload_max| {
        let mut output = Vec::with_capacity(entries.len());
        for files in entries {
            let mut file = |path: &str, cap: usize| -> Result<Vec<u8>, PlatformError> {
                let bytes = super::io::read(&root, path, remaining.min(cap) as u64, limits())?;
                remaining = remaining
                    .checked_sub(bytes.capacity())
                    .ok_or_else(|| crate::exceeded("package-evidence-byte-limit"))?;
                Ok(bytes)
            };
            let manifest = file(&files.manifest, 4096)?;
            let configuration = file(&files.configuration, 2)?;
            if configuration != b"{}" {
                return Err(crate::invalid("invalid-package-evidence-configuration"));
            }
            let payload = file(&files.payload, payload_max)?;
            output.push(AdmissionEvidence {
                manifest,
                configuration,
                payload,
            });
        }
        Ok(output)
    };
    let evidence = ReleaseEvidenceUpload {
        signatures: read(&index.signatures, 4096)?,
        provenance: read(&index.provenance, 49152)?,
        sboms: read(&index.sboms, 1024 * 1024)?,
    };
    check_evidence(&evidence, maximum_bytes)?;
    Ok(evidence)
}

fn check_index(
    index: &PackageEvidenceIndex,
    expected: &PackageDigest,
) -> Result<(), PlatformError> {
    if index.format_version != 1 || index.package_digest != expected.to_string() {
        return Err(crate::invalid("package-evidence-subject-mismatch"));
    }
    let mut paths = BTreeSet::new();
    for entries in [&index.signatures, &index.provenance, &index.sboms] {
        if entries.len() > MAX_ENTRIES || entries.capacity() > MAX_ENTRIES {
            return Err(crate::exceeded("package-evidence-count-limit"));
        }
        for files in entries {
            for path in [&files.manifest, &files.configuration, &files.payload] {
                validate_package_path(path, limits())?;
                if !paths.insert(path) {
                    return Err(crate::invalid("duplicate-package-evidence-path"));
                }
            }
        }
    }
    Ok(())
}

fn check_maximum(maximum: usize) -> Result<(), PlatformError> {
    if maximum == 0 || maximum > MAX_TOTAL {
        return Err(crate::exceeded("package-evidence-byte-limit"));
    }
    Ok(())
}

fn check_evidence(evidence: &ReleaseEvidenceUpload, maximum: usize) -> Result<(), PlatformError> {
    check_maximum(maximum)?;
    let mut remaining = maximum;
    let mut identities = BTreeSet::new();
    for (entries, payload_max) in [
        (&evidence.signatures, 4096),
        (&evidence.provenance, 49152),
        (&evidence.sboms, 1024 * 1024),
    ] {
        if entries.len() > MAX_ENTRIES || entries.capacity() > MAX_ENTRIES {
            return Err(crate::exceeded("package-evidence-count-limit"));
        }
        for entry in entries {
            if entry.manifest.len() > 4096
                || entry.configuration != b"{}"
                || entry.payload.len() > payload_max
            {
                return Err(crate::invalid("invalid-package-evidence-file"));
            }
            if !identities.insert(artifact_blob_digest(&entry.manifest)) {
                return Err(crate::invalid("duplicate-package-evidence-identity"));
            }
            for bytes in [&entry.manifest, &entry.configuration, &entry.payload] {
                remaining = remaining
                    .checked_sub(bytes.capacity())
                    .ok_or_else(|| crate::exceeded("package-evidence-byte-limit"))?;
            }
        }
    }
    Ok(())
}

/// Exports exact evidence into a new sibling directory, publishing index.json
/// last. Existing output is refused; partial output remains identifiable and is
/// never represented as successful or recursively removed by this helper.
pub fn write_package_evidence(
    package: &PackageDigest,
    evidence: &ReleaseEvidenceUpload,
    output: &Path,
    maximum_bytes: usize,
) -> Result<(), PlatformError> {
    check_evidence(evidence, maximum_bytes)?;
    let name = output
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| crate::invalid("invalid-package-evidence-output"))?;
    validate_package_path(name, limits())?;
    let parent = super::open_root(
        output
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new(".")),
    )?;
    parent.create_dir(name).map_err(super::io_error)?;
    let root = parent.open_dir_nofollow(name).map_err(super::io_error)?;
    let write =
        |kind, entries: &[AdmissionEvidence]| -> Result<Vec<PackageEvidenceFiles>, PlatformError> {
            let mut files = Vec::with_capacity(entries.len());
            for (number, entry) in entries.iter().enumerate() {
                let selected = PackageEvidenceFiles {
                    manifest: format!("{kind}/{number}/manifest.json"),
                    configuration: format!("{kind}/{number}/config.json"),
                    payload: format!("{kind}/{number}/payload.json"),
                };
                for (path, bytes) in [
                    (&selected.manifest, &entry.manifest),
                    (&selected.configuration, &entry.configuration),
                    (&selected.payload, &entry.payload),
                ] {
                    super::io::write(&root, path, bytes, limits())?;
                }
                files.push(selected);
            }
            Ok(files)
        };
    let index = PackageEvidenceIndex {
        format_version: 1,
        package_digest: package.to_string(),
        signatures: write("signature", &evidence.signatures)?,
        provenance: write("provenance", &evidence.provenance)?,
        sboms: write("sbom", &evidence.sboms)?,
    };
    let bytes =
        serde_json::to_vec(&index).map_err(|_| crate::invalid("invalid-package-evidence-index"))?;
    validate_package_json(&bytes, limits())?;
    super::io::write(&root, "index.pending", &bytes, limits())?;
    root.rename("index.pending", &root, "index.json")
        .map_err(super::io_error)
}
