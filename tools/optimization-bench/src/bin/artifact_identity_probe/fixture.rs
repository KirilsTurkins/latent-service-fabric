mod padding;

use std::fs;
use std::sync::Arc;

use latent_artifacts::{
    content_digest, decode_contract_metadata, encode_contract_metadata, ArtifactDescriptor,
    ArtifactRepository, CapsuleArtifact, ContractMetadataLimits, DirectoryArtifactRepository,
};
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{ArtifactReference, CapabilityId, DeploymentId, Metadata, PolicyId, ServiceId};
use latent_manifest::{
    AvailabilityPolicy, CapabilityGrantSpec, CapsuleManifest, DeploymentManifest,
    JsonManifestCodec, ManifestCodec, ManifestValidator, ObjectMetadata, Phase1ManifestValidator,
    PlacementPolicy,
};
use latent_routing::{InvocationTarget, RouteResolver};

use super::args::FixtureArgs;
use super::io::{emit, immediate, read, write};
use super::model::{self, Fixture, MAX_COMPONENT, MAX_DOCUMENT};
use super::Result;

pub(super) fn generate(args: &FixtureArgs) -> Result<()> {
    let source = read(&args.component, 16 * 1024 * 1024)?;
    padding::validate(&source)?;
    let source_digest = content_digest(&source).0;
    let source_bytes = source.len().to_string();
    let codec = JsonManifestCodec::default();
    let mut capsule = codec
        .decode_capsule(&read(&args.capsule, MAX_DOCUMENT)?)
        .map_err(|_| "capsule-decode")?;
    if capsule.component_digest.0 != source_digest {
        return Err("source-capsule-digest-mismatch");
    }
    let contracts =
        decode_contract_metadata(&read(&args.contracts, MAX_DOCUMENT)?, contract_limits())
            .map_err(|_| "contracts-decode")?;
    let (contract, function) = exported_function(&capsule, &contracts)?;
    let component = padding::pad(source, args.size.target())?;
    padding::validate(&component)?;
    let digest = content_digest(&component);
    capsule.component_digest = digest.clone();
    Phase1ManifestValidator::new()
        .validate_capsule(&capsule)
        .map_err(|_| "capsule-invalid")?;
    let deployment = deployment(&capsule)?;
    Phase1ManifestValidator::new()
        .validate_deployment_against_capsule(&deployment, &capsule)
        .map_err(|_| "deployment-invalid")?;
    let capsule_bytes = codec
        .encode_capsule(&capsule)
        .map_err(|_| "capsule-encode")?;
    let contracts_bytes =
        encode_contract_metadata(&contracts, contract_limits()).map_err(|_| "contracts-encode")?;
    let deployment_bytes = codec
        .encode_deployment(&deployment)
        .map_err(|_| "deployment-encode")?;
    fs::create_dir(&args.output).map_err(|_| "fixture-create")?;
    for (name, bytes) in [
        ("component.wasm", component.as_slice()),
        ("capsule.json", &capsule_bytes),
        ("contracts.json", &contracts_bytes),
        ("deployment.json", &deployment_bytes),
    ] {
        write(&args.output.join(name), bytes)?;
    }
    let mut fixture = Fixture {
        schema: model::FIXTURE_SCHEMA.to_owned(),
        size: args.size.label().to_owned(),
        component_digest: digest.0.clone(),
        component_bytes: component.len().to_string(),
        source_component_digest: source_digest,
        source_component_bytes: source_bytes,
        capsule_sha256: content_digest(&capsule_bytes).0,
        contracts_sha256: content_digest(&contracts_bytes).0,
        deployment_sha256: content_digest(&deployment_bytes).0,
        tenant: deployment
            .metadata
            .tenant
            .as_ref()
            .ok_or("tenant-required")?
            .0
            .clone(),
        service: deployment.service.0.clone(),
        deployment_id: deployment.id.0.clone(),
        contract: contract.0.clone(),
        function: function.0.clone(),
        revision_id: String::new(),
        route_generation: String::new(),
        configuration: model::configuration(),
    };
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local:release:{}", digest.0)),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: component.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: capsule,
        contracts,
        component_bytes: component,
    };
    publish(args, artifact, deployment, &mut fixture)?;
    let encoded = serde_json::to_vec(&fixture).map_err(|_| "fixture-encode")?;
    write(&args.output.join("fixture.json"), &encoded)?;
    emit(&fixture)
}

fn exported_function(
    capsule: &CapsuleManifest,
    contracts: &[latent_artifacts::ContractDescriptor],
) -> Result<(latent_core::ContractId, latent_core::FunctionId)> {
    contracts
        .iter()
        .filter(|contract| {
            capsule
                .exports
                .iter()
                .any(|export| export.contract == contract.id)
        })
        .find_map(|contract| {
            contract.interfaces.iter().find_map(|interface| {
                interface
                    .functions
                    .first()
                    .map(|function| (contract.id.clone(), function.id.clone()))
            })
        })
        .ok_or("no-callable-export")
}

fn publish(
    args: &FixtureArgs,
    artifact: CapsuleArtifact,
    deployment: DeploymentManifest,
    fixture: &mut Fixture,
) -> Result<()> {
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open(args.output.join("artifacts"), model::artifact_config())
            .map_err(|error| error.code.wire_code())?,
    );
    immediate(artifacts.publish(artifact))?.map_err(|error| error.code.wire_code())?;
    let catalog = immediate(DirectoryDeploymentRepository::open(
        args.output.join("deployments"),
        artifacts,
        model::deployment_config(),
    ))?
    .map_err(|error| error.code.wire_code())?;
    immediate(catalog.apply(deployment))?.map_err(|error| error.code.wire_code())?;
    let target = InvocationTarget {
        tenant: latent_core::TenantId(fixture.tenant.clone()),
        service: ServiceId(fixture.service.clone()),
        contract: latent_core::ContractId(fixture.contract.clone()),
        function: latent_core::FunctionId(fixture.function.clone()),
        route: None,
    };
    let resolved = catalog
        .pin()
        .map_err(|error| error.code.wire_code())?
        .resolve(&target, Some("identity-probe"))
        .map_err(|error| error.code.wire_code())?;
    fixture.revision_id = resolved.revision.0;
    fixture.route_generation = resolved.route_generation.0.to_string();
    Ok(())
}

fn contract_limits() -> ContractMetadataLimits {
    ContractMetadataLimits {
        max_document_bytes: MAX_DOCUMENT,
        ..ContractMetadataLimits::default()
    }
}

fn deployment(capsule: &CapsuleManifest) -> Result<DeploymentManifest> {
    if capsule.metadata.tenant.is_none() {
        return Err("tenant-required");
    }
    Ok(DeploymentManifest {
        api_version: capsule.api_version.clone(),
        id: DeploymentId("artifact-identity-probe".to_owned()),
        metadata: ObjectMetadata {
            name: "artifact-identity-probe".to_owned(),
            tenant: capsule.metadata.tenant.clone(),
            namespace: None,
            labels: Metadata::new(),
            annotations: Metadata::new(),
        },
        service: ServiceId(capsule.metadata.name.clone()),
        release: capsule.component_digest.clone(),
        route_weight: 1,
        grants: capsule
            .imports
            .iter()
            .filter(|import| !import.optional)
            .map(|import| {
                CapabilityGrantSpec::new(
                    CapabilityId(import.contract.0.clone()),
                    PolicyId("artifact-identity-probe".to_owned()),
                )
            })
            .collect(),
        resources: capsule.execution.resource_budget_ceiling.clone(),
        availability: AvailabilityPolicy {
            minimum_cached_copies: 1,
            minimum_zones: 1,
        },
        placement: PlacementPolicy {
            trust_class: "local".to_owned(),
            architectures: vec!["x86_64".to_owned()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        },
    })
}

pub(super) fn load(root: &std::path::Path) -> Result<Fixture> {
    let fixture: Fixture = serde_json::from_slice(&read(&root.join("fixture.json"), 16 * 1024)?)
        .map_err(|_| "fixture-decode")?;
    let length: usize = fixture
        .component_bytes
        .parse()
        .map_err(|_| "fixture-size")?;
    if fixture.schema != model::FIXTURE_SCHEMA
        || fixture.configuration != model::configuration()
        || length == 0
        || length > MAX_COMPONENT
        || length.to_string() != fixture.component_bytes
        || !matches!(fixture.size.as_str(), "small" | "16m" | "64m")
        || (fixture.size == "16m" && length != 16 * 1024 * 1024)
        || (fixture.size == "64m" && length != MAX_COMPONENT)
        || (fixture.size == "small" && length > 16 * 1024 * 1024)
        || fixture.route_generation != "1"
        || [
            &fixture.tenant,
            &fixture.service,
            &fixture.deployment_id,
            &fixture.contract,
            &fixture.function,
            &fixture.revision_id,
        ]
        .iter()
        .any(|value| value.is_empty() || value.len() > 512 || value.chars().any(char::is_control))
        || !canonical_digest(&fixture.component_digest)
    {
        return Err("fixture-invalid");
    }
    Ok(fixture)
}

fn canonical_digest(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}
