use std::path::Path;

use latent_artifacts::content_digest;
use latent_core::{ArtifactReference, DeploymentId, ServiceId};
use serde_json::{json, Value};

use super::super::{evidence, node::Node};
use super::{Fixture, Result};

pub(in crate::standalone::measurements::comparison) fn variants(
    base: &Fixture,
) -> Result<Vec<Fixture>> {
    let mut result = Vec::with_capacity(8);
    for index in 0_u8..8 {
        let service = format!("cold-key-{index}");
        let mut artifact = base.artifact.clone();
        if index != 0 {
            // One valid custom section with empty name and one inert byte.
            artifact
                .component_bytes
                .extend_from_slice(&[0, 2, 0, index]);
        }
        let digest = content_digest(&artifact.component_bytes);
        artifact.descriptor.release_digest = digest.clone();
        artifact.descriptor.size_bytes = u64::try_from(artifact.component_bytes.len())?;
        artifact.descriptor.reference = ArtifactReference(format!("memory:cold-fixture/{index}"));
        artifact.manifest.component_digest = digest.clone();
        artifact.manifest.metadata.name.clone_from(&service);
        artifact
            .manifest
            .execution
            .resource_budget_ceiling
            .memory_bytes = 16_777_216;
        let mut deployment = base.deployment.clone();
        deployment.id = DeploymentId(service.clone());
        deployment.metadata.name.clone_from(&service);
        deployment.service = ServiceId(service.clone());
        deployment.release = digest.clone();
        deployment.resources.memory_bytes = 16_777_216;
        let mut target = base.target.clone();
        target.service.clone_from(&service);
        result.push(Fixture {
            artifact,
            deployment,
            tenant: base.tenant.clone(),
            service,
            contract: base.contract.clone(),
            release_digest: digest.0,
            target,
        });
    }
    Ok(result)
}

pub(in crate::standalone::measurements::comparison) async fn publish(
    node: &mut Node,
    fixtures: Vec<Fixture>,
    directory: &Path,
) -> Result<Vec<Value>> {
    let mut rows = Vec::with_capacity(8);
    for (index, fixture) in fixtures.into_iter().enumerate() {
        node.fixture = fixture;
        let publication = node.publish().await?;
        let published = node.published().await?;
        let relative = format!("fixtures/key-{index}");
        let target = directory.join(&relative);
        std::fs::create_dir_all(&target)?;
        let artifact = evidence::artifact(&target, &node.fixture, &published)?;
        let component = super::super::super::fixture_inputs::retain(
            &target,
            "echo-component.wasm",
            &published.component_bytes,
        )?;
        rows.push(
            json!({"key":index.to_string(),"directory":relative,"artifact":artifact,
            "component":component,"publication":publication,"target":{"tenant":node.fixture.tenant,
            "service":node.fixture.service,"contract":node.fixture.contract,"function":"echo"}}),
        );
    }
    Ok(rows)
}
