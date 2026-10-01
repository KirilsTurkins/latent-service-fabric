use super::{
    codec, model, model_shapes::ModelShape, requests, responses::NativeReply, wire_schemas,
    RpcClient,
};
use crate::network::{ClientConfig, ClientLimits};
use latent_core::TenantId;
use latent_rpc::{control::v1 as c, phase4, transaction::v1 as t};
use prost::Message;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tokio::time::Instant;
use tonic::codegen::tokio_stream::{wrappers::TcpListenerStream, StreamExt};

struct Peer {
    client: RpcClient,
    calls: Arc<AtomicUsize>,
    connections: Arc<AtomicUsize>,
    stop: tokio::sync::oneshot::Sender<()>,
    server: tokio::task::JoinHandle<()>,
}

async fn peer(fail_audit: bool) -> Peer {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = listener.local_addr().unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let connections = Arc::new(AtomicUsize::new(0));
    let accepted = Arc::clone(&connections);
    let incoming = TcpListenerStream::new(listener).map(move |value| {
        accepted.fetch_add(1, Ordering::AcqRel);
        value
    });
    let transaction = super::test_peer::Service {
        calls: Arc::clone(&calls),
        fail_audit,
    };
    let dispatcher = super::test_peer::Dispatcher {
        calls: Arc::clone(&calls),
    };
    let state = super::test_peer::State {
        calls: Arc::clone(&calls),
    };
    let (stop, stopped) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        tonic::transport::Server::builder()
            .max_concurrent_streams(2)
            .add_service(t::transaction_service_server::TransactionServiceServer::new(transaction))
            .add_service(c::dispatcher_service_server::DispatcherServiceServer::new(
                dispatcher,
            ))
            .add_service(c::state_service_server::StateServiceServer::new(state))
            .serve_with_incoming_shutdown(incoming, async {
                let _ = stopped.await;
            })
            .await
            .unwrap();
    });
    let client = RpcClient::new(ClientConfig {
        endpoint,
        tenant: TenantId("tests".into()),
        credential: "LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY".to_owned().into(),
        limits: ClientLimits::default(),
    })
    .unwrap();
    Peer {
        client,
        calls,
        connections,
        stop,
        server,
    }
}

impl Peer {
    async fn shutdown(self) {
        self.client
            .shutdown(Instant::now() + std::time::Duration::from_secs(2))
            .await
            .unwrap();
        assert_eq!(self.client.usage().active_calls, 0);
        assert_eq!(self.client.usage().reserved_message_bytes, 0);
        assert_eq!(self.client.usage().sockets, 0);
        assert_eq!(self.client.usage().executor_tasks, 0);
        let _ = self.stop.send(());
        self.server.await.unwrap();
    }
}

fn namespace() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: "tests".into(),
        namespace: "aggregate".into(),
        incarnation: "1".into(),
    }
}

#[tokio::test]
async fn effect_plan_transport_keeps_original_cas_historical_receipt_and_independent_facts() {
    use model::TransactionClient;
    let peer = peer(false).await;
    let original = c::PlanEffectMutationRequest {
        effect: Some(t::GetEffectRequest {
            profile: Some(phase4::current_profile()),
            command: Some(t::CommandSelector {
                namespace: Some(namespace()),
                operation: "update".into(),
                client_key: "effect-command".into(),
                entity: None,
                shared_recovery_scope: None,
            }),
            effect_id: "a".repeat(64),
            authorization_publication: Some(publication()),
        }),
        operation_id: "effect-operation".into(),
        mutation: 1,
        expected_version: vec![1; 32],
        expected_policy_digest: format!("sha256:{}", "a".repeat(64)),
        reason: "explicit redrive".into(),
        retry_delay_millis: 100,
    };
    let prepared = peer
        .client
        .plan_effect_mutation(
            original.clone().into(),
            crate::management::CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        prepared.metadata.transport.outcome,
        crate::management::OutcomeKnowledge::UNKNOWN
    );
    assert!(prepared.metadata.identity.effect_plan.is_some());
    let plan = prepared.value.plan.unwrap();
    let request = c::MutateStateRequest {
        namespace: Some(inspect()),
        operation_id: original.operation_id.clone(),
        mutation: original.mutation,
        record_id: Some(original.effect.as_ref().unwrap().effect_id.clone()),
        expected_version: original.expected_version.clone(),
        expected_policy_digest: original.expected_policy_digest.clone(),
        reason: original.reason.clone(),
        effect_plan: Some(super::test_peer::effect_plan(original.clone())),
    };
    let accepted = peer
        .client
        .mutate_state(
            request.clone().into(),
            crate::management::CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(accepted.value.receipt.unwrap().effect.unwrap().fact.0, 1);
    let mut current = inspect();
    current.authorization_publication.as_mut().unwrap().id =
        format!("publication:sha256:{}", "c".repeat(64));
    let recovered = peer
        .client
        .get_state_operation_receipt(
            model::GetStateOperationReceiptRequest {
                namespace: Some(current.clone().into()),
                operation_id: original.operation_id.clone(),
                original_effect_plan: Some(plan),
            },
            crate::management::CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        recovered
            .metadata
            .identity
            .authorization_publication
            .unwrap()
            .id,
        current.authorization_publication.unwrap().id
    );
    assert_eq!(
        recovered
            .metadata
            .identity
            .effect_mutation
            .unwrap()
            .effect
            .unwrap()
            .authorization_publication
            .unwrap()
            .id,
        publication().id
    );
    effect_plan_local_rejections(&peer, &request).await;
    effect_plan_response_facts(&peer, original, request).await;
    assert_eq!(peer.calls.load(Ordering::Acquire), 6);
    assert_eq!(peer.connections.load(Ordering::Acquire), 1);
    peer.shutdown().await;
}
async fn effect_plan_local_rejections(peer: &Peer, request: &c::MutateStateRequest) {
    use model::TransactionClient;
    let mut naked = request.clone();
    naked.effect_plan = None;
    assert!(
        !peer
            .client
            .mutate_state(naked.into(), crate::management::CallOptions::default())
            .await
            .unwrap_err()
            .transport
            .dispatched
    );
    let mut swapped = request.clone();
    swapped.expected_version.fill(0);
    assert!(
        !peer
            .client
            .mutate_state(swapped.into(), crate::management::CallOptions::default())
            .await
            .unwrap_err()
            .transport
            .dispatched
    );
}

async fn effect_plan_response_facts(
    peer: &Peer,
    original: c::PlanEffectMutationRequest,
    request: c::MutateStateRequest,
) {
    use model::TransactionClient;
    let mut audit = original.clone();
    audit.reason = "bad-audit".into();
    let failed = peer
        .client
        .plan_effect_mutation(
            audit.clone().into(),
            crate::management::CallOptions::default(),
        )
        .await
        .unwrap_err();
    assert_eq!(
        failed.transport.outcome,
        crate::management::OutcomeKnowledge::UNKNOWN
    );
    assert!(matches!(
        failed.observed,
        Some(model::ObservedOutcome::EffectPlan(_))
    ));
    assert_eq!(
        failed
            .identity
            .effect_plan
            .unwrap()
            .original
            .unwrap()
            .reason,
        "bad-audit"
    );
    audit.reason = "bad-window".into();
    assert!(peer
        .client
        .plan_effect_mutation(audit.into(), crate::management::CallOptions::default())
        .await
        .unwrap_err()
        .observed
        .is_none());
    let mut forged = request;
    forged.reason = "forged-fact".into();
    forged
        .effect_plan
        .as_mut()
        .unwrap()
        .original
        .as_mut()
        .unwrap()
        .reason = forged.reason.clone();
    assert!(peer
        .client
        .mutate_state(forged.into(), crate::management::CallOptions::default())
        .await
        .unwrap_err()
        .observed
        .is_none());
}

fn publication() -> c::PublicationRef {
    c::PublicationRef {
        tenant: "tests".into(),
        id: format!("publication:sha256:{}", "a".repeat(64)),
    }
}
fn inspect() -> c::InspectNamespaceRequest {
    c::InspectNamespaceRequest {
        profile: Some(phase4::current_profile()),
        namespace: Some(namespace()),
        authorization_publication: Some(publication()),
    }
}
fn lookup() -> t::LookupCommandRequest {
    t::LookupCommandRequest {
        profile: Some(phase4::current_profile()),
        command: Some(t::CommandSelector {
            namespace: Some(namespace()),
            operation: "update".into(),
            client_key: "original-client-key".into(),
            entity: Some("item".into()),
            shared_recovery_scope: None,
        }),
        attempt_id: None,
        authorization_publication: Some(publication()),
    }
}
fn client() -> RpcClient {
    RpcClient::new(ClientConfig {
        endpoint: "127.0.0.1:9".parse().unwrap(),
        tenant: TenantId("tests".into()),
        credential: "LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY".to_owned().into(),
        limits: ClientLimits::default(),
    })
    .unwrap()
}

#[test]
fn full_width_generation_presence_and_qualified_pages_roundtrip() {
    let value = model::MutateNamespaceRequest {
        namespace: Some(inspect().into()),
        operation_id: "original-operation".into(),
        mutation: model::NamespaceMutationKind::QUIESCE,
        expected_generation: Some(u64::MAX),
        configuration: None,
    };
    let native: c::MutateNamespaceRequest = value.clone().try_into().unwrap();
    assert_eq!(native.expected_generation, Some(u64::MAX));
    assert_eq!(
        model::MutateNamespaceRequest::from(
            c::MutateNamespaceRequest::decode(native.encode_to_vec().as_slice()).unwrap()
        ),
        value
    );
    let native: t::PageRequest = model::PageRequest {
        limit: 128,
        cursor: Some(vec![0, 255]),
    }
    .try_into()
    .unwrap();
    assert_eq!(native.cursor, Some(vec![0, 255]));
    let false_presence = model::ExpectedVersion {
        key: vec![1],
        absent: Some(false),
        version: None,
    };
    let native: t::ExpectedVersion = false_presence.clone().try_into().unwrap();
    assert_eq!(model::ExpectedVersion::from(native), false_presence);
    assert!(t::ExpectedVersion::try_from(model::ExpectedVersion {
        absent: Some(true),
        version: Some(vec![1]),
        ..Default::default()
    })
    .is_err());
}

#[test]
fn original_preconditions_and_current_publication_are_retained_without_refresh() {
    let request = phase4::Request::from(c::MutateStateRequest {
        namespace: Some(inspect()),
        operation_id: "original-operation".into(),
        mutation: c::StateMutationKind::CheckpointNamespace as i32,
        expected_version: vec![9, 0],
        expected_policy_digest: format!("sha256:{}", "b".repeat(64)),
        reason: "explicit".into(),
        record_id: None,
        effect_plan: None,
    });
    let context = requests::prepare(
        &request,
        &client(),
        Instant::now(),
        &model::CallOptions::default(),
    )
    .unwrap();
    assert_eq!(
        context.identity.operation_id.as_deref(),
        Some("original-operation")
    );
    assert_eq!(context.identity.expected_version, Some(vec![9, 0]));
    assert_eq!(
        context.identity.authorization_publication.unwrap().id,
        publication().id
    );
}

#[test]
fn predecode_rejects_duplicate_oneof_utf8_and_empty_record_expansion() {
    let schema = &wire_schemas::LATENT_TRANSACTION_V1_COMMANDINSPECTION;
    assert!(codec::preflight(schema, &[82, 0, 90, 0], 1024).is_err());
    assert!(codec::preflight(schema, &[18, 1, 255], 1024).is_err());
    let expansion: Vec<u8> = [10, 0].repeat(129);
    assert!(codec::preflight(
        &wire_schemas::LATENT_TRANSACTION_V1_LISTEFFECTHISTORYRESPONSE,
        &expansion,
        1024
    )
    .is_err());
    let duplicate = [18, 1, b'a', 18, 1, b'b'];
    assert!(codec::preflight(schema, &duplicate, 1024).is_err());
    let retained_ids: Vec<u8> = [50, 1, b'x'].repeat(256);
    assert!(codec::preflight(
        &wire_schemas::LATENT_TRANSACTION_V1_LINKEDRETENTION,
        &retained_ids,
        1024
    )
    .is_ok());
}

#[test]
fn model_collections_are_bounded_before_native_conversion() {
    let value = model::InvokeCommandRequest {
        expected_versions: vec![model::ExpectedVersion::default(); 129],
        ..Default::default()
    };
    assert_eq!(
        value.validate_shape(),
        Err(phase4::ValidationError::Capacity)
    );
}

#[test]
fn unknown_record_and_transport_abort_never_prove_an_explicit_attempt() {
    let request = phase4::Request::from(lookup());
    let association = request.association();
    let selector = lookup().command.unwrap();
    let value = t::LookupCommandResponse {
        command: Some(t::CommandInspection {
            key: Some(t::CommandKey {
                namespace: selector.namespace,
                operation: selector.operation,
                entity: selector.entity,
                client_key: selector.client_key,
                recovery_scope: "caller-scope".into(),
            }),
            outcome: t::CommandOutcome::Unknown as i32,
            ..Default::default()
        }),
    };
    let (_, checked, observed, _) = value.check(&association);
    assert!(checked.is_ok());
    assert!(!super::responses::known(observed.as_ref().unwrap()));
    assert!(
        matches!(observed, Some(model::ObservedOutcome::Command(value)) if value.proven_abort.is_none() && value.outcome == model::CommandOutcome::UNKNOWN)
    );
    let error = super::RpcFailure::status(&tonic::Status::aborted("transport abort"));
    assert_eq!(error.grpc_code, Some(10));
    assert!(model::ClientFailure {
        transport: Box::new(error.into()),
        identity: Box::new(requests::identity(&request)),
        observed: None
    }
    .observed
    .is_none());
}

#[tokio::test]
async fn local_deadline_keeps_original_identity_and_shutdown_retires() {
    use model::TransactionClient;
    let client = client();
    let error = client
        .lookup_command(
            lookup().into(),
            model::CallOptions {
                timeout_millis: Some(0),
            },
        )
        .await
        .unwrap_err();
    assert_eq!(
        error.identity.command.unwrap().client_key,
        "original-client-key"
    );
    assert!(!error.transport.dispatched);
    assert!(error.observed.is_none());
    assert_eq!(client.usage().active_calls, 0);
    client
        .shutdown(Instant::now() + std::time::Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(client.usage().reserved_message_bytes, 0);
}

#[tokio::test]
async fn actual_unary_keeps_durable_rejection_through_later_audit_failure_and_never_resubmits() {
    use model::TransactionClient;
    for fail_audit in [false, true] {
        let peer = peer(fail_audit).await;
        let error = peer
            .client
            .lookup_command(lookup().into(), model::CallOptions::default())
            .await
            .unwrap_err();
        assert_eq!(peer.calls.load(Ordering::Acquire), 1);
        assert_eq!(
            error.identity.command.as_ref().unwrap().client_key,
            "original-client-key"
        );
        if fail_audit {
            assert_eq!(
                error.transport.outcome,
                crate::management::OutcomeKnowledge::OBSERVED
            );
            assert!(
                matches!(error.observed, Some(model::ObservedOutcome::Command(value)) if
                value.outcome == model::CommandOutcome::REJECTED && value.metadata_durable &&
                !value.application_state_committed && value.proven_abort.is_none())
            );
        } else {
            assert_eq!(
                error.transport.outcome,
                crate::management::OutcomeKnowledge::UNKNOWN
            );
            assert!(error.observed.is_none());
            let request = model::InvokeCommandRequest {
                profile: Some(model::current_profile()),
                command: lookup().command.map(Into::into),
                invocation: Some(crate::management::InvokeRequest {
                    activation_id: Some("original-activation".into()),
                    target: Some(crate::management::InvocationTarget {
                        tenant: "tests".into(),
                        service: "aggregate".into(),
                        contract: "example:aggregate/api@1.0.0".into(),
                        function: "update".into(),
                        route: None,
                    }),
                    payload: vec![1],
                    media_type: "application/octet-stream".into(),
                    budget: Some(crate::management::ResourceBudget::default()),
                    ..Default::default()
                }),
                input_format: "raw-v1".into(),
                expected_versions: vec![model::ExpectedVersion {
                    key: vec![1],
                    absent: Some(true),
                    version: None,
                }],
                retry_attempt: None,
            };
            let error = peer
                .client
                .invoke_command(request, model::CallOptions::default())
                .await
                .unwrap_err();
            assert_eq!(peer.calls.load(Ordering::Acquire), 2);
            assert!(error.observed.is_none());
            assert_eq!(
                error.transport.outcome,
                crate::management::OutcomeKnowledge::UNKNOWN
            );
            assert_eq!(error.identity.expected_versions[0].absent, Some(true));
            assert!(error.identity.expected_abort.is_none());
            assert!(error.identity.retry_request_id.is_none());
        }
        peer.shutdown().await;
    }
}

#[tokio::test]
async fn dispatcher_uses_original_channel_and_keeps_receipt_through_independent_audit_failure() {
    use model::TransactionClient;
    let peer = peer(false).await;
    let original = c::ControlDispatcherRequest {
        profile: Some(phase4::current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: "original-control".into(),
        action: c::DispatcherAction::Pause as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: u64::MAX,
            revision: u64::MAX - 1,
        }),
    };
    let failure = peer
        .client
        .control_dispatcher(original.clone().into(), model::CallOptions::default())
        .await
        .unwrap_err();
    assert_eq!(
        failure.transport.outcome,
        crate::management::OutcomeKnowledge::OBSERVED
    );
    assert_eq!(
        failure
            .transport
            .unsupported_wire_value
            .as_ref()
            .unwrap()
            .value,
        "91"
    );
    assert_eq!(
        failure
            .identity
            .dispatcher_expected_generation
            .as_ref()
            .unwrap()
            .revision,
        u64::MAX - 1
    );
    assert!(failure.identity.expected_abort.is_none());
    assert!(
        matches!(failure.observed, Some(model::ObservedOutcome::Dispatcher(ref receipt)) if receipt.receipt_id == "dispatcher-receipt")
    );
    let inspected = peer
        .client
        .inspect_dispatcher(
            c::InspectDispatcherRequest {
                profile: Some(phase4::current_profile()),
                scope: c::DispatcherScope::Node as i32,
            }
            .into(),
            model::CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        inspected.value.dispatcher.unwrap().physical_owners,
        u64::MAX
    );
    let recovered = peer
        .client
        .get_dispatcher_operation(
            c::GetDispatcherOperationRequest {
                original: Some(original.clone()),
            }
            .into(),
            model::CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(
        recovered.value.receipt.unwrap().receipt_id,
        "dispatcher-receipt"
    );
    assert_eq!(
        recovered
            .metadata
            .identity
            .dispatcher_expected_generation
            .as_ref()
            .unwrap()
            .revision,
        u64::MAX - 1
    );
    assert_eq!(peer.calls.load(Ordering::Acquire), 3);
    assert_eq!(peer.connections.load(Ordering::Acquire), 1);
    reject_invalid_dispatcher_controls(&peer, &original).await;
    peer.shutdown().await;
}

async fn reject_invalid_dispatcher_controls(peer: &Peer, original: &c::ControlDispatcherRequest) {
    use model::TransactionClient;
    for (id, action) in [
        ("replayed", c::DispatcherAction::Pause),
        ("not-committed", c::DispatcherAction::Pause),
        ("resume", c::DispatcherAction::Resume),
    ] {
        let mut invalid = original.clone();
        invalid.operation_id = id.into();
        invalid.action = action as i32;
        let failure = peer
            .client
            .control_dispatcher(invalid.into(), model::CallOptions::default())
            .await
            .unwrap_err();
        assert!(failure.observed.is_none());
        assert_eq!(
            failure.transport.outcome,
            crate::management::OutcomeKnowledge::UNKNOWN
        );
    }
    let before = peer.calls.load(Ordering::Acquire);
    let mut exhausted = original.clone();
    exhausted.expected_generation.as_mut().unwrap().revision = u64::MAX;
    let failure = peer
        .client
        .control_dispatcher(exhausted.into(), model::CallOptions::default())
        .await
        .unwrap_err();
    assert!(!failure.transport.dispatched);
    assert_eq!(
        failure
            .identity
            .dispatcher_expected_generation
            .as_ref()
            .unwrap()
            .revision,
        u64::MAX
    );
    assert_eq!(peer.calls.load(Ordering::Acquire), before);
}
