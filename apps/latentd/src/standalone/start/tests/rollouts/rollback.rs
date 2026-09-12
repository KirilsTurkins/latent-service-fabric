use super::*;
use latent_core::{ContractId, FunctionId, ServiceId, TenantId};
use latent_routing::{InvocationTarget, RouteResolver};
use latent_wire::invocation::proto as invocation;

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "two real activations prove the same node publishes rollback and retires its canary window"
)]
async fn rollback_restores_real_base_invocation_and_retires_canary_observation() {
    let directory = TempDir::new().unwrap();
    let settings = canary::configured(&directory);
    let catalogs = Catalogs::open_with_control_and_clock(
        &settings,
        &tokio::runtime::Handle::current(),
        Arc::new(canary::Clock::new()),
    )
    .await
    .unwrap();
    let input = canary::seed(&catalogs, &settings.node.trust_classes[0]).await;
    let deployments = catalogs.deployments.clone();
    let candidate = input.candidate.as_ref().unwrap().release_digest.clone();
    let node = Box::pin(super::super::super::StandaloneNode::start_with_catalogs(
        settings,
        catalogs,
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    ))
    .await
    .unwrap();
    let endpoint = format!("http://{}", node.endpoint());
    let mut client = proto::rollout_service_client::RolloutServiceClient::connect(endpoint.clone())
        .await
        .unwrap();
    client.start_rollout(canary::request(input)).await.unwrap();
    let before = client
        .get_rollout(canary::request(proto::GetRolloutRequest {
            id: "observed".into(),
        }))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    let target = before.rollback_target.unwrap();
    let base = before.base.unwrap().component_digest;
    let invocation_target = InvocationTarget {
        tenant: TenantId("tests".into()),
        service: ServiceId("echo".into()),
        contract: ContractId("tests:echo/api@1.0.0".into()),
        function: FunctionId("echo".into()),
        route: None,
    };
    let activation = (0..128)
        .map(|index| format!("rollback-before-{index}"))
        .find(|key| {
            deployments
                .resolve(&invocation_target, Some(key))
                .unwrap()
                .release
                .0
                == candidate
        })
        .unwrap();
    check_invoked(&canary::invoke(&endpoint, activation).await, &candidate);
    // No Evaluate/Promote or elapsed interval is needed to restore an eligible
    // retained base; the selector comes only from this plan's exact status.
    let restored = client
        .change_rollout(canary::request(proto::ChangeRolloutRequest {
            id: "observed".into(),
            operation: Some(proto::RolloutOperationPrecondition {
                operation_id: "rollback".into(),
                expected_revision: Some(before.revision),
            }),
            command: Some(proto::change_rollout_request::Command::Rollback(
                proto::RollbackRollout {
                    target_generation: target.historical_route_generation,
                },
            )),
        }))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        restored.observation.unwrap().state,
        proto::RolloutObservationState::Retired as i32
    );
    let receipt = restored.receipt.unwrap();
    assert_eq!(receipt.state, proto::RolloutState::RolledBack as i32);
    assert_eq!(receipt.rollback_target, Some(target));
    assert!(receipt.route_generation > before.route_generation);
    assert!(receipt.canary_decision.is_none());
    assert_eq!(
        deployments
            .resolve(&invocation_target, Some("rollback-after"))
            .unwrap()
            .release
            .0,
        base
    );
    check_invoked(
        &canary::invoke(&endpoint, "rollback-after".into()).await,
        &base,
    );
    drop(client);
    drop(deployments);
    assert!(node.shutdown().await.unwrap().clean);
}

fn check_invoked(response: &invocation::InvokeResponse, expected: &str) {
    assert_eq!(response.release_digest, expected);
    assert!(
        matches!(
            response.result,
            Some(invocation::invoke_response::Result::Success(_))
        ),
        "{response:?}"
    );
    assert!(response.consumption.unwrap().cpu_fuel > 0);
}
