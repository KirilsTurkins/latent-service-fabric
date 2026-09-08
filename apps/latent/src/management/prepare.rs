use std::collections::BTreeSet;

use latent_artifacts::{content_digest, decode_contract_metadata, ContractMetadataLimits};
use latent_control_store::VersionedDeployment;
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestLimits, ManifestValidator, Phase1ManifestValidator,
};
use latent_wire::management::{deployment_to_proto, proto};
use serde_json::json;

use crate::args::{
    Command, DeploymentCommand, NodeCommand, PublishArgs, ReleaseCommand, RouteCommand,
    ValidateCommand,
};
use crate::config::ResolvedConfig;
use crate::error::Failure;
use crate::input::{self, MAXIMUM_CONTRACT_BYTES, MAXIMUM_MANIFEST_BYTES};
use crate::operation::Operation;
use crate::output::Outcome;

use super::invalid_manifest;

pub fn prepare(command: &Command, config: &ResolvedConfig) -> Result<Operation, Failure> {
    match command {
        Command::Release(ReleaseCommand::Publish(args)) => publish(args, config),
        Command::Release(ReleaseCommand::Get(args)) => {
            digest(&args.digest)?;
            Ok(Operation::GetRelease(proto::GetReleaseRequest {
                digest: args.digest.clone(),
            }))
        }
        Command::Release(ReleaseCommand::List(args)) => {
            optional_identifier(args.service.as_deref())?;
            Ok(Operation::ListReleases(proto::ListReleasesRequest {
                service: args.service.clone(),
                page: Some(page(args.page_size, args.page_token.as_deref())?),
            }))
        }
        Command::Deployment(DeploymentCommand::Apply(args)) => {
            let bytes = input::read(&args.file, MAXIMUM_MANIFEST_BYTES, "manifest")?;
            let manifest = codec()
                .decode_deployment(&bytes)
                .map_err(|_| invalid_manifest())?;
            Phase1ManifestValidator
                .validate_deployment(&manifest)
                .map_err(|_| invalid_manifest())?;
            tenant(
                manifest
                    .metadata
                    .tenant
                    .as_ref()
                    .map(|value| value.0.as_str()),
                &config.tenant,
            )?;
            let deployment = deployment_to_proto(&VersionedDeployment {
                manifest,
                generation: 0,
            })
            .map_err(|_| invalid_manifest())?;
            Ok(Operation::ApplyDeployment(proto::ApplyDeploymentRequest {
                deployment: Some(deployment),
                expected_generation: args.expected_generation,
            }))
        }
        Command::Deployment(DeploymentCommand::Get(args)) => {
            identifier(&args.id)?;
            Ok(Operation::GetDeployment(proto::GetDeploymentRequest {
                id: args.id.clone(),
            }))
        }
        Command::Deployment(DeploymentCommand::Delete(args)) => {
            identifier(&args.id)?;
            Ok(Operation::DeleteDeployment(
                proto::DeleteDeploymentRequest {
                    id: args.id.clone(),
                    expected_generation: args.expected_generation,
                },
            ))
        }
        Command::Deployment(DeploymentCommand::List(args)) => {
            optional_identifier(args.service.as_deref())?;
            Ok(Operation::ListDeployments(proto::ListDeploymentsRequest {
                service: args.service.clone(),
                page: Some(page(args.page_size, args.page_token.as_deref())?),
            }))
        }
        Command::Route(RouteCommand::Get(args)) => Ok(Operation::GetRouteSnapshot(
            proto::GetRouteSnapshotRequest {
                generation: args.generation,
            },
        )),
        Command::Node(NodeCommand::Get(args)) => {
            identifier(&args.id)?;
            Ok(Operation::GetNode(proto::GetNodeRequest {
                node_id: args.id.clone(),
            }))
        }
        Command::Node(NodeCommand::List(args)) => {
            for value in [&args.trust_class, &args.region, &args.zone] {
                optional_identifier(value.as_deref())?;
            }
            Ok(Operation::ListNodes(proto::ListNodesRequest {
                trust_class: args.trust_class.clone(),
                region: args.region.clone(),
                zone: args.zone.clone(),
                page: Some(page(args.page_size, args.page_token.as_deref())?),
            }))
        }
        _ => Err(Failure::local(
            "invalid-operation",
            "This is not a management operation.",
        )),
    }
}

pub fn validate(command: &ValidateCommand) -> Result<Outcome, Failure> {
    let (kind, bytes) = match command {
        ValidateCommand::Capsule(args) => (
            "Capsule",
            input::read(&args.file, MAXIMUM_MANIFEST_BYTES, "manifest")?,
        ),
        ValidateCommand::Deployment(args) => (
            "Deployment",
            input::read(&args.file, MAXIMUM_MANIFEST_BYTES, "manifest")?,
        ),
    };
    if kind == "Capsule" {
        let manifest = codec()
            .decode_capsule(&bytes)
            .map_err(|_| invalid_manifest())?;
        Phase1ManifestValidator
            .validate_capsule(&manifest)
            .map_err(|_| invalid_manifest())?;
    } else {
        let manifest = codec()
            .decode_deployment(&bytes)
            .map_err(|_| invalid_manifest())?;
        Phase1ManifestValidator
            .validate_deployment(&manifest)
            .map_err(|_| invalid_manifest())?;
    }
    Ok(Outcome::success(json!({"kind":kind,"valid":true})))
}

fn publish(args: &PublishArgs, config: &ResolvedConfig) -> Result<Operation, Failure> {
    input::single_stdin(&[&args.manifest, &args.component, &args.contracts])?;
    let capsule_manifest_json = input::read(&args.manifest, MAXIMUM_MANIFEST_BYTES, "manifest")?;
    let manifest = codec()
        .decode_capsule(&capsule_manifest_json)
        .map_err(|_| invalid_manifest())?;
    Phase1ManifestValidator
        .validate_capsule(&manifest)
        .map_err(|_| invalid_manifest())?;
    tenant(
        manifest
            .metadata
            .tenant
            .as_ref()
            .map(|value| value.0.as_str()),
        &config.tenant,
    )?;
    let contract_metadata_json = input::read(&args.contracts, MAXIMUM_CONTRACT_BYTES, "contracts")?;
    let contracts = decode_contract_metadata(
        &contract_metadata_json,
        ContractMetadataLimits {
            max_document_bytes: MAXIMUM_CONTRACT_BYTES,
            max_string_bytes: 4096,
            max_retained_bytes: 4 * 1024 * 1024,
            ..ContractMetadataLimits::default()
        },
    )
    .map_err(|_| {
        Failure::local(
            "invalid-contract-metadata",
            "The typed contract metadata is invalid.",
        )
    })?;
    let mut ids = BTreeSet::new();
    if contracts.len() > 4096
        || contracts.iter().any(|value| !ids.insert(&value.id))
        || manifest
            .exports
            .iter()
            .any(|export| !ids.contains(&export.contract))
    {
        return Err(Failure::local(
            "invalid-contract-metadata",
            "Every export requires unique typed contract metadata.",
        ));
    }
    let component_bytes = input::read(
        &args.component,
        config.limits.maximum_component_bytes,
        "component",
    )?;
    let component_digest = content_digest(&component_bytes).0;
    if component_bytes.is_empty() || component_digest != manifest.component_digest.0 {
        return Err(Failure::local(
            "component-digest-mismatch",
            "The component bytes do not match the manifest digest.",
        ));
    }
    Ok(Operation::PublishRelease(proto::PublishReleaseRequest {
        release: None,
        artifact: Some(proto::CapsuleArtifactUpload {
            capsule_manifest_json,
            component_bytes,
            component_digest,
            component_media_type: "application/wasm".to_owned(),
            contract_metadata_json,
        }),
    }))
}

pub(super) fn codec() -> JsonManifestCodec {
    JsonManifestCodec::new(ManifestLimits {
        max_document_bytes: MAXIMUM_MANIFEST_BYTES,
        max_string_bytes: 4096,
        ..ManifestLimits::default()
    })
}

fn tenant(actual: Option<&str>, expected: &str) -> Result<(), Failure> {
    if actual == Some(expected) {
        Ok(())
    } else {
        Err(Failure::local(
            "manifest-tenant-mismatch",
            "The manifest tenant must match the selected profile tenant.",
        ))
    }
}

fn identifier(value: &str) -> Result<(), Failure> {
    if value.is_empty() || value.len() > 512 || value.chars().any(char::is_control) {
        Err(Failure::local(
            "invalid-identifier",
            "An identifier is empty, oversized, or contains control characters.",
        ))
    } else {
        Ok(())
    }
}

fn optional_identifier(value: Option<&str>) -> Result<(), Failure> {
    value.map_or(Ok(()), identifier)
}

fn digest(value: &str) -> Result<(), Failure> {
    if super::canonical_digest(value) {
        Ok(())
    } else {
        Err(Failure::local(
            "invalid-release-digest",
            "A canonical SHA-256 release digest is required.",
        ))
    }
}

fn page(page_size: u32, token: Option<&str>) -> Result<proto::PageRequest, Failure> {
    if page_size > 1000
        || token.is_some_and(|value| {
            value.is_empty() || value.len() > 8192 || value.chars().any(char::is_control)
        })
    {
        return Err(Failure::local(
            "invalid-page-request",
            "The page size or continuation token is invalid.",
        ));
    }
    Ok(proto::PageRequest {
        page_size,
        page_token: token.map(str::to_owned),
    })
}
