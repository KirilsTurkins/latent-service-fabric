use super::*;
use latent_wire::{
    invocation::AuthenticatedInvocationContext,
    management::{
        MAX_WEB_MUTATION_WAIT_MILLIS, MAX_WEB_PREPARATION_WAIT_MILLIS, WEB_EVIDENCE_RPC_PATH,
        WEB_PREPARATION_RPC_PATH, WEB_PUBLICATION_RPC_PATH,
    },
};

#[test]
fn only_exact_web_control_paths_get_separate_bounded_transport_waits() {
    let config = configuration();
    for (path, maximum) in [
        (
            WEB_PREPARATION_RPC_PATH,
            Duration::from_millis(MAX_WEB_PREPARATION_WAIT_MILLIS),
        ),
        (
            WEB_PUBLICATION_RPC_PATH,
            Duration::from_millis(MAX_WEB_MUTATION_WAIT_MILLIS),
        ),
        (
            WEB_EVIDENCE_RPC_PATH,
            Duration::from_millis(MAX_WEB_MUTATION_WAIT_MILLIS),
        ),
        (
            "/latent.control.v1.ReleaseService/ChangeWebLifecycle",
            config.request_timeout,
        ),
        (
            "/latent.control.v1.ReleaseService/PrepareWebPublication/",
            config.request_timeout,
        ),
        (
            "/latent.invocation.v1.InvocationService/Invoke",
            config.request_timeout,
        ),
    ] {
        let mut request = request(path);
        request
            .headers_mut()
            .insert("grpc-timeout", "99999999S".parse().unwrap());
        let before = std::time::Instant::now();
        auth::authenticate(&mut request, &config, &SystemActivationClock).unwrap();
        let after = std::time::Instant::now();
        let expires = request
            .extensions()
            .get::<AuthenticatedInvocationContext>()
            .unwrap()
            .transport_expires_at()
            .unwrap();
        assert!(expires >= before + maximum && expires <= after + maximum);
        let mut bounded = tonic::Request::new(());
        bounded.set_timeout(maximum);
        assert_eq!(
            request.headers()["grpc-timeout"].as_bytes(),
            bounded
                .metadata()
                .get("grpc-timeout")
                .unwrap()
                .as_encoded_bytes()
        );
    }
}

#[test]
fn preparation_keeps_shorter_transport_timeout_and_requires_authentication() {
    let config = configuration();
    let mut request = request(WEB_PREPARATION_RPC_PATH);
    request
        .headers_mut()
        .insert("grpc-timeout", "17m".parse().unwrap());
    let before = std::time::Instant::now();
    auth::authenticate(&mut request, &config, &SystemActivationClock).unwrap();
    let after = std::time::Instant::now();
    let expires = request
        .extensions()
        .get::<AuthenticatedInvocationContext>()
        .unwrap()
        .transport_expires_at()
        .unwrap();
    assert!(
        expires >= before + Duration::from_millis(17)
            && expires <= after + Duration::from_millis(17)
    );
    request.headers_mut().remove("authorization");
    assert_eq!(
        auth::authenticate(&mut request, &config, &SystemActivationClock)
            .unwrap_err()
            .code(),
        tonic::Code::Unauthenticated
    );
}
