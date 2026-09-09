use latent_artifacts::encode_contract_metadata;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::Path;

use super::{
    files::{self, Reference},
    fixtures::{Artifact, ContextFile, Manifest, Payload},
    Result,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ComponentInput {
    id: String,
    component: Reference,
    contracts: Option<Reference>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    schema: String,
    components: Vec<ComponentInput>,
    payloads: Vec<Payload>,
}

pub(super) struct Generated {
    pub artifacts: Vec<Artifact>,
    pub payloads: Vec<Payload>,
    pub contexts: Vec<ContextFile>,
}

pub(super) fn bootstrap(root: &Path, directory: &Path, bytes: &[u8]) -> Result<Generated> {
    use super::super::super::fixtures as shared;
    let input: Input = serde_json::from_slice(bytes)?;
    if input.schema != "latent.optimization.ownership-fixture-input.v1"
        || !input.components.iter().map(|v| v.id.as_str()).eq([
            "optimization",
            "capabilities",
            "generic",
        ])
        || !input
            .payloads
            .iter()
            .map(|v| v.shape.as_str())
            .eq(super::plan::SHAPES[..3].iter().copied())
    {
        return Err("ownership bootstrap population".into());
    }
    let mut artifacts = Vec::new();
    for component in input.components {
        let mut capsule: Value = serde_json::from_slice(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/echo-contract/capsule.json"
        )))?;
        let (tenant, service, contract, world, imports, contracts) = match component.id.as_str() {
            "optimization" => (
                "optimization",
                "optimization/workloads",
                "optimization:benchmark/workloads@0.1.0",
                "optimization:benchmark/service@0.1.0",
                Vec::<&str>::new(),
                files::load(
                    root,
                    component
                        .contracts
                        .as_ref()
                        .ok_or("optimization contracts missing")?,
                    1024 * 1024,
                )?,
            ),
            "capabilities" => {
                if component.contracts.is_some() {
                    return Err("unexpected capabilities contracts input".into());
                }
                (
                    "tests",
                    "measurement-capabilities",
                    "tests:capabilities/api@0.1.0",
                    "tests:capabilities/service@0.1.0",
                    vec![
                        "latent:context/context@0.1.0",
                        "latent:log/log@0.1.0",
                        "latent:clock/monotonic@0.1.0",
                        "latent:clock/wall@0.1.0",
                    ],
                    shared::capabilities::capabilities(),
                )
            }
            "generic" => {
                if component.contracts.is_some() {
                    return Err("unexpected generic contracts input".into());
                }
                (
                    "tests",
                    "measurement-generic",
                    "tests:generic/values@0.1.0",
                    "tests:generic/service@0.1.0",
                    Vec::new(),
                    shared::generic::contracts(),
                )
            }
            _ => return Err("unknown ownership component".into()),
        };
        capsule["component"]["world"] = json!(world);
        capsule["exports"] = if component.id == "generic" {
            json!([contract, "tests:generic/alternate@0.1.0"])
        } else {
            json!([contract])
        };
        capsule["imports"] = json!(imports
            .iter()
            .map(|id| json!({"contract":id,"optional":false}))
            .collect::<Vec<_>>());
        let fixture = shared::build(
            tenant,
            service,
            contract,
            files::load(root, &component.component, 16 * 1024 * 1024)?,
            capsule,
            &contracts,
        )?;
        let codec = JsonManifestCodec::default();
        let capsule = codec
            .encode_capsule(&fixture.artifact.manifest)
            .map_err(|_| "ownership capsule encoding")?;
        let contracts = encode_contract_metadata(
            &fixture.artifact.contracts,
            latent_artifacts::ContractMetadataLimits::default(),
        )
        .map_err(super::platform)?;
        artifacts.push(Artifact {
            id: component.id.clone(),
            component: component.component,
            capsule: files::retain(
                root,
                &directory.join(format!("{}-capsule.json", component.id)),
                &capsule,
            )?,
            contracts: files::retain(
                root,
                &directory.join(format!("{}-contracts.json", component.id)),
                &contracts,
            )?,
        });
    }
    Ok(Generated {
        artifacts,
        payloads: input.payloads,
        contexts: Vec::new(),
    })
}

impl Generated {
    pub fn finish(self, root: &Path, receipt: Reference) -> Result<()> {
        let manifest = Manifest {
            schema: "latent.optimization.ownership-fixtures.v1".into(),
            artifacts: self.artifacts,
            payloads: self.payloads,
            contexts: self.contexts,
            generation: receipt,
        };
        manifest.validate()?;
        files::retain(
            root,
            &root.join("ownership-fixtures.json"),
            &serde_json::to_vec(&manifest)?,
        )?;
        Ok(())
    }
}
