use super::*;

fn captured_request() -> proto::ApplyDeploymentRequest {
    proto::ApplyDeploymentRequest {
        deployment:
            Some(
                super::super::super::deployment_to_proto(
                    &super::super::super::tests::captured_phase4(),
                )
                .unwrap(),
            ),
        expected_component_digest: None,
        expected_generation: Some(0),
        operation: Some(proto::DeploymentOperationPrecondition {
            operation_id: "phase4-control".into(),
            expected_state_version: Some(0),
        }),
    }
}

fn administrator() -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "workflow-operator".into(),
        kind: latent_core::PrincipalKind::Administrator,
        tenant: Some(latent_core::TenantId("examples".into())),
        service: None,
        claims: latent_core::Metadata::new(),
    }
}

#[test]
fn managed_phase4_validation_preserves_original_request_and_stateless_refusal() {
    let limits = ManagementLimits::default();
    assert_eq!(
        apply(
            captured_request(),
            administrator(),
            &limits,
            ManifestValidationProfile::default()
        )
        .unwrap_err()
        .code(),
        tonic::Code::InvalidArgument
    );
    let request = apply(
        captured_request(),
        administrator(),
        &limits,
        super::super::super::tests::phase4_profile(),
    )
    .unwrap();
    let DeploymentOperationRequest::Apply {
        context,
        manifest,
        expected_generation,
    } = request
    else {
        panic!("expected apply");
    };
    assert_eq!(
        manifest,
        super::super::super::tests::captured_phase4().manifest
    );
    assert_eq!(context.tenant.0, "examples");
    assert_eq!(context.expected_state_version, 0);
    assert_eq!(expected_generation, 0);
}

#[test]
fn managed_phase4_selection_retains_required_fields_scope_and_preconditions() {
    let profile = super::super::super::tests::phase4_profile();
    let limits = ManagementLimits::default();
    for change in [
        "metadata",
        "resources",
        "tenant",
        "route",
        "operation",
        "generation",
        "availability",
    ] {
        let mut request = captured_request();
        let expected = if change == "tenant" {
            tonic::Code::PermissionDenied
        } else {
            tonic::Code::InvalidArgument
        };
        match change {
            "metadata" => request.deployment.as_mut().unwrap().metadata = None,
            "resources" => request.deployment.as_mut().unwrap().resources = None,
            "tenant" => {
                let deployment = request.deployment.as_mut().unwrap();
                deployment.metadata.as_mut().unwrap().tenant = Some("foreign".into());
                deployment.publication.as_mut().unwrap().tenant = "foreign".into();
                deployment.requested_publication.as_mut().unwrap().tenant = "foreign".into();
            }
            "route" => request.deployment.as_mut().unwrap().route_weight = 10001,
            "operation" => request.operation = None,
            "generation" => request.expected_generation = None,
            "availability" => {
                request
                    .deployment
                    .as_mut()
                    .unwrap()
                    .availability
                    .as_mut()
                    .unwrap()
                    .minimum_zones = 2;
            }
            _ => unreachable!(),
        }
        assert_eq!(
            apply(request, administrator(), &limits, profile)
                .unwrap_err()
                .code(),
            expected,
            "{change}"
        );
    }
    let mut request = captured_request();
    let id = &mut request.deployment.as_mut().unwrap().id;
    let value = id.clone();
    *id = String::with_capacity(limits.max_id_bytes + 1);
    id.push_str(&value);
    assert_eq!(
        apply(request, administrator(), &limits, profile)
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
}

#[test]
fn managed_preconditions_preserve_presence_zero_and_full_u64() {
    for (state, generation, delete, valid) in [
        (None, Some(0), false, false),
        (Some(0), None, false, false),
        (Some(0), Some(0), false, true),
        (Some(0), Some(0), true, false),
        (Some(u64::MAX), Some(u64::MAX), true, true),
    ] {
        let value = proto::DeploymentOperationPrecondition {
            operation_id: "op".into(),
            expected_state_version: state,
        };
        let mut budget =
            RequestBudget::new::<proto::ApplyDeploymentRequest>(&ManagementLimits::default())
                .unwrap();
        assert_eq!(
            operation(Some(&value), generation, delete, &mut budget).is_ok(),
            valid
        );
    }
}

#[test]
fn managed_operation_id_rejects_spare_capacity_before_decode() {
    let mut id = String::with_capacity(129);
    id.push_str("op");
    let value = proto::DeploymentOperationPrecondition {
        operation_id: id,
        expected_state_version: Some(0),
    };
    let mut budget =
        RequestBudget::new::<proto::ApplyDeploymentRequest>(&ManagementLimits::default()).unwrap();
    assert_eq!(
        operation(Some(&value), Some(0), false, &mut budget)
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
}
