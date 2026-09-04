#[tokio::test(flavor = "current_thread")]
async fn public_platform_failures_use_fixed_messages_and_allowlisted_details() {
    let internal = PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "failed at /srv/private/component.wasm with token=super-secret".to_owned(),
        retryable: true,
        details: vec![
            ErrorDetail {
                kind: "resource.limit".to_owned(),
                fields: Metadata::from([
                    ("resource".to_owned(), "memory".to_owned()),
                    ("requested".to_owned(), "2048".to_owned()),
                    ("limit".to_owned(), "1024".to_owned()),
                    ("credential".to_owned(), "super-secret".to_owned()),
                    ("path".to_owned(), "/srv/private".to_owned()),
                ]),
            },
            ErrorDetail {
                kind: "engine.backtrace".to_owned(),
                fields: Metadata::from([("frame".to_owned(), "secret-frame".to_owned())]),
            },
        ],
    };
    let runtime = Arc::new(FakeRuntime::new(ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::ResourceExhausted,
        error: internal,
        consumption: consumption(),
    }));
    let service = adapter(runtime, InvocationLimits::default());
    let response = InvocationService::invoke(&service, authenticated("tenant-a", request()))
        .await
        .unwrap()
        .into_inner();

    let error = match response.result {
        Some(proto::invoke_response::Result::PlatformFailure(error)) => error,
        other => panic!("expected platform failure, got {other:?}"),
    };
    assert_eq!(error.code, "resource-exhausted");
    assert_eq!(
        error.message,
        "the invocation exceeded an available resource limit"
    );
    assert_eq!(error.detail_items.len(), 1);
    assert_eq!(error.detail_items[0].fields.len(), 3);
    assert!(!error.detail_items[0].fields.contains_key("credential"));
    assert!(!error.detail_items[0].fields.contains_key("path"));
    let rendered = format!("{error:?}");
    for forbidden in ["super-secret", "/srv/private", "secret-frame"] {
        assert!(!rendered.contains(forbidden));
    }
}

#[tokio::test(flavor = "current_thread")]
async fn cancel_returns_every_deterministic_disposition() {
    let runtime = Arc::new(FakeRuntime::new(success()));
    let service = adapter(Arc::clone(&runtime), InvocationLimits::default());
    let mut invoke_request = request();
    invoke_request.activation_id = Some("activation-cancel".to_owned());
    InvocationService::invoke(&service, authenticated("tenant-a", invoke_request))
        .await
        .unwrap();

    for (domain, wire, terminal) in [
        (
            CancelDisposition::Accepted,
            proto::CancelDisposition::Accepted,
            None,
        ),
        (
            CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed),
            proto::CancelDisposition::AlreadyTerminal,
            Some("completed"),
        ),
        (
            CancelDisposition::NotFound,
            proto::CancelDisposition::NotFound,
            None,
        ),
    ] {
        runtime.set_cancellation_disposition(domain);
        let response = InvocationService::cancel(
            &service,
            authenticated(
                "tenant-a",
                proto::CancelRequest {
                    activation_id: "activation-cancel".to_owned(),
                    reason: "caller cancelled".to_owned(),
                },
            ),
        )
        .await
        .unwrap()
        .into_inner();
        assert_eq!(
            proto::CancelDisposition::try_from(response.disposition).unwrap(),
            wire
        );
        assert_eq!(response.terminal_state.as_deref(), terminal);
    }
}

#[test]
fn generated_messages_keep_hardened_service_and_descriptor_contract() {
    assert!(!latent_rpc::FILE_DESCRIPTOR_SET.is_empty());
    assert_eq!(
        <InvocationServiceServer<InvocationServiceAdapter<FakeRuntime>> as
            tonic::server::NamedService>::NAME,
        "latent.invocation.v1.InvocationService"
    );
}
