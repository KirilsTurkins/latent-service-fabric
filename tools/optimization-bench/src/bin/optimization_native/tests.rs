use std::time::{Duration, Instant};

use clap::Parser;
use latent_optimization_workloads::{invoke, CONTRACT, MEDIA_TYPE};
use latent_rpc::invocation::v1::{self as proto, invocation_service_server::InvocationService};
use tonic::{Code, Request};

use super::{
    command::Args,
    service::{completed, NativeService},
    validation,
};

const TOKEN: &str = "native-reference-test-credential-1234567890";

fn args() -> Args {
    Args::try_parse_from([
        "optimization-native",
        "--token",
        TOKEN,
        "--concurrency",
        "1",
        "--services",
        "optimization/workloads,optimization/workloads-1",
    ])
    .unwrap()
}

fn request(function: &str, payload: &[u8]) -> Request<proto::InvokeRequest> {
    let mut request = Request::new(proto::InvokeRequest {
        activation_id: Some("known-before-completion".to_owned()),
        target: Some(proto::InvocationTarget {
            tenant: "optimization".to_owned(),
            service: "optimization/workloads".to_owned(),
            contract: CONTRACT.to_owned(),
            function: function.to_owned(),
            route: None,
        }),
        payload: payload.to_vec(),
        media_type: MEDIA_TYPE.to_owned(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 10_000_000_000,
            memory_bytes: 64 * 1024 * 1024,
            wall_time_limit_millis: Some(5000),
            ..proto::ResourceBudget::default()
        }),
        ..proto::InvokeRequest::default()
    });
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
    request
}

fn failure(response: &proto::InvokeResponse) -> &proto::PlatformError {
    let Some(proto::invoke_response::Result::PlatformFailure(error)) = &response.result else {
        panic!("expected platform failure")
    };
    error
}

#[tokio::test]
async fn native_success_matches_shared_bytes_and_preserves_caller_identity() {
    let service = NativeService::new(&args());
    for (function, payload) in [
        ("echo", br#"["hello"]"#.as_slice()),
        ("compute", b"[1,3]"),
        (
            "transform",
            br#"[{"label":"x","bytes":[1,2],"values":[0,4294967295]}]"#,
        ),
    ] {
        let response = service
            .invoke(request(function, payload))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(response.activation_id, "known-before-completion");
        assert_eq!(response.release_digest, "native-reference-v1");
        let Some(proto::invoke_response::Result::Success(success)) = response.result else {
            panic!("expected success")
        };
        assert_eq!(success.payload, invoke(function, payload).unwrap());
        assert_eq!(success.media_type, MEDIA_TYPE);
        let consumption = response.consumption.unwrap();
        assert_eq!(consumption.cpu_fuel, 0);
        assert_eq!(consumption.peak_memory_bytes, 0);
    }
}

#[tokio::test]
async fn token_tenant_service_and_explicit_empty_identity_are_checked() {
    let service = NativeService::new(&args());
    let mut missing = request("echo", br#"["x"]"#);
    missing.metadata_mut().remove("authorization");
    assert_eq!(
        service.invoke(missing).await.unwrap_err().code(),
        Code::Unauthenticated
    );
    let mut duplicate = request("echo", br#"["x"]"#);
    duplicate
        .metadata_mut()
        .append("authorization", "Bearer unrelated".parse().unwrap());
    assert_eq!(
        service.invoke(duplicate).await.unwrap_err().code(),
        Code::Unauthenticated
    );
    let mut foreign = request("echo", br#"["x"]"#);
    foreign.get_mut().target.as_mut().unwrap().tenant = "other".to_owned();
    assert_eq!(
        service.invoke(foreign).await.unwrap_err().code(),
        Code::PermissionDenied
    );
    let mut unregistered = request("echo", br#"["x"]"#);
    unregistered.get_mut().target.as_mut().unwrap().service = "optimization/workloads-4".to_owned();
    assert_eq!(
        service.invoke(unregistered).await.unwrap_err().code(),
        Code::NotFound
    );
    let mut empty = request("echo", br#"["x"]"#);
    empty.get_mut().activation_id = Some(String::new());
    assert_eq!(
        service.invoke(empty).await.unwrap_err().code(),
        Code::InvalidArgument
    );
    let mut registered = request("echo", br#"["x"]"#);
    registered.get_mut().target.as_mut().unwrap().service = "optimization/workloads-1".to_owned();
    registered.get_mut().activation_id = None;
    assert_eq!(
        service
            .invoke(registered)
            .await
            .unwrap()
            .into_inner()
            .activation_id,
        "native-activation-0"
    );
}

#[tokio::test]
async fn global_capacity_rejection_and_release_are_visible_without_queuing() {
    let service = NativeService::new(&args());
    let held = service.hold_capacity();
    let rejected = service
        .invoke(request("echo", br#"["x"]"#))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(failure(&rejected).code, "unavailable");
    assert!(failure(&rejected).retryable);
    drop(held);
    let response = service
        .invoke(request("echo", br#"["x"]"#))
        .await
        .unwrap()
        .into_inner();
    assert!(matches!(
        response.result,
        Some(proto::invoke_response::Result::Success(_))
    ));
}

#[tokio::test]
async fn expired_requests_and_post_work_expiry_preserve_known_identity() {
    let service = NativeService::new(&args());
    let mut expired = request("compute", b"[1,3]");
    expired.get_mut().deadline_unix_millis = Some(0);
    let response = service.invoke(expired).await.unwrap().into_inner();
    assert_eq!(failure(&response).code, "deadline-exceeded");
    assert_eq!(response.activation_id, "known-before-completion");
    let started = Instant::now();
    let response = completed(
        "post-work".to_owned(),
        started,
        started + Duration::from_millis(1),
        started + Duration::from_millis(2),
        Ok(b"[42]".to_vec()),
    );
    assert_eq!(failure(&response).code, "deadline-exceeded");
    assert_eq!(response.activation_id, "post-work");
}

#[test]
fn deadlines_intersect_transport_absolute_relative_and_node_limits() {
    let started = Instant::now();
    let mut request = request("echo", br#"["x"]"#);
    request.get_mut().deadline_unix_millis = Some(1002);
    request
        .get_mut()
        .budget
        .as_mut()
        .unwrap()
        .wall_time_limit_millis = Some(4);
    request
        .metadata_mut()
        .insert("grpc-timeout", "1m".parse().unwrap());
    assert_eq!(
        validation::deadline(&request, started, 1000, Duration::from_secs(5)).unwrap(),
        started + Duration::from_millis(1)
    );
    request.metadata_mut().remove("grpc-timeout");
    assert_eq!(
        validation::deadline(&request, started, 1000, Duration::from_secs(5)).unwrap(),
        started + Duration::from_millis(2)
    );
    request.get_mut().deadline_unix_millis = None;
    assert_eq!(
        validation::deadline(&request, started, 1000, Duration::from_millis(3)).unwrap(),
        started + Duration::from_millis(3)
    );
    request
        .metadata_mut()
        .insert("grpc-timeout", "invalid".parse().unwrap());
    assert_eq!(
        validation::deadline(&request, started, 1000, Duration::from_secs(5))
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
}

#[test]
fn configuration_rejects_public_bind_bad_tokens_and_unowned_service_names() {
    assert!(args().validate().is_ok());
    let mut config = args();
    config.listen = "0.0.0.0:5000".parse().unwrap();
    assert!(config.validate().is_err());
    config = args();
    config.token = "short".to_owned();
    assert!(config.validate().is_err());
    config = args();
    config.services.push("foreign/service".to_owned());
    assert!(config.validate().is_err());
    config = args();
    config.services.push("optimization/workloads".to_owned());
    assert!(config.validate().is_err());
}
