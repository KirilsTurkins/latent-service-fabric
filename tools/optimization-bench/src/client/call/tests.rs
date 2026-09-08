use super::*;

fn row() -> Attempt {
    let plan = super::super::plan::tests::fixture();
    Offer {
        phase: "measured",
        index: 0,
        origin: Instant::now(),
        scheduled: 0,
        absolute_deadline: 123,
        deadline: 100,
        quantization: 0,
    }
    .row(&plan, "invalid-response")
}

fn success(id: &str, payload: &[u8]) -> proto::InvokeResponse {
    proto::InvokeResponse {
        activation_id: id.into(),
        revision_id: "revision".into(),
        release_digest: "release".into(),
        route_generation: 1,
        consumption: Some(proto::BudgetConsumption::default()),
        result: Some(proto::invoke_response::Result::Success(proto::Success {
            payload: payload.to_vec(),
            media_type: MEDIA.into(),
            ..Default::default()
        })),
    }
}

#[test]
fn semantic_and_identity_mismatches_are_recorded_as_received_failures() {
    let mut row = row();
    classify(
        &mut row,
        success("foreign", br#"["test"]"#),
        br#"["test"]"#,
        false,
    );
    assert!(row.rpc_received);
    assert_eq!(row.outcome, "invalid-response");
    let id = row.activation_id.clone();
    classify(
        &mut row,
        success(&id, br#"["different"]"#),
        br#"["test"]"#,
        false,
    );
    assert_eq!(row.semantic_match, Some(false));
    assert_eq!(
        row.response.as_ref().unwrap()["payload_sha256"],
        digest(br#"["different"]"#)
    );
    classify(
        &mut row,
        success(&id, br#"["test"]"#),
        br#"["test"]"#,
        false,
    );
    assert_eq!(row.outcome, "success");
    assert_eq!(row.semantic_match, Some(true));
}

#[test]
fn platform_deadline_failure_preserves_measured_consumption_without_private_message() {
    let mut row = row();
    let response = proto::InvokeResponse {
        activation_id: row.activation_id.clone(),
        result: Some(proto::invoke_response::Result::PlatformFailure(
            proto::PlatformError {
                code: "deadline-exceeded".into(),
                message: "PRIVATE-TEXT".into(),
                ..Default::default()
            },
        )),
        consumption: Some(proto::BudgetConsumption {
            wall_time_micros: 1400,
            ..Default::default()
        }),
        ..Default::default()
    };
    classify(&mut row, response, b"[]", false);
    assert_eq!(row.outcome, "platform-failure");
    assert_eq!(
        row.response.as_ref().unwrap()["consumption"]["wall_time_micros"],
        "1400"
    );
    assert!(!serde_json::to_string(&row)
        .unwrap()
        .contains("PRIVATE-TEXT"));
}

#[test]
fn native_absent_guest_consumption_is_preserved_and_lsf_absence_is_invalid() {
    let mut row = row();
    let mut response = success(&row.activation_id, b"[]");
    response.consumption = None;
    classify(&mut row, response.clone(), b"[]", true);
    assert_eq!(row.outcome, "success");
    assert!(row.response.as_ref().unwrap()["consumption"].is_null());
    classify(&mut row, response, b"[]", false);
    assert_eq!(row.outcome, "invalid-response");
}

#[test]
fn actual_grpc_timeout_encoding_is_retained_at_short_and_long_budgets() {
    for remaining in [1, 999_999, 1_000_000, 10_000_000, 5_000_000_000] {
        let mut request = tonic::Request::new(());
        request.set_timeout(Duration::from_nanos(remaining));
        let (header, decoded) = encoded_timeout(&request);
        assert!(!header.is_empty());
        assert!(decoded <= remaining);
        assert!(remaining - decoded < 1000);
    }
}
