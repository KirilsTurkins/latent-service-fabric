use super::*;

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
