use super::{
    RpcClient, codec, model, model_shapes::ModelShape, requests, responses::NativeReply,
    wire_schemas,
};
use crate::network::{ClientConfig, ClientLimits};
use latent_core::TenantId;
use latent_rpc::{control::v1 as c, phase4, transaction::v1 as t};
use prost::Message;
use tokio::time::Instant;

fn namespace() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: "tests".into(),
        namespace: "aggregate".into(),
        incarnation: "1".into(),
    }
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
    assert!(
        t::ExpectedVersion::try_from(model::ExpectedVersion {
            absent: Some(true),
            version: Some(vec![1]),
            ..Default::default()
        })
        .is_err()
    );
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
    assert!(
        codec::preflight(
            &wire_schemas::LATENT_TRANSACTION_V1_LISTEFFECTHISTORYRESPONSE,
            &expansion,
            1024
        )
        .is_err()
    );
    let duplicate = [18, 1, b'a', 18, 1, b'b'];
    assert!(codec::preflight(schema, &duplicate, 1024).is_err());
    let retained_ids: Vec<u8> = [50, 1, b'x'].repeat(256);
    assert!(codec::preflight(&wire_schemas::LATENT_TRANSACTION_V1_LINKEDRETENTION, &retained_ids, 1024).is_ok());
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
    let (_, checked, observed) = value.check(&association);
    assert!(checked.is_ok());
    assert!(!super::responses::known(observed.as_ref().unwrap()));
    assert!(
        matches!(observed, Some(model::ObservedOutcome::Command(value)) if value.proven_abort.is_none() && value.outcome == model::CommandOutcome::UNKNOWN)
    );
    let error = super::RpcFailure::status(&tonic::Status::aborted("transport abort"));
    assert_eq!(error.grpc_code, Some(10));
    assert!(
        model::ClientFailure {
            transport: Box::new(error.into()),
            identity: Box::new(requests::identity(&request)),
            observed: None
        }
        .observed
        .is_none()
    );
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
    use std::sync::{atomic::{AtomicUsize, Ordering}, Arc};
    use tonic::codegen::tokio_stream::wrappers::TcpListenerStream;
    for fail_audit in [false, true] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let service = super::test_peer::Service { calls: Arc::clone(&calls), fail_audit };
        let (stop, stopped) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            tonic::transport::Server::builder().max_concurrent_streams(2)
                .add_service(t::transaction_service_server::TransactionServiceServer::new(service))
                .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async { let _ = stopped.await; }).await.unwrap();
        });
        let client = RpcClient::new(ClientConfig { endpoint: address, tenant: TenantId("tests".into()),
            credential: "LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY".to_owned().into(), limits: ClientLimits::default() }).unwrap();
        let error = client.lookup_command(lookup().into(), model::CallOptions::default()).await.unwrap_err();
        assert_eq!(calls.load(Ordering::Acquire), 1);
        assert_eq!(error.identity.command.as_ref().unwrap().client_key, "original-client-key");
        if fail_audit {
            assert_eq!(error.transport.outcome, crate::management::OutcomeKnowledge::OBSERVED);
            assert!(matches!(error.observed, Some(model::ObservedOutcome::Command(value)) if
                value.outcome == model::CommandOutcome::REJECTED && value.metadata_durable &&
                !value.application_state_committed && value.proven_abort.is_none()));
        } else {
            assert_eq!(error.transport.outcome, crate::management::OutcomeKnowledge::UNKNOWN);
            assert!(error.observed.is_none());
            let request = model::InvokeCommandRequest {
                profile: Some(model::current_profile()), command: lookup().command.map(Into::into),
                invocation: Some(crate::management::InvokeRequest {
                    activation_id: Some("original-activation".into()),
                    target: Some(crate::management::InvocationTarget { tenant: "tests".into(), service: "aggregate".into(),
                        contract: "example:aggregate/api@1.0.0".into(), function: "update".into(), route: None }),
                    payload: vec![1], media_type: "application/octet-stream".into(),
                    budget: Some(crate::management::ResourceBudget::default()), ..Default::default()
                }), input_format: "raw-v1".into(),
                expected_versions: vec![model::ExpectedVersion { key: vec![1], absent: Some(true), version: None }],
                retry_attempt: None,
            };
            let error = client.invoke_command(request, model::CallOptions::default()).await.unwrap_err();
            assert_eq!(calls.load(Ordering::Acquire), 2);
            assert!(error.observed.is_none());
            assert_eq!(error.transport.outcome, crate::management::OutcomeKnowledge::UNKNOWN);
            assert_eq!(error.identity.expected_versions[0].absent, Some(true));
            assert!(error.identity.expected_abort.is_none());
            assert!(error.identity.retry_request_id.is_none());
        }
        client.shutdown(Instant::now() + std::time::Duration::from_secs(2)).await.unwrap();
        assert_eq!(client.usage().active_calls, 0);
        assert_eq!(client.usage().reserved_message_bytes, 0);
        assert_eq!(client.usage().sockets, 0);
        assert_eq!(client.usage().executor_tasks, 0);
        let _ = stop.send(());
        server.await.unwrap();
    }
}
