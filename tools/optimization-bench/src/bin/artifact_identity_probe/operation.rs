use std::hint::black_box;
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_artifacts::{content_digest, ArtifactRepository, DirectoryArtifactRepository};
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{ContractId, DeploymentId, FunctionId, ReleaseDigest, ServiceId, TenantId};
use latent_routing::{InvocationTarget, RouteResolver, RouteSnapshotSource};
use serde_json::{json, Value};

use super::args::{MeasureArgs, Operation};
use super::fixture;
use super::io::{emit, immediate, read};
use super::model::{self, Fixture, HOLD_MILLIS, MAX_COMPONENT};
use super::Result;

enum Owned {
    Hash {
        bytes: Vec<u8>,
        digest: ReleaseDigest,
    },
    Artifact(DirectoryArtifactRepository),
    Catalog {
        artifacts: Arc<DirectoryArtifactRepository>,
        catalog: DirectoryDeploymentRepository,
    },
}

pub(super) fn measure(args: &MeasureArgs) -> Result<()> {
    validate_iterations(args.operation, args.iterations)?;
    let fixture = fixture::load(&args.fixture)?;
    // Hash input I/O is deliberately outside the byte-slice operation timer.
    // Catalog cases do not preload component bytes or open either repository.
    let bytes = if args.operation == Operation::Hash {
        let bytes = read(&args.fixture.join("component.wasm"), MAX_COMPONENT)?;
        if bytes.len().to_string() != fixture.component_bytes {
            return Err("input-length-mismatch");
        }
        Some(bytes)
    } else {
        None
    };
    let mut ready = identity(args, &fixture);
    ready["schema"] = json!("latent.artifact-identity.ready.v1");
    ready["event"] = json!("ready");
    ready["observation_hold_millis"] = json!(HOLD_MILLIS);
    emit(&ready)?;
    let start = Instant::now();
    let owner = perform(args, bytes);
    let elapsed = start.elapsed().as_nanos().to_string();
    // Metadata/count/routing oracles are outside the operation timer, while
    // owners remain alive for the parent's completion-time resource sample.
    let observations = match &owner {
        Ok(owner) => verify(owner, &fixture),
        Err(code) => Err(*code),
    };
    let mut result = identity(args, &fixture);
    result["schema"] = json!("latent.artifact-identity.result.v1");
    result["event"] = json!("measurement-complete");
    result["elapsed_nanos"] = json!(elapsed);
    for name in [
        "release_count",
        "deployment_count",
        "route_count",
        "route_generation",
        "revision_id",
    ] {
        result[name] = Value::Null;
    }
    match &observations {
        Ok(fields) => {
            result["outcome"] = json!("passed");
            result["code"] = Value::Null;
            for (key, value) in fields.as_object().ok_or("observation-shape")? {
                result[key] = value.clone();
            }
        }
        Err(code) => {
            result["outcome"] = json!("failed");
            result["code"] = json!(code);
        }
    }
    emit(&result)?;
    std::thread::sleep(Duration::from_millis(HOLD_MILLIS));
    black_box(&owner);
    observations.map(|_| ())
}

fn identity(args: &MeasureArgs, fixture: &Fixture) -> Value {
    json!({
        "operation": args.operation.label(), "boundary": args.operation.boundary(),
        "process_id": std::process::id(), "size": fixture.size,
        "component_digest": fixture.component_digest, "component_bytes": fixture.component_bytes,
        "operation_count": args.iterations.to_string(),
    })
}

pub(super) fn validate_iterations(operation: Operation, iterations: u32) -> Result<()> {
    if !(1..=4096).contains(&iterations) || (operation != Operation::Hash && iterations != 1) {
        return Err("operation-count-invalid");
    }
    Ok(())
}

fn perform(args: &MeasureArgs, bytes: Option<Vec<u8>>) -> Result<Owned> {
    match args.operation {
        Operation::Hash => {
            let bytes = bytes.ok_or("hash-input-missing")?;
            let mut digest = ReleaseDigest(String::new());
            for _ in 0..args.iterations {
                digest = black_box(content_digest(black_box(bytes.as_slice())));
            }
            Ok(Owned::Hash { bytes, digest })
        }
        Operation::ArtifactOpen => DirectoryArtifactRepository::open(
            args.fixture.join("artifacts"),
            model::artifact_config(),
        )
        .map(Owned::Artifact)
        .map_err(|error| error.code.wire_code()),
        Operation::CatalogOpen => {
            let artifacts = Arc::new(
                DirectoryArtifactRepository::open(
                    args.fixture.join("artifacts"),
                    model::artifact_config(),
                )
                .map_err(|error| error.code.wire_code())?,
            );
            let repository: Arc<dyn ArtifactRepository> = artifacts.clone();
            let catalog = immediate(DirectoryDeploymentRepository::open(
                args.fixture.join("deployments"),
                repository,
                model::deployment_config(),
            ))?
            .map_err(|error| error.code.wire_code())?;
            Ok(Owned::Catalog { artifacts, catalog })
        }
    }
}

fn verify(owner: &Owned, fixture: &Fixture) -> Result<Value> {
    match owner {
        Owned::Hash { bytes, digest } => {
            if digest.0 != fixture.component_digest
                || bytes.len().to_string() != fixture.component_bytes
            {
                return Err("hash-mismatch");
            }
            Ok(json!({}))
        }
        Owned::Artifact(artifacts) => {
            verify_artifacts(artifacts, fixture)?;
            Ok(json!({"release_count": "1"}))
        }
        Owned::Catalog { artifacts, catalog } => {
            verify_artifacts(artifacts, fixture)?;
            verify_catalog(catalog, fixture)
        }
    }
}

fn verify_artifacts(artifacts: &DirectoryArtifactRepository, fixture: &Fixture) -> Result<()> {
    let page = immediate(artifacts.list(None, 2))?.map_err(|error| error.code.wire_code())?;
    if page.next_after.is_some()
        || page.entries.len() != 1
        || page.entries[0].release_digest.0 != fixture.component_digest
        || page.entries[0].size_bytes.to_string() != fixture.component_bytes
    {
        return Err("release-recovery-mismatch");
    }
    Ok(())
}

fn verify_catalog(catalog: &DirectoryDeploymentRepository, fixture: &Fixture) -> Result<Value> {
    let tenant = TenantId(fixture.tenant.clone());
    let id = DeploymentId(fixture.deployment_id.clone());
    let deployment = immediate(catalog.get_versioned(&tenant, &id))?
        .map_err(|error| error.code.wire_code())?
        .ok_or("deployment-missing")?;
    let all = immediate(catalog.list())?.map_err(|error| error.code.wire_code())?;
    let snapshot = immediate(catalog.current())?.map_err(|error| error.code.wire_code())?;
    if all.len() != 1
        || deployment.generation != 1
        || deployment.manifest.release.0 != fixture.component_digest
        || snapshot.services.len() != 2
        || snapshot.generation.0.to_string() != fixture.route_generation
        || !snapshot.bindings.is_empty()
        || !snapshot.policy_digests.is_empty()
    {
        return Err("catalog-recovery-mismatch");
    }
    let resolver = catalog.pin().map_err(|error| error.code.wire_code())?;
    for route in [None, Some(fixture.deployment_id.clone())] {
        let target = InvocationTarget {
            tenant: tenant.clone(),
            service: ServiceId(fixture.service.clone()),
            contract: ContractId(fixture.contract.clone()),
            function: FunctionId(fixture.function.clone()),
            route,
        };
        let resolved = resolver
            .resolve(&target, Some("identity-probe"))
            .map_err(|error| error.code.wire_code())?;
        if resolved.release.0 != fixture.component_digest
            || resolved.revision.0 != fixture.revision_id
            || resolved.route_generation.0.to_string() != fixture.route_generation
        {
            return Err("resolved-identity-mismatch");
        }
    }
    if snapshot.services.iter().any(|row| {
        row.tenant != tenant
            || row.service.0 != fixture.service
            || row.revisions.len() != 1
            || row.revisions[0].release.0 != fixture.component_digest
            || row.revisions[0].revision.0 != fixture.revision_id
    }) {
        return Err("route-membership-mismatch");
    }
    Ok(
        json!({"release_count": "1", "deployment_count": "1", "route_count": "2",
        "route_generation": fixture.route_generation, "revision_id": fixture.revision_id}),
    )
}
