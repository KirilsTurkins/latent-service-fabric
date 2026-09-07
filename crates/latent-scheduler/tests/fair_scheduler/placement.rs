use std::time::Duration;

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_admission::AdmissionPermit;
use latent_core::{
    InvocationPrincipal, Metadata, NodeId, PlatformErrorCode, PrincipalKind, SpanId, TraceId,
};
use latent_scheduler::{
    CellClass, ClusterPlacement, LocalNodePlacement, NodeCandidate, SchedulingRequest,
};

use super::support::Fixture;

fn request(permit: &AdmissionPermit) -> SchedulingRequest {
    SchedulingRequest {
        envelope: ActivationEnvelope {
            activation_id: permit.activation_id().clone(),
            parent_activation_id: None,
            root_activation_id: permit.activation_id().clone(),
            principal: InvocationPrincipal {
                subject: "local-client".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(permit.tenant().clone()),
                service: None,
                claims: Metadata::new(),
            },
            target: permit.revision().target.clone(),
            resolved_revision: Some(permit.revision().clone()),
            deadline_unix_millis: permit.deadline().unix_millis(),
            priority: permit.obligations().priority,
            trace: TraceContext {
                trace_id: TraceId("placement-trace".to_owned()),
                span_id: SpanId("placement-span".to_owned()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: permit.granted_budget().clone(),
            metadata: Metadata::new(),
            input: vec![1, 2, 3, 4],
            input_media_type: "application/octet-stream".to_owned(),
        },
        trust_class: permit.obligations().trust_class.clone(),
        cell_class: CellClass::Tiny,
        artifact_locality: Some(permit.revision().release.clone()),
        state_affinity_key: None,
        required_features: vec![],
    }
}

fn candidate(node: NodeId, available_cells: u32) -> NodeCandidate {
    NodeCandidate {
        node,
        queue_delay_micros: 0,
        artifact_cached: true,
        state_affinity: true,
        available_cells,
        attributes: Metadata::new(),
    }
}

#[tokio::test(start_paused = true)]
async fn placement_selects_only_the_configured_local_node_with_stable_evidence() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let admitted = fixture.request("placement", "a");
    let request = request(&admitted.permit);
    let placement = LocalNodePlacement::new(fixture.configuration.node.clone());
    let local = candidate(fixture.configuration.node.clone(), 1);
    let remote = candidate(NodeId("remote".to_owned()), u32::MAX);

    let decision = placement
        .place(&request, &[remote.clone(), local.clone()])
        .await
        .unwrap();
    assert_eq!(decision.selected_node, local.node);
    assert_eq!(decision.considered, vec![local.clone()]);
    assert_eq!(decision.policy_digest, "local-node-v1");
    assert_eq!(
        placement.place(&request, &[local, remote]).await.unwrap(),
        decision
    );
    drop(admitted);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn placement_requires_the_configured_local_node_to_be_present() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let admitted = fixture.request("no-local-placement", "a");
    let request = request(&admitted.permit);
    let placement = LocalNodePlacement::new(fixture.configuration.node.clone());
    for candidates in [
        vec![],
        vec![candidate(NodeId("remote".to_owned()), u32::MAX)],
    ] {
        assert_eq!(
            placement
                .place(&request, &candidates)
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::Unavailable
        );
    }
    drop(admitted);
    fixture.assert_no_quota();
}
