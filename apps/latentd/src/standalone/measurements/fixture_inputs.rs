//! Small canonical metadata artifacts bind the actual normalized fixture inputs.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use latent_artifacts::{content_digest, encode_contract_metadata, ContractMetadataLimits};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

use super::{fixtures::Fixtures, platform, MeasurementWriter, Result};

const MAXIMUM_FILE_BYTES: usize = 1024 * 1024;

pub(super) fn write(
    directory: &Path,
    fixtures: &Fixtures,
    writer: &mut MeasurementWriter,
) -> Result<()> {
    std::fs::create_dir(directory.join("fixture-inputs"))?;
    let codec = JsonManifestCodec::default();
    let mut rows = Vec::with_capacity(3);
    for (name, fixture) in [
        ("echo", &fixtures.echo),
        ("generic", &fixtures.generic),
        ("capabilities", &fixtures.capabilities),
    ] {
        let capsule = codec
            .encode_capsule(&fixture.artifact.manifest)
            .map_err(|_| "measurement capsule input encoding")?;
        let contracts = encode_contract_metadata(
            &fixture.artifact.contracts,
            ContractMetadataLimits::default(),
        )
        .map_err(platform)?;
        let deployment = codec
            .encode_deployment(&fixture.deployment)
            .map_err(|_| "measurement deployment input encoding")?;
        rows.push(json!({"name":name,"tenant":fixture.tenant,"service":fixture.service,
            "component_sha256":fixture.release_digest,"component_bytes":fixture.artifact.component_bytes.len().to_string(),
            "capsule":retain(directory,&format!("fixture-inputs/{name}-capsule.json"),&capsule)?,
            "contracts":retain(directory,&format!("fixture-inputs/{name}-contracts.json"),&contracts)?,
            "deployment":retain(directory,&format!("fixture-inputs/{name}-deployment.json"),&deployment)?}));
    }
    writer.write("fixture-inputs", &json!({"fixtures":rows}))?;
    Ok(())
}

pub(super) fn retain(directory: &Path, relative: &str, bytes: &[u8]) -> Result<Value> {
    if bytes.is_empty() || bytes.len() > MAXIMUM_FILE_BYTES {
        return Err("measurement metadata input byte limit".into());
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(directory.join(relative))?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(json!({"path":relative,"sha256":content_digest(bytes).0,"bytes":bytes.len().to_string()}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_artifact_references_match_retained_bytes_and_cannot_overwrite() {
        let directory = tempfile::tempdir().unwrap();
        let bytes = b"{\"synthetic\":true}";
        let reference = retain(directory.path(), "synthetic.json", bytes).unwrap();
        assert_eq!(reference["sha256"], content_digest(bytes).0);
        assert_eq!(reference["bytes"], bytes.len().to_string());
        assert_eq!(
            std::fs::read(directory.path().join("synthetic.json")).unwrap(),
            bytes
        );
        assert!(retain(directory.path(), "synthetic.json", b"different").is_err());
        assert!(retain(directory.path(), "empty.json", b"").is_err());
        assert!(!directory.path().join("empty.json").exists());
    }
}
