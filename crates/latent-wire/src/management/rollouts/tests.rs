use super::super::RequestBudget;
use super::*;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};

fn principal() -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "operator".into(),
        tenant: Some(TenantId("acme".into())),
        kind: PrincipalKind::Administrator,
        service: None,
        claims: Metadata::new(),
    }
}

#[test]
fn rollout_scope_cannot_be_minted_from_an_operator_claim_or_missing_tenant() {
    let mut value = principal();
    value.kind = PrincipalKind::User;
    value
        .claims
        .insert("latent.node.operator".into(), "true".into());
    assert_eq!(
        validation::tenant(&value).unwrap_err().code(),
        tonic::Code::PermissionDenied
    );
    value.kind = PrincipalKind::Administrator;
    value.tenant = None;
    assert_eq!(
        validation::tenant(&value).unwrap_err().code(),
        tonic::Code::PermissionDenied
    );
    assert_eq!(
        validation::tenant(&principal()).unwrap(),
        TenantId("acme".into())
    );
}

#[test]
fn operation_preconditions_distinguish_missing_zero_and_positive_revision() {
    let limits = ManagementLimits::default();
    for (revision, start, valid) in [
        (None, true, false),
        (Some(0), true, true),
        (Some(1), true, false),
        (None, false, false),
        (Some(0), false, false),
        (Some(1), false, true),
    ] {
        let value = proto::RolloutOperationPrecondition {
            operation_id: "operation".into(),
            expected_revision: revision,
        };
        let mut budget = RequestBudget::new::<proto::ChangeRolloutRequest>(&limits).unwrap();
        assert_eq!(
            validation::operation(Some(&value), &mut budget, start, limits.max_id_bytes).is_ok(),
            valid
        );
    }
}

#[test]
fn short_identifiers_with_excess_retained_capacity_reject_before_work() {
    let mut value = proto::ChangeRolloutRequest {
        id: String::with_capacity(129),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "operation".into(),
            expected_revision: Some(1),
        }),
        command: Some(proto::change_rollout_request::Command::Pause(
            proto::Empty {},
        )),
    };
    value.id.push('r');
    assert_eq!(
        validation::change(&value, &ManagementLimits::default())
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
    value.id = "r".into();
    let lowered = ManagementLimits {
        max_id_bytes: 4,
        ..ManagementLimits::default()
    };
    assert_eq!(
        validation::change(&value, &lowered).unwrap_err().code(),
        tonic::Code::ResourceExhausted
    );
}

#[test]
fn unknown_state_and_absent_command_are_invalid() {
    for value in [0, -1, i32::MAX] {
        assert!(enums::state_input(value).is_err());
    }
    let value = proto::ChangeRolloutRequest {
        id: "rollout".into(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "operation".into(),
            expected_revision: Some(1),
        }),
        command: None,
    };
    assert_eq!(
        validation::change(&value, &ManagementLimits::default())
            .unwrap_err()
            .code(),
        tonic::Code::InvalidArgument
    );
}

#[test]
fn all_manual_states_round_trip_without_an_automatic_or_pending_state() {
    for value in [
        domain::RolloutState::Running,
        domain::RolloutState::Paused,
        domain::RolloutState::Completed,
        domain::RolloutState::Aborted,
        domain::RolloutState::Conflicted,
    ] {
        assert_eq!(enums::state_input(enums::state(value)).unwrap(), value);
    }
}
