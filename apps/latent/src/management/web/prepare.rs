use super::{invalid_input, proto, WebOperation};
use crate::{
    args::{release::PublishPackageArgs, web::WebCommand},
    config::ResolvedConfig,
    error::Failure,
    management::phase2::prepare::{convert_evidence, parent},
    operation::Operation,
};

pub fn prepare(command: &WebCommand, config: &ResolvedConfig) -> Result<Operation, Failure> {
    command.validate()?;
    let selected = |id: &String| {
        Some(proto::PublicationRef {
            id: id.clone(),
            tenant: config.tenant.clone(),
        })
    };
    let precondition = |operation: &crate::args::release::ReleaseMutation| {
        Some(proto::ReleaseOperationPrecondition {
            operation_id: operation.operation_id.clone(),
            expected_generation: Some(operation.expected_generation),
        })
    };
    let operation = match command {
        WebCommand::Publish(arguments) => publish(arguments, config)?,
        WebCommand::Get { publication } => WebOperation::Get(proto::GetWebPublicationRequest {
            publication: selected(publication),
        }),
        WebCommand::Prepare {
            publication,
            lifecycle_generation,
            maximum_wait_ms,
        } => WebOperation::Prepare(proto::PrepareWebPublicationRequest {
            publication: selected(publication),
            lifecycle_generation: *lifecycle_generation,
            maximum_wait_millis: *maximum_wait_ms,
        }),
        WebCommand::Operation { operation_id } => {
            WebOperation::Operation(proto::GetWebOperationRequest {
                operation_id: operation_id.clone(),
            })
        }
        WebCommand::Revoke {
            publication,
            operation,
        }
        | WebCommand::Retire {
            publication,
            operation,
        } => {
            let revoke = matches!(command, WebCommand::Revoke { .. });
            WebOperation::Change(proto::ChangeWebLifecycleRequest {
                publication: selected(publication),
                operation: precondition(operation),
                action: if revoke {
                    proto::ReleaseLifecycleAction::Revoke
                } else {
                    proto::ReleaseLifecycleAction::Retire
                } as i32,
                reason: if revoke {
                    proto::ReleaseLifecycleReason::OperatorRevocation
                } else {
                    proto::ReleaseLifecycleReason::OperatorRetirement
                } as i32,
            })
        }
        WebCommand::RenewEvidence {
            publication,
            package_digest,
            evidence,
            operation,
        } => {
            let package = package_digest.parse().map_err(|_| invalid_input())?;
            if super::publication(&package, &config.tenant)?.id != *publication {
                return Err(invalid_input());
            }
            let evidence = crate::package::evidence(evidence, parent(evidence)?, &package)?;
            WebOperation::Renew(proto::RenewWebEvidenceRequest {
                publication: selected(publication),
                evidence: Some(convert_evidence(evidence)),
                operation: precondition(operation),
            })
        }
    };
    Ok(Operation::Web(Box::new(operation)))
}

fn publish(
    arguments: &PublishPackageArgs,
    config: &ResolvedConfig,
) -> Result<WebOperation, Failure> {
    let package = crate::package::read(&arguments.directory)?;
    latent_packaging::inspect_web_bundle(&package, crate::package::limits().semantics)
        .map_err(crate::package::failure)?;
    let evidence = arguments
        .evidence
        .as_ref()
        .map(|path| crate::package::evidence(path, parent(path)?, package.layout().digest()))
        .transpose()?
        .unwrap_or_default();
    let input = package.into_input();
    if input
        .layers
        .iter()
        .any(|(_, bytes)| bytes.len() > config.limits.maximum_component_bytes)
    {
        return Err(invalid_input());
    }
    let evidence = convert_evidence(evidence);
    Ok(WebOperation::Publish(proto::PublishWebPackageRequest {
        package: Some(proto::PackageAdmissionUpload {
            manifest: input.manifest,
            configuration: input.configuration,
            layers: input
                .layers
                .into_iter()
                .map(|(path, data)| proto::PackageAdmissionLayer { path, data })
                .collect(),
            signatures: evidence.signatures,
            provenance: evidence.provenance,
            sboms: evidence.sboms,
        }),
        operation: Some(proto::ReleaseOperationPrecondition {
            operation_id: arguments.operation_id.clone(),
            expected_generation: Some(arguments.expected_generation),
        }),
    }))
}
