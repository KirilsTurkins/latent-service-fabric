#[tokio::test(flavor = "current_thread")]
async fn cancellation_is_fail_closed_before_status_publication() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    runtime.set_pending(true);
    let service = adapter(Arc::clone(&runtime), InvocationLimits::default());
    let mut invoke_request = request();
    invoke_request.activation_id = Some("activation-owned".to_owned());

    let invocation_service = service.clone();
    let invocation = tokio::spawn(async move {
        InvocationService::invoke(
            &invocation_service,
            authenticated("tenant-a", invoke_request),
        )
        .await
    });
    let activation_id = ActivationId("activation-owned".to_owned());
    runtime.wait_until_registered(&activation_id).await;

    let status_error = InvocationService::get_activation(
        &service,
        authenticated(
            "tenant-b",
            proto::GetActivationRequest {
                activation_id: activation_id.0.clone(),
            },
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(status_error.code(), Code::PermissionDenied);

    let cancel_error = InvocationService::cancel(
        &service,
        authenticated(
            "tenant-b",
            proto::CancelRequest {
                activation_id: activation_id.0.clone(),
                reason: "not mine".to_owned(),
            },
        ),
    )
    .await
    .unwrap_err();
    assert_eq!(cancel_error.code(), Code::PermissionDenied);
    assert!(runtime.cancellations().is_empty());

    invocation.abort();
    assert!(invocation.await.unwrap_err().is_cancelled());
    tokio::task::yield_now().await;
    assert!(runtime.token(&activation_id).is_cancelled());
}

#[tokio::test(flavor = "current_thread")]
async fn dropped_transport_cancels_only_its_own_activation() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    runtime.set_pending(true);
    let service = adapter(Arc::clone(&runtime), InvocationLimits::default());

    let mut first_request = request();
    first_request.activation_id = Some("activation-a".to_owned());
    let first_service = service.clone();
    let first = tokio::spawn(async move {
        InvocationService::invoke(&first_service, authenticated("tenant-a", first_request)).await
    });

    let mut second_request = request();
    second_request.activation_id = Some("activation-b".to_owned());
    let second_service = service.clone();
    let second = tokio::spawn(async move {
        InvocationService::invoke(&second_service, authenticated("tenant-a", second_request)).await
    });

    let first_id = ActivationId("activation-a".to_owned());
    let second_id = ActivationId("activation-b".to_owned());
    runtime.wait_until_registered(&first_id).await;
    runtime.wait_until_registered(&second_id).await;

    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    tokio::task::yield_now().await;
    assert!(runtime.token(&first_id).is_cancelled());
    assert!(!runtime.token(&second_id).is_cancelled());

    runtime.release_pending();
    let _response = second.await.unwrap().unwrap();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn grpc_timeout_is_propagated_and_actively_cancels_the_activation() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    runtime.set_pending(true);
    let service = adapter(Arc::clone(&runtime), InvocationLimits::default());
    let mut invoke_request = request();
    invoke_request.activation_id = Some("activation-deadline".to_owned());
    invoke_request.deadline_unix_millis = None;
    let mut transport_request = authenticated("tenant-a", invoke_request);
    transport_request.set_timeout(Duration::from_millis(50));

    let invocation_service = service.clone();
    let invocation = tokio::spawn(async move {
        InvocationService::invoke(&invocation_service, transport_request).await
    });
    let activation_id = ActivationId("activation-deadline".to_owned());
    runtime.wait_until_registered(&activation_id).await;
    assert_eq!(
        runtime.invocations()[0].request.deadline_unix_millis,
        Some(1_050)
    );

    tokio::time::advance(Duration::from_millis(50)).await;
    let error = invocation.await.unwrap().unwrap_err();
    assert_eq!(error.code(), Code::DeadlineExceeded);
    assert!(runtime.token(&activation_id).is_cancelled());
}
