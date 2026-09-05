#[tokio::test(flavor = "current_thread")]
async fn generated_client_and_server_cover_invoke_cancel_and_status_in_process() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    let service = adapter(Arc::clone(&runtime), InvocationLimits::default());
    let mut client = InvocationServiceClient::new(service.clone().into_server());

    let invoke = client
        .invoke(authenticated("tenant-a", request()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(invoke.activation_id, "activation-runtime-0000");
    assert_eq!(invoke.revision_id, "revision-1");
    assert_eq!(invoke.route_generation, 42);
    assert!(matches!(
        invoke.result,
        Some(proto::invoke_response::Result::Success(_))
    ));

    let status = client
        .get_activation(authenticated(
            "tenant-a",
            proto::GetActivationRequest {
                activation_id: invoke.activation_id.clone(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(status.terminal_state.as_deref(), Some("completed"));
    assert_eq!(status.final_consumption, Some(consumption_to_proto(&consumption())));

    let cancellation = client
        .cancel(authenticated(
            "tenant-a",
            proto::CancelRequest {
                activation_id: invoke.activation_id,
                reason: "caller cancelled".to_owned(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        proto::CancelDisposition::try_from(cancellation.disposition).unwrap(),
        proto::CancelDisposition::Accepted
    );
}

#[tokio::test(flavor = "current_thread")]
async fn validation_and_authentication_fail_before_the_runtime() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    let mut limits = InvocationLimits::default();
    limits.max_payload_bytes = 5;
    let service = adapter(Arc::clone(&runtime), limits);

    let unauthenticated = InvocationService::invoke(&service, tonic::Request::new(request()))
        .await
        .unwrap_err();
    assert_eq!(unauthenticated.code(), Code::Unauthenticated);

    let mut forged = request();
    forged.metadata.insert(
        "latent.principal.subject".to_owned(),
        "forged-administrator".to_owned(),
    );
    assert_eq!(
        InvocationService::invoke(&service, authenticated("tenant-a", forged))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );

    let mut oversized = request();
    oversized.payload = b"123456".to_vec();
    assert_eq!(
        InvocationService::invoke(&service, authenticated("tenant-a", oversized))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );

    let mut expired = request();
    expired.deadline_unix_millis = Some(999);
    assert_eq!(
        InvocationService::invoke(&service, authenticated("tenant-a", expired))
            .await
            .unwrap_err()
            .code(),
        Code::DeadlineExceeded
    );

    let mut missing_target = request();
    missing_target.target = None;
    assert_eq!(
        InvocationService::invoke(&service, authenticated("tenant-a", missing_target))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );

    let mut excessive_budget = request();
    excessive_budget.budget.as_mut().unwrap().cpu_fuel = u64::MAX;
    assert_eq!(
        InvocationService::invoke(&service, authenticated("tenant-a", excessive_budget))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );

    assert!(runtime.invocations().is_empty());
}
