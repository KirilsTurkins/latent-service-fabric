use super::super::{invalid_input, proto};
use crate::{
    args::rollout::{ChangeArgs, RolloutCommand as R},
    config::ResolvedConfig,
    error::Failure,
    input,
    operation::Operation,
};
use latent_control_store::VersionedDeployment;
use latent_manifest::{ManifestCodec, ManifestValidator, Phase1ManifestValidator};

pub(in crate::management) fn rollout(
    command: &R,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    use proto::change_rollout_request::Command as C;
    Ok(match command {
        R::Start(args) => start(args, config)?,
        R::Get(args) => Operation::GetRollout(proto::GetRolloutRequest {
            id: args.id.clone(),
        }),
        R::List(args) => Operation::ListRollouts(proto::ListRolloutsRequest {
            service: args.service.clone(),
            state: args
                .state
                .as_ref()
                .map(|state| {
                    proto::RolloutState::from_str_name(&format!(
                        "ROLLOUT_STATE_{}",
                        state.replace('-', "_").to_ascii_uppercase()
                    ))
                    .map(|state| state as i32)
                    .ok_or_else(invalid_input)
                })
                .transpose()?,
            page: Some(crate::management::prepare::page(
                args.page_size,
                args.page_token.as_deref(),
            )?),
        }),
        R::Operation(args) => Operation::LookupRolloutReceipt(proto::GetRolloutOperationRequest {
            id: args.id.clone(),
            operation_id: args.operation_id.clone(),
        }),
        R::Evaluate(args) => Operation::EvaluateRollout(proto::EvaluateRolloutRequest {
            id: args.id.clone(),
            expected_revision: Some(args.expected_revision),
        }),
        R::Advance(args) => change(
            &args.change,
            C::Advance(proto::AdvanceRollout {
                next_step: args.next_step,
            }),
        ),
        R::Promote(args) => change(
            &args.change,
            C::Promote(proto::PromoteRollout {
                next_step: args.next_step,
            }),
        ),
        R::Rollback(args) => change(
            &args.change,
            C::Rollback(proto::RollbackRollout {
                target_generation: args.target_generation,
            }),
        ),
        R::Pause(args) => change(args, C::Pause(proto::Empty {})),
        R::Resume(args) => change(args, C::Resume(proto::Empty {})),
        R::Abort(args) => change(args, C::Abort(proto::Empty {})),
    })
}
fn change(args: &ChangeArgs, command: proto::change_rollout_request::Command) -> Operation {
    Operation::ChangeRollout(proto::ChangeRolloutRequest {
        id: args.id.clone(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: args.operation_id.clone(),
            expected_revision: Some(args.expected_revision),
        }),
        command: Some(command),
    })
}

fn start(
    args: &crate::args::rollout::StartArgs,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    let bytes = input::read(&args.candidate, 64 * 1024, "manifest")?;
    let manifest = crate::management::prepare::codec()
        .decode_deployment(&bytes)
        .map_err(|_| invalid_input())?;
    Phase1ManifestValidator
        .validate_deployment(&manifest)
        .map_err(|_| invalid_input())?;
    if args.weights.first().copied() != Some(u32::from(manifest.route_weight)) {
        return Err(Failure::local(
            "rollout-candidate-weight",
            "The candidate route weight must equal the first rollout stage.",
        ));
    }
    crate::management::prepare::tenant(
        manifest
            .metadata
            .tenant
            .as_ref()
            .map(|tenant| tenant.0.as_str()),
        &config.tenant,
    )?;
    let candidate = latent_wire::management::deployment_to_proto(&VersionedDeployment {
        manifest,
        generation: 0,
    })
    .map_err(|_| invalid_input())?;
    let policy = args
        .canary_policy
        .as_ref()
        .map(|path| {
            let bytes = input::read(path, 4096, "canary-policy")?;
            latent_artifacts::package::validate_package_json(
                &bytes,
                latent_artifacts::package::PackageLimits {
                    max_document_bytes: 4096,
                    max_depth: 4,
                    max_nodes: 32,
                    max_string_bytes: 128,
                    ..Default::default()
                },
            )
            .map_err(|_| invalid_input())?;
            let policy: latent_control_store::rollouts::RolloutCanaryPolicy =
                serde_json::from_slice(&bytes).map_err(|_| invalid_input())?;
            policy.validate().map_err(|_| invalid_input())?;
            Ok::<_, Failure>(proto::RolloutCanaryPolicy {
                format_version: policy.format_version,
                observation_millis: policy.observation_millis,
                minimum_candidate_samples: policy.minimum_candidate_samples,
                maximum_failure_basis_points: Some(u32::from(policy.maximum_failure_basis_points)),
                latency_threshold_micros: policy.latency_threshold_micros,
                maximum_slow_basis_points: Some(u32::from(policy.maximum_slow_basis_points)),
            })
        })
        .transpose()?;
    Ok(Operation::StartRollout(proto::StartRolloutRequest {
        id: args.id.clone(),
        base_deployment_id: args.base.clone(),
        expected_base_generation: Some(args.expected_base_generation),
        candidate: Some(candidate),
        candidate_weights: args.weights.clone(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: args.operation_id.clone(),
            expected_revision: Some(args.expected_revision),
        }),
        canary_policy: policy,
    }))
}
