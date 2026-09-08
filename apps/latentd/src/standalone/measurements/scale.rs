use std::time::Instant;

use latent_artifacts::{content_digest, ArtifactRepository, CapsuleArtifact};
use latent_core::{ArtifactReference, ContractId, DeploymentId, FunctionId, ServiceId, TenantId};
use latent_manifest::DeploymentManifest;
use latent_routing::{InvocationTarget, RouteResolver};
use serde_json::{json, Value};

use super::{platform, MeasurementNode, MeasurementPlan, MeasurementWriter, Result};

pub(super) async fn run(
    node: &MeasurementNode,
    plan: &MeasurementPlan,
    writer: &mut MeasurementWriter,
) -> Result<Value> {
    let baseline = node.sample("scale-empty")?;
    dormant(&baseline)?;
    writer.write("scale-baseline", &baseline)?;
    let mut previous = 0_u32;
    let mut route_samples = 0_u64;
    for count in &plan.scale_counts {
        // Exactly one bounded desired-state batch per scale checkpoint avoids
        // timing 100k repeated whole-catalog compilations as a registration test.
        let mut deployments = Vec::with_capacity(usize::try_from(*count - previous)?);
        let started = Instant::now();
        for index in previous..*count {
            let (artifact, deployment) = variant(node, index);
            node.publish_artifact(artifact).await?;
            deployments.push(deployment);
        }
        let publish_elapsed = started.elapsed().as_nanos().to_string();
        let started = Instant::now();
        node.apply_many(deployments).await?;
        let apply_elapsed = started.elapsed().as_nanos().to_string();
        let timings = measure_routes(node, *count, plan.route_samples).await?;
        route_samples += u64::from(plan.route_samples);
        let sample = node.sample(&format!("scale-{count}"))?;
        dormant(&sample)?;
        fixed_topology(&baseline, &sample)?;
        writer.write("scale-checkpoint", &json!({"registered_releases":count.to_string(),"registered_deployments":count.to_string(),
            "publish_elapsed_nanos":publish_elapsed,"apply_elapsed_nanos":apply_elapsed,
            "route_lookup":{"boundary":"directory-deployment-resolver.resolve","unit":"ns",
                "samples":timings,"sample_count":plan.route_samples.to_string()},"sample":sample}))?;
        previous = *count;
    }
    let summary = json!({"registered_releases":previous.to_string(),"registered_deployments":previous.to_string(),
        "checkpoint_count":plan.scale_counts.len().to_string(),"route_samples":route_samples.to_string(),"dormant_topology_constant":true});
    writer.write("scale-summary", &summary)?;
    Ok(summary)
}

fn variant(node: &MeasurementNode, index: u32) -> (CapsuleArtifact, DeploymentManifest) {
    let fixture = &node.fixtures.echo;
    let mut artifact = fixture.artifact.clone();
    append_identity(&mut artifact.component_bytes, index);
    let digest = content_digest(&artifact.component_bytes);
    let service = format!("scale-{index:06}");
    artifact.descriptor.reference = ArtifactReference(format!("local://scale/{index:06}"));
    artifact.descriptor.release_digest = digest.clone();
    artifact.descriptor.size_bytes = u64::try_from(artifact.component_bytes.len()).unwrap();
    artifact.manifest.component_digest = digest.clone();
    artifact.manifest.metadata.name.clone_from(&service);
    let mut deployment = fixture.deployment.clone();
    deployment.id = DeploymentId(service.clone());
    deployment.metadata.name.clone_from(&service);
    deployment.service = ServiceId(service);
    deployment.release = digest;
    (artifact, deployment)
}

fn append_identity(component: &mut Vec<u8>, index: u32) {
    // Component binary custom section 0: short UTF-8 name plus opaque index.
    // It changes content identity while preserving all executable WIT exports.
    const NAME: &[u8] = b"latent.scale.identity.v1";
    component.push(0);
    component.push(u8::try_from(1 + NAME.len() + 4).unwrap());
    component.push(u8::try_from(NAME.len()).unwrap());
    component.extend_from_slice(NAME);
    component.extend_from_slice(&index.to_le_bytes());
}

async fn measure_routes(node: &MeasurementNode, count: u32, samples: u32) -> Result<Vec<String>> {
    let mut result = Vec::with_capacity(usize::try_from(samples)?);
    for sample in 0..samples {
        let index = sample.wrapping_mul(7919) % count;
        let target = InvocationTarget {
            tenant: TenantId(node.fixtures.echo.tenant.clone()),
            service: ServiceId(format!("scale-{index:06}")),
            contract: ContractId(node.fixtures.echo.contract.clone()),
            function: FunctionId("echo".to_owned()),
            route: None,
        };
        node.before_command(false)?;
        let started = Instant::now();
        let resolved = node
            .deployments
            .resolve(&target, Some("measurement-route-key"))
            .map_err(platform)?;
        let elapsed = started.elapsed().as_nanos();
        if resolved.target != target || resolved.route_generation != node.deployments.generation() {
            return Err("scale route association mismatch".into());
        }
        let entry = node
            .artifacts
            .get_catalog_entry(&target.tenant, &resolved.release)
            .await
            .map_err(platform)?
            .ok_or("missing scale release summary")?;
        if entry.service != target.service {
            return Err("scale route release mismatch".into());
        }
        result.push(elapsed.to_string());
    }
    Ok(result)
}

fn dormant(sample: &Value) -> Result<()> {
    let inventory = &sample["inventory"];
    if inventory["queueDepth"] != "0"
        || inventory["cacheSummary"]["entries"] != "0"
        || inventory["cacheSummary"]["preparing"] != "0"
        || sample["backend"]["stores_created"] != "0"
    {
        return Err("dormant catalog created execution resources".into());
    }
    for key in [
        "active_invocations",
        "live_stores",
        "live_host_states",
        "live_component_instances",
        "live_temporary_buffers",
        "live_cancellation_probes",
    ] {
        if sample["backend"][key] != "0" {
            return Err("dormant backend owner remains".into());
        }
    }
    for cell in inventory["cellCapacity"]
        .as_array()
        .ok_or("missing measured cells")?
    {
        if cell["total"] != cell["available"]
            || cell["active"] != 0
            || cell["quarantined"] != 0
            || cell["queueDepth"] != 0
        {
            return Err("dormant cell capacity changed".into());
        }
    }
    if sample["resources"]["descendants"] != json!([]) {
        return Err("unexpected measurement descendants".into());
    }
    for entry in inventory["topology"]["entries"]
        .as_array()
        .ok_or("missing measured topology")?
    {
        if entry["ownership"] == "service-resident"
            && (entry["activeCount"] != "0" || entry["configuredCount"] != "0")
        {
            return Err("service-resident execution resource".into());
        }
    }
    Ok(())
}

fn fixed_topology(first: &Value, last: &Value) -> Result<()> {
    if first["resources"]["identity"] != last["resources"]["identity"] {
        return Err("scale process identity changed".into());
    }
    for key in ["taskCount", "uniqueSocketCount", "listeningTcpSocketCount"] {
        if first["resources"][key] != last["resources"][key] {
            return Err("scale OS topology grew".into());
        }
    }
    for key in ["threadCount", "openFileDescriptors", "socketCount"] {
        if first["resources"]["process"][key] != last["resources"]["process"][key] {
            return Err("scale process resources grew".into());
        }
    }
    if first["inventory"]["topology"] != last["inventory"]["topology"]
        || first["inventory"]["cellCapacity"] != last["inventory"]["cellCapacity"]
    {
        return Err("scale fixed node topology changed".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn variant_identity_is_one_bounded_custom_section() {
        let mut first = b"\0asm\x0d\0\x01\0".to_vec();
        let mut second = first.clone();
        append_identity(&mut first, 1);
        append_identity(&mut second, 2);
        assert_eq!(&first[..8], &second[..8]);
        assert_eq!(first[8], 0);
        assert_eq!(usize::from(first[9]), first.len() - 10);
        assert_eq!(first.len(), second.len());
        assert_ne!(content_digest(&first), content_digest(&second));
    }
}
