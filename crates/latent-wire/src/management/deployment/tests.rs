mod fixtures;

use latent_control_store::DeploymentPage;
use latent_core::{RouteGeneration, TenantId};
use tonic::Code;

use super::super::{proto, ManagementLimits, RequestBudget};
use super::{
    control_budget_from_proto, control_budget_to_proto, deployment_from_proto,
    deployment_manifest_from_proto, deployment_to_proto, response, validation,
};
use fixtures::deployment;

#[test]
fn every_deployment_field_and_object_stamp_survives_conversion() {
    let mut wire = deployment();
    wire.generation = 19;
    // Conversion is lossless even for later-phase dimensions; the RPC boundary
    // separately applies Phase 1 semantic validation before mutation.
    let budget = wire.resources.as_mut().unwrap();
    budget.child_calls = 1;
    budget.outbound_requests = 2;
    budget.state_read_bytes = 3;
    budget.state_write_bytes = 4;
    budget.blob_read_bytes = 5;
    budget.blob_write_bytes = 6;
    budget.effect_count = 7;
    let domain = deployment_from_proto(wire.clone()).unwrap();
    assert_eq!(domain.generation, 19);
    assert_eq!(deployment_to_proto(&domain).unwrap(), wire);
}

#[test]
fn apply_ignores_output_stamp_without_erasing_an_optional_budget() {
    let mut wire = deployment();
    wire.generation = u64::MAX;
    let expected = deployment_manifest_from_proto(wire.clone()).unwrap();
    wire.generation = 0;
    assert_eq!(deployment_manifest_from_proto(wire).unwrap(), expected);
    for wall_time_limit_millis in [None, Some(0), Some(u64::MAX)] {
        let budget = proto::ResourceBudget {
            wall_time_limit_millis,
            cpu_fuel: u64::MAX,
            ..proto::ResourceBudget::default()
        };
        assert_eq!(
            control_budget_to_proto(&control_budget_from_proto(&budget)),
            budget
        );
    }
}

#[test]
fn missing_fields_and_unrepresentable_values_fail_without_defaulting() {
    let mut wrong_name = deployment();
    wrong_name.metadata.as_mut().unwrap().name = "different".to_owned();
    assert_eq!(deployment_from_proto(wrong_name).unwrap_err().field, "id");
    let mut overflow = deployment();
    overflow.route_weight = u32::MAX;
    assert_eq!(
        deployment_from_proto(overflow).unwrap_err().field,
        "route_weight"
    );
    for field in ["metadata", "resources", "availability", "placement"] {
        let mut wire = deployment();
        match field {
            "metadata" => wire.metadata = None,
            "resources" => wire.resources = None,
            "availability" => wire.availability = None,
            "placement" => wire.placement = None,
            _ => unreachable!(),
        }
        assert_eq!(deployment_from_proto(wire).unwrap_err().field, field);
    }
    let mut unsupported = deployment_from_proto(deployment()).unwrap();
    unsupported.manifest.api_version = "latent.dev/v99".to_owned();
    assert_eq!(
        deployment_to_proto(&unsupported).unwrap_err().field,
        "api_version"
    );
}

#[test]
fn wire_bounds_reject_spare_string_and_sequence_allocations() {
    let limits = ManagementLimits::default();
    let mut wire = deployment();
    wire.id = String::with_capacity(limits.max_id_bytes + 1);
    wire.id.push_str("ship");
    let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&limits).unwrap();
    assert_eq!(
        validation::wire(&wire, &mut budget, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );

    let limits = ManagementLimits {
        max_request_bytes: 2048,
        ..limits
    };
    let mut wire = deployment();
    wire.grants = Vec::with_capacity(64);
    let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&limits).unwrap();
    assert_eq!(
        validation::wire(&wire, &mut budget, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn short_caller_ids_do_not_reject_generated_release_digests() {
    let limits = ManagementLimits {
        max_id_bytes: 16,
        ..ManagementLimits::default()
    };
    let mut wire = deployment();
    wire.grants.clear();
    let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&limits).unwrap();
    validation::wire(&wire, &mut budget, &limits).unwrap();
    let domain = deployment_from_proto(wire).unwrap();
    response::apply(&domain, &TenantId("acme".to_owned()), &limits).unwrap();
}

#[test]
fn responses_reject_wrong_scope_and_aggregate_page_allocation() {
    let limits = ManagementLimits {
        max_response_bytes: 32 * 1024,
        ..ManagementLimits::default()
    };
    let domain = deployment_from_proto(deployment()).unwrap();
    assert_eq!(
        response::get(Some(&domain), &TenantId("other".to_owned()), &limits)
            .unwrap_err()
            .code(),
        Code::Internal
    );
    let tenant = TenantId("acme".to_owned());
    response::get(Some(&domain), &tenant, &limits).unwrap();
    let page = DeploymentPage {
        deployments: vec![domain; 3],
        next_page_token: None,
        catalog_generation: RouteGeneration(1),
    };
    assert_eq!(
        response::page(&page, &tenant, 3, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}
