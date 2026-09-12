use super::super::{invalid_input, proto};
use crate::{
    args::{Command, ReleaseCommand},
    config::ResolvedConfig,
    error::Failure,
    operation::Operation,
};
use latent_artifacts::ReleaseEvidenceUpload;
use std::path::Path;

pub(in crate::management) fn release(
    command: &Command,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    let Command::Release(command) = command else {
        return Err(invalid_input());
    };
    match command {
        ReleaseCommand::Lifecycle(args) => {
            crate::management::prepare::digest(&args.digest)?;
            Ok(Operation::GetReleaseLifecycle(
                proto::GetReleaseLifecycleRequest {
                    digest: args.digest.clone(),
                },
            ))
        }
        ReleaseCommand::Operation(args) => Ok(Operation::LookupReleaseReceipt(
            proto::GetReleaseOperationRequest {
                operation_id: args.operation_id.clone(),
            },
        )),
        ReleaseCommand::Revoke(args) | ReleaseCommand::Retire(args) => {
            crate::management::prepare::digest(&args.digest)?;
            let revoke = matches!(command, ReleaseCommand::Revoke(_));
            Ok(Operation::ChangeReleaseLifecycle(
                proto::ChangeReleaseLifecycleRequest {
                    digest: args.digest.clone(),
                    action: if revoke {
                        proto::ReleaseLifecycleAction::Revoke
                    } else {
                        proto::ReleaseLifecycleAction::Retire
                    } as i32,
                    operation: Some(proto::ReleaseOperationPrecondition {
                        operation_id: args.operation.operation_id.clone(),
                        expected_generation: Some(args.operation.expected_generation),
                    }),
                    reason: if revoke {
                        proto::ReleaseLifecycleReason::OperatorRevocation
                    } else {
                        proto::ReleaseLifecycleReason::OperatorRetirement
                    } as i32,
                },
            ))
        }
        ReleaseCommand::RenewEvidence(args) => {
            crate::management::prepare::digest(&args.digest)?;
            crate::management::prepare::digest(&args.package_digest)?;
            let package = args.package_digest.parse().map_err(|_| invalid_input())?;
            let evidence =
                crate::package::evidence(&args.evidence, parent(&args.evidence)?, &package)?;
            Ok(Operation::RenewReleaseEvidence(
                proto::RenewReleaseEvidenceRequest {
                    digest: args.digest.clone(),
                    package_digest: args.package_digest.clone(),
                    operation: Some(proto::ReleaseOperationPrecondition {
                        operation_id: args.operation.operation_id.clone(),
                        expected_generation: Some(args.operation.expected_generation),
                    }),
                    evidence: Some(convert_evidence(evidence)),
                },
            ))
        }
        ReleaseCommand::PublishPackage(args) => {
            let package = crate::package::read(&args.directory)?;
            let evidence = args
                .evidence
                .as_ref()
                .map(|path| {
                    crate::package::evidence(path, parent(path)?, package.layout().digest())
                })
                .transpose()?
                .unwrap_or_default();
            // Package inspection is association only. The node authenticates its
            // tenant and checks current policy; no client authority is asserted.
            let input = package.into_input();
            if input
                .layers
                .iter()
                .any(|(_, bytes)| bytes.len() > config.limits.maximum_component_bytes)
            {
                return Err(invalid_input());
            }
            let evidence = convert_evidence(evidence);
            Ok(Operation::PublishRelease(proto::PublishReleaseRequest {
                release: None,
                artifact: None,
                operation: Some(proto::ReleaseOperationPrecondition {
                    operation_id: args.operation_id.clone(),
                    expected_generation: Some(args.expected_generation),
                }),
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
            }))
        }
        _ => Err(invalid_input()),
    }
}
fn parent(path: &Path) -> Result<&Path, Failure> {
    if path == Path::new("-") {
        return Err(invalid_input());
    }
    Ok(path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new(".")))
}
fn convert_evidence(value: ReleaseEvidenceUpload) -> proto::ReleaseEvidenceUpload {
    let convert = |entries: Vec<latent_artifacts::AdmissionEvidence>| {
        entries
            .into_iter()
            .map(|value| proto::PackageAdmissionEvidence {
                manifest: value.manifest,
                configuration: value.configuration,
                payload: value.payload,
            })
            .collect()
    };
    proto::ReleaseEvidenceUpload {
        signatures: convert(value.signatures),
        provenance: convert(value.provenance),
        sboms: convert(value.sboms),
    }
}
