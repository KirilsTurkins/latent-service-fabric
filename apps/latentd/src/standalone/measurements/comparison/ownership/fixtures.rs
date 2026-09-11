use std::path::Path;

use latent_artifacts::{
    content_digest, decode_contract_metadata, ArtifactDescriptor, CapsuleArtifact,
    ContractMetadataLimits,
};
use latent_core::{ArtifactReference, Metadata};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{
    context::Context,
    files::{self, Reference},
    Result,
};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Artifact {
    pub id: String,
    pub component: Reference,
    pub capsule: Reference,
    pub contracts: Reference,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Payload {
    pub shape: String,
    pub artifact: Reference,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ContextFile {
    pub shape: String,
    pub artifact: Reference,
    pub charge: Value,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Manifest {
    pub schema: String,
    pub artifacts: Vec<Artifact>,
    pub payloads: Vec<Payload>,
    pub contexts: Vec<ContextFile>,
    pub generation: Reference,
}

impl Manifest {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.ownership-fixtures.v1"
            || !self.artifacts.iter().map(|v| v.id.as_str()).eq([
                "optimization",
                "capabilities",
                "generic",
            ])
            || !self
                .payloads
                .iter()
                .map(|v| v.shape.as_str())
                .eq(super::plan::SHAPES[..3].iter().copied())
            || !self
                .contexts
                .iter()
                .map(|v| v.shape.as_str())
                .eq(super::plan::SHAPES[3..].iter().copied())
        {
            return Err("ownership fixture manifest population".into());
        }
        Ok(())
    }
    pub fn payload(&self, root: &Path, shape: &str) -> Result<Vec<u8>> {
        let row = self
            .payloads
            .iter()
            .find(|v| v.shape == shape)
            .ok_or("ownership payload missing")?;
        let bytes = files::load(root, &row.artifact, 131_072)?;
        let input: Vec<String> = serde_json::from_slice(&bytes)?;
        let expected = match shape {
            "warm-echo" => "optimization-reference-v1".into(),
            "payload-64k" => "x".repeat(65_536),
            "payload-near-limit" => "x".repeat(122_880),
            _ => return Err("ownership payload shape".into()),
        };
        if input != [expected] || serde_json::to_vec(&input)? != bytes {
            return Err("ownership payload content".into());
        }
        Ok(bytes)
    }
    pub fn context(&self, root: &Path, shape: &str) -> Result<(Context, &Value)> {
        let row = self
            .contexts
            .iter()
            .find(|v| v.shape == shape)
            .ok_or("ownership context missing")?;
        let value: Context =
            serde_json::from_slice(&files::load(root, &row.artifact, 1024 * 1024)?)?;
        value.validate(shape)?;
        Ok((value, &row.charge))
    }
}

impl Artifact {
    pub fn load(&self, root: &Path) -> Result<CapsuleArtifact> {
        let bytes = files::load(root, &self.component, 16 * 1024 * 1024)?;
        let manifest = JsonManifestCodec::default()
            .decode_capsule(&files::load(root, &self.capsule, 1024 * 1024)?)
            .map_err(|_| "ownership capsule invalid")?;
        let digest = content_digest(&bytes);
        if manifest.component_digest != digest {
            return Err("ownership capsule component binding".into());
        }
        let contracts = decode_contract_metadata(
            &files::load(root, &self.contracts, 1024 * 1024)?,
            ContractMetadataLimits::default(),
        )
        .map_err(super::platform)?;
        Ok(CapsuleArtifact {
            descriptor: ArtifactDescriptor {
                reference: ArtifactReference(format!("local://ownership/{}", self.id)),
                release_digest: digest,
                media_type: "application/vnd.wasm.component.v1+wasm".into(),
                size_bytes: u64::try_from(bytes.len())?,
                publisher: None,
                layers: Vec::new(),
                annotations: Metadata::new(),
            },
            manifest,
            contracts,
            component_bytes: bytes,
        })
    }
}
