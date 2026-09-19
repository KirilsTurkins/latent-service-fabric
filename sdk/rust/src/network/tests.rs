use super::{
    error, ownership::Resources, ClientConfig, ClientLimits, FailureKind, RpcClient, RpcFailure,
};
use latent_core::{PlatformErrorCode, TenantId};
use latent_rpc::control::v1 as proto;
use prost::Message;
use std::{sync::Arc, time::Duration};
use tonic::{metadata::MetadataMap, Code, Status};

fn config() -> ClientConfig {
    ClientConfig {
        endpoint: "127.0.0.1:9080".parse().unwrap(),
        tenant: TenantId("tests".into()),
        credential: "LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY".to_owned().into(),
        limits: ClientLimits::default(),
    }
}

#[test]
fn configuration_is_explicit_bounded_redacted_and_does_not_start_io() {
    let value = config();
    let debug = format!("{value:?}");
    assert!(!debug.contains("tests"));
    assert!(!debug.contains(value.credential.as_str()));
    let client = RpcClient::new(value).unwrap();
    assert_eq!(client.usage().sockets, 0);
    assert_eq!(client.usage().executor_tasks, 0);
    for index in 0..7 {
        let mut value = config();
        match index {
            0 => value.endpoint = "192.0.2.1:9080".parse().unwrap(),
            1 => value.endpoint.set_port(0),
            2 => value.tenant = TenantId("-tenant".into()),
            3 => value.credential = "short".to_owned().into(),
            4 => value.limits.maximum_calls = 33,
            5 => value.limits.maximum_response_bytes = usize::MAX,
            _ => value.limits.connect_timeout = Duration::ZERO,
        }
        assert!(
            matches!(RpcClient::new(value), Err(error) if error.kind == FailureKind::InvalidConfiguration)
        );
    }
}

#[test]
fn audit_metadata_preserves_full_width_and_rejects_ambiguous_presence() {
    let mut metadata = MetadataMap::new();
    assert_eq!(error::audit(&metadata).unwrap(), None);
    metadata.insert("latent-audit-status", "durable".parse().unwrap());
    assert!(error::audit(&metadata).is_err());
    metadata.insert(
        "latent-audit-attempt",
        u64::MAX.to_string().parse().unwrap(),
    );
    assert_eq!(
        error::audit(&metadata).unwrap().unwrap().attempt_sequence,
        Some(u64::MAX)
    );
    for value in ["0", "01", "18446744073709551616", "-1", "1 "] {
        metadata.insert("latent-audit-attempt", value.parse().unwrap());
        assert!(error::audit(&metadata).is_err());
    }
    metadata.insert("latent-audit-attempt", "1".parse().unwrap());
    metadata.append("latent-audit-status", "durable".parse().unwrap());
    assert!(error::audit(&metadata).is_err());
    metadata.remove("latent-audit-status");
    assert!(error::audit(&metadata).is_err());
    metadata.insert("latent-audit-status", "future-state".parse().unwrap());
    let failure = error::audit(&metadata).unwrap_err();
    assert_eq!(failure.unsupported.unwrap().value, "future-state");
}

#[test]
fn typed_platform_details_require_canonical_codes_and_never_enable_retries() {
    let mut platform = proto::PlatformError {
        code: "permission-denied".into(),
        message: "untrusted server text".into(),
        retryable: true,
        detail_items: vec![],
    };
    let status = Status::with_details(
        Code::PermissionDenied,
        "denied",
        platform.encode_to_vec().into(),
    );
    let failure = RpcFailure::status(&status);
    assert_eq!(failure.kind, FailureKind::Rejected);
    assert_eq!(
        failure.platform.as_ref().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!format!("{failure:?}").contains("untrusted server text"));
    assert!(!crate::ClientTransportError::from(failure).retryable);
    let mismatch = Status::with_details(
        Code::Internal,
        "wrong code",
        platform.encode_to_vec().into(),
    );
    assert_eq!(
        RpcFailure::status(&mismatch).kind,
        FailureKind::InvalidResponse
    );
    platform.code = "future-code".into();
    let unknown = Status::with_details(Code::Internal, "unknown", platform.encode_to_vec().into());
    assert_eq!(
        RpcFailure::status(&unknown).unsupported.unwrap().value,
        "future-code"
    );
    let oversized = Status::with_details(Code::Internal, "oversize", vec![0; 8193].into());
    assert_eq!(
        RpcFailure::status(&oversized).kind,
        FailureKind::InvalidResponse
    );
    assert_eq!(
        RpcFailure::status(&Status::cancelled("Timeout expired")).kind,
        FailureKind::Connection
    );
}

#[test]
fn audit_uncertainty_does_not_turn_a_rejection_into_a_known_mutation_outcome() {
    let mut metadata = MetadataMap::new();
    metadata.insert("latent-audit-status", "outcome-unknown".parse().unwrap());
    metadata.insert("latent-audit-attempt", "1".parse().unwrap());
    let status = Status::with_metadata(Code::FailedPrecondition, "uncertain receipt", metadata);
    let failure = RpcFailure::status(&status).context(
        &super::RecoveryIdentity {
            activation_id: None,
            operation_id: Some("original-operation".into()),
        },
        true,
    );
    assert_eq!(failure.kind, FailureKind::Rejected);
    assert!(!failure.outcome_known);
    assert_eq!(
        failure.recovery.operation_id.as_deref(),
        Some("original-operation")
    );
}

#[test]
fn capacity_is_refunded_only_after_the_last_physical_body_owner_retires() {
    let resources = Resources::new(ClientLimits {
        maximum_calls: 1,
        ..ClientLimits::default()
    });
    let caller = resources.begin(128).unwrap();
    let body = Arc::clone(&caller);
    drop(caller);
    assert_eq!(resources.usage().active_calls, 1);
    assert!(resources.begin(1).is_err());
    resources.close();
    assert_eq!(resources.usage().active_calls, 1);
    drop(body);
    assert_eq!(resources.usage().active_calls, 0);
    assert_eq!(resources.usage().reserved_message_bytes, 0);
    assert!(resources.begin(1).is_err());
}
