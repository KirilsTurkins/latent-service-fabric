//! Safe fixed-schema target inspection; no mutation recovery identity is made.
use super::invalid_response;
use crate::{
    args::TargetInspectionArgs, config::ResolvedConfig, error::Failure, operation::Operation,
    output::Outcome,
};
use latent_wire::management::proto;
use serde_json::{json, Value};

pub(super) fn prepare(
    args: &TargetInspectionArgs,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    let publication = args
        .publication
        .as_ref()
        .map(|id| {
            id.parse::<latent_core::PublicationId>().map_err(|_| {
                Failure::local(
                    "invalid-publication-selector",
                    "An exact publication ID is required.",
                )
            })?;
            Ok(proto::PublicationRef {
                id: id.clone(),
                tenant: config.tenant.clone(),
            })
        })
        .transpose()?;
    Ok(Operation::InspectHttpTarget(
        proto::InspectHttpTargetRequest {
            service: args.service.clone(),
            contract: args.contract.clone(),
            function: args.function.clone(),
            route: args.route.clone(),
            revision_id: args.revision.clone(),
            publication,
            routing_key: args.routing_key.clone(),
            include_preparation: args.include_preparation,
            maximum_wait_millis: args.maximum_wait_millis,
        },
    ))
}

pub(super) fn associate(
    value: &proto::InspectHttpTargetResponse,
    expected: &proto::InspectHttpTargetRequest,
    tenant: &str,
) -> Result<(), Failure> {
    if value.tenant != tenant
        || value.service != expected.service
        || value.contract != expected.contract
        || value.function != expected.function
        || value.route != expected.route.as_deref().unwrap_or("default")
        || value.live_grants_checked
        || expected.routing_key.is_none() && value.selected_revision_id.is_some()
    {
        return Err(invalid_response());
    }
    for candidate in &value.candidates {
        if expected
            .revision_id
            .as_ref()
            .is_some_and(|id| &candidate.revision_id != id)
            || expected
                .publication
                .as_ref()
                .is_some_and(|publication| candidate.publication.as_ref() != Some(publication))
            || [&candidate.publication, &candidate.requested_publication]
                .into_iter()
                .flatten()
                .any(|publication| publication.tenant != tenant)
            || candidate.preparation.as_ref().is_none_or(|preparation| {
                (preparation.state == proto::TargetPreparationState::NotRequested as i32)
                    == expected.include_preparation
            })
        {
            return Err(invalid_response());
        }
    }
    if value.selected_revision_id.as_ref().is_some_and(|id| {
        !value
            .candidates
            .iter()
            .any(|candidate| &candidate.revision_id == id)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn response(value: proto::InspectHttpTargetResponse) -> Outcome {
    let candidates = value.candidates.into_iter().map(|candidate| {
        let reasons = candidate.reasons.iter().map(|reason| reason_name(*reason)).collect::<Vec<_>>();
        let dependencies = candidate.dependencies.into_iter().map(|dependency| json!({
            "capability":dependency.capability,"state":dependency.state,"policyIdentityDigest":dependency.policy_identity_digest,
            "providerConfigurationEpoch":dependency.provider_configuration_epoch.to_string(),
            "binding":dependency.binding.as_ref().map(revision),"policies":dependency.policies.iter().map(revision).collect::<Vec<_>>(),
            "providerProfile":dependency.provider_profile,"configurationDigest":dependency.configuration_digest,
        })).collect::<Vec<_>>();
        json!({"deploymentId":candidate.deployment_id,"deploymentGeneration":candidate.deployment_generation.to_string(),
            "revisionId":candidate.revision_id,"componentDigest":candidate.component_digest,"packageDigest":candidate.package_digest,
            "publication":candidate.publication.as_ref().map(publication),"requestedPublication":candidate.requested_publication.as_ref().map(publication),
            "publicationKind":candidate.publication_kind,"publicationGeneration":candidate.publication_generation.map(|value| value.to_string()),
            "routingWeight":candidate.routing_weight,"exportCompatible":candidate.export_compatible,"httpCompatible":candidate.http_compatible,
            "eligible":candidate.eligible,"reasons":candidate.reasons,"reasonNames":reasons,"dependencies":dependencies,
            "preparation":candidate.preparation.map(preparation),
            "httpBindings":candidate.http_bindings.into_iter().map(|binding| json!({"id":binding.id,"generation":binding.generation.to_string(),
                "selectedDeploymentGeneration":binding.selected_deployment_generation.to_string(),"state":binding.state})).collect::<Vec<_>>()})
    }).collect::<Vec<_>>();
    Outcome::success(
        json!({"schemaVersion":value.schema_version,"tenant":value.tenant,"service":value.service,
        "contract":value.contract,"function":value.function,"route":value.route,"state":value.state,"stateName":state_name(value.state),
        "catalogTransaction":value.catalog_transaction.to_string(),"routeGeneration":value.route_generation.to_string(),
        "bindingGeneration":value.binding_generation.to_string(),"policyStoreGeneration":value.policy_store_generation.map(|value| value.to_string()),
        "candidates":candidates,"selectedRevisionId":value.selected_revision_id,"liveGrantsChecked":value.live_grants_checked}),
    )
}

fn publication(value: &proto::PublicationRef) -> Value {
    json!({"tenant":value.tenant,"id":value.id})
}
fn revision(value: &proto::TargetDependencyRevision) -> Value {
    json!({"id":value.id,"digest":value.digest,"revision":value.revision.to_string()})
}
fn preparation(value: proto::TargetPreparation) -> Value {
    let exports = value
        .exports
        .into_iter()
        .map(|export| json!({"contract":export.contract,"function":export.function}))
        .collect::<Vec<_>>();
    json!({"state":value.state,"stateName":preparation_name(value.state),"diagnostic":value.diagnostic.as_ref().map(diagnostic),
        "profile":value.profile,"profileName":value.profile.and_then(profile_name),"engineVersion":value.engine_version,
        "engineConfigurationDigest":value.engine_configuration_digest,"targetTriple":value.target_triple,"cpuFeatureSet":value.cpu_feature_set,
        "sealedMetadataFingerprint":value.sealed_metadata_fingerprint,"importCount":value.import_count.map(|value| value.to_string()),
        "functionCount":value.function_count.map(|value| value.to_string()),"hostcallFuel":value.hostcall_fuel.map(|value| value.to_string()),
        "maximumLiftedBytes":value.maximum_lifted_bytes.map(|value| value.to_string()),"maximumTypeNodes":value.maximum_type_nodes.map(|value| value.to_string()),
        "declaredBudget":value.declared_budget.map(budget),"imports":value.imports,"typeImports":value.type_imports,"exports":exports})
}
fn budget(value: proto::ResourceBudget) -> Value {
    json!({"cpuFuel":value.cpu_fuel.to_string(),"memoryBytes":value.memory_bytes.to_string(),
    "wallTimeLimitMillis":value.wall_time_limit_millis.map(|value| value.to_string()),"childCalls":value.child_calls,"outboundRequests":value.outbound_requests,
    "stateReadBytes":value.state_read_bytes.to_string(),"stateWriteBytes":value.state_write_bytes.to_string(),"blobReadBytes":value.blob_read_bytes.to_string(),
    "blobWriteBytes":value.blob_write_bytes.to_string(),"logBytes":value.log_bytes.to_string(),"effectCount":value.effect_count})
}
fn diagnostic(value: &proto::ActivationDiagnostic) -> Value {
    json!({"schemaVersion":value.schema_version,"stage":value.stage,"reason":value.reason,
    "stageName":proto::DiagnosticStage::try_from(value.stage).ok().map(|value| value.as_str_name()),
    "reasonName":proto::DiagnosticReason::try_from(value.reason).ok().map(|value| value.as_str_name()),"profile":value.profile,"profileDigest":value.profile_digest,
    "configuredBound":value.configured_bound.map(|value| value.to_string()),"calculatedRequirement":value.calculated_requirement.map(|value| value.to_string()),
    "fixedBytes":value.fixed_bytes.map(|value| value.to_string()),"liftingFuel":value.lifting_fuel.map(|value| value.to_string()),"liftMultiplier":value.lift_multiplier.map(|value| value.to_string())})
}
fn state_name(value: i32) -> Option<&'static str> {
    match value {
        1 => Some("coherent"),
        2 => Some("stale"),
        3 => Some("unavailable"),
        _ => None,
    }
}
fn preparation_name(value: i32) -> Option<&'static str> {
    match value {
        1 => Some("ready"),
        2 => Some("rejected"),
        3 => Some("unavailable"),
        4 => Some("not-requested"),
        _ => None,
    }
}
fn profile_name(value: i32) -> Option<&'static str> {
    match value {
        1 => Some("wasmtime-service-values-v1"),
        2 => Some("wasmtime-buffered-web-values-v1"),
        _ => None,
    }
}
fn reason_name(value: i32) -> Option<&'static str> {
    match value {
        1 => Some("current"),
        2 => Some("export-absent"),
        3 => Some("zero-routing-weight"),
        4 => Some("publication-unavailable"),
        5 => Some("binding-plan-unavailable"),
        6 => Some("policy-changed-or-revoked"),
        7 => Some("provider-unavailable"),
        8 => Some("inspection-unavailable"),
        9 => Some("unmanaged-publication"),
        10 => Some("http-incompatible"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::management::bounds;

    fn reply() -> proto::InspectHttpTargetResponse {
        proto::InspectHttpTargetResponse {
            schema_version: 1,
            tenant: "a".into(),
            service: "service".into(),
            contract: "contract".into(),
            function: "function".into(),
            route: "default".into(),
            state: 1,
            catalog_transaction: u64::MAX,
            binding_generation: u64::MAX,
            policy_store_generation: Some(0),
            candidates: vec![proto::TargetCandidate {
                deployment_id: "deployment".into(),
                deployment_generation: u64::MAX,
                revision_id: "revision".into(),
                component_digest: format!("sha256:{}", "a".repeat(64)),
                reasons: vec![777],
                preparation: Some(proto::TargetPreparation {
                    state: 2,
                    imports: vec!["latent:runtime/clocks@0.1.0".into()],
                    type_imports: vec!["examples:java-http-domain/types@1.0.0".into()],
                    import_count: Some(2),
                    diagnostic: Some(proto::ActivationDiagnostic {
                        schema_version: 1,
                        stage: 778,
                        reason: 779,
                        configured_bound: Some(0),
                        calculated_requirement: Some(u64::MAX),
                        ..proto::ActivationDiagnostic::default()
                    }),
                    ..proto::TargetPreparation::default()
                }),
                ..proto::TargetCandidate::default()
            }],
            ..proto::InspectHttpTargetResponse::default()
        }
    }
    #[test]
    fn target_json_preserves_exact_u64_absence_and_future_reason_values() {
        let value = reply();
        bounds::checked(&value, 65536).unwrap();
        let json = response(value).data;
        assert_eq!(json["catalogTransaction"], u64::MAX.to_string());
        assert_eq!(json["policyStoreGeneration"], "0");
        assert_eq!(json["stateName"], "coherent");
        let candidate = &json["candidates"][0];
        assert_eq!(candidate["deploymentGeneration"], u64::MAX.to_string());
        assert_eq!(candidate["reasons"][0], 777);
        assert!(candidate["reasonNames"][0].is_null());
        assert!(candidate["requestedPublication"].is_null());
        assert!(candidate["packageDigest"].is_null());
        assert_eq!(
            candidate["preparation"]["diagnostic"]["calculatedRequirement"],
            u64::MAX.to_string()
        );
        assert_eq!(
            candidate["preparation"]["diagnostic"]["configuredBound"],
            "0"
        );
        assert!(candidate["preparation"]["diagnostic"]["fixedBytes"].is_null());
        assert_eq!(candidate["preparation"]["importCount"], "2");
        assert_eq!(
            candidate["preparation"]["imports"][0],
            "latent:runtime/clocks@0.1.0"
        );
        assert_eq!(
            candidate["preparation"]["typeImports"][0],
            "examples:java-http-domain/types@1.0.0"
        );
    }
    #[test]
    fn target_reply_rejects_foreign_scope_selector_drift_and_unmeasured_ready_claims() {
        let expected = proto::InspectHttpTargetRequest {
            service: "service".into(),
            contract: "contract".into(),
            function: "function".into(),
            include_preparation: true,
            ..proto::InspectHttpTargetRequest::default()
        };
        let mut value = reply();
        associate(&value, &expected, "a").unwrap();
        assert!(associate(&value, &expected, "foreign").is_err());
        value.selected_revision_id = Some("revision".into());
        assert!(associate(&value, &expected, "a").is_err());
        value.selected_revision_id = None;
        value.candidates[0].preparation.as_mut().unwrap().state = 1;
        assert!(bounds::checked(&value, 65536).is_err());
        value.candidates[0].preparation.as_mut().unwrap().state = 2;
        value.state = 2;
        value.candidates[0].eligible = true;
        assert!(bounds::checked(&value, 65536).is_err());
        value.candidates[0].eligible = false;
        value.candidates.resize(33, value.candidates[0].clone());
        assert!(bounds::checked(&value, 65536).is_err());
    }
    #[test]
    fn target_command_has_finite_wait_and_exact_publication_grammar() {
        use clap::Parser as _;
        let base = [
            "latent",
            "route",
            "target",
            "--service",
            "service",
            "--contract",
            "contract",
            "--function",
            "function",
        ];
        let cli = crate::args::Cli::try_parse_from(base).unwrap();
        cli.validate().unwrap();
        assert!(crate::args::Cli::try_parse_from(
            base.into_iter().chain(["--maximum-wait-millis", "30001"])
        )
        .is_err());
        let cli = crate::args::Cli::try_parse_from(
            base.into_iter()
                .chain(["--publication", "ambiguous-component-digest"]),
        )
        .unwrap();
        assert!(cli.validate().is_err());
        let cli = crate::args::Cli::try_parse_from(base.into_iter().chain([
            "--publication",
            &format!("publication:sha256:{}", "a".repeat(64)),
        ]))
        .unwrap();
        cli.validate().unwrap();
    }
}
