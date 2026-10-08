use super::*;
use latent_activation::ActivationSuccess;
use latent_core::{ActivationId, DeclaredError, Metadata};

fn success(size: usize) -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: vec![b' '; size],
        output_media_type: http::VALUE_MEDIA_TYPE.into(),
        consumption: BudgetConsumption::default(),
        committed_state_version: None,
        effect_ids: vec![],
        metadata: Metadata::new(),
    })
}
fn rejection() -> ActivationOutcome {
    ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "business-rejection".into(),
            message: "original message".into(),
            payload: b"[]".to_vec(),
            media_type: http::VALUE_MEDIA_TYPE.into(),
            metadata: Metadata::new(),
        },
        consumption: BudgetConsumption::default(),
    }
}
fn receipt(outcome: ActivationOutcome) -> ActivationReceipt {
    ActivationReceipt {
        activation_id: ActivationId("http-transaction-test".into()),
        resolved_revision: None,
        outcome,
        transaction: None,
        delivery_failure: None,
        result_delivery_fence: None,
    }
}

#[test]
fn required_http_replay_forms_reject_oversize_media_and_cookie_fields_before_commit() {
    let codec = HttpCommandResultCodec;
    assert_eq!(codec.format(), CanonicalCommandResult.format());
    assert!(matches!(
        codec.validate(&success(RESULT_BYTES)),
        Ok(CommandOutput::Success(_))
    ));
    assert!(codec.validate(&success(RESULT_BYTES + 1)).is_err());
    let mut wrong_media = success(2);
    let ActivationOutcome::Succeeded(value) = &mut wrong_media else {
        unreachable!()
    };
    value.output_media_type = "text/html".into();
    assert!(codec.validate(&wrong_media).is_err());
    assert!(matches!(
        codec.validate(&rejection()),
        Ok(CommandOutput::Rejection { .. })
    ));
    for field in [
        "set-cookie",
        "authorization",
        "csrf-token",
        "lsf-query-view-token",
    ] {
        let mut rejected = rejection();
        let ActivationOutcome::DeclaredError { error, .. } = &mut rejected else {
            unreachable!()
        };
        error
            .metadata
            .insert(field.into(), "historical credential".into());
        assert!(codec.validate(&rejected).is_err(), "{field}");
    }
}

#[test]
fn framework_metadata_is_excluded_and_maximum_result_has_a_bounded_json_envelope() {
    let mut outcome = success(RESULT_BYTES);
    let ActivationOutcome::Succeeded(value) = &mut outcome else {
        unreachable!()
    };
    value
        .metadata
        .insert("set-cookie".into(), "old-session=secret".into());
    let mut token = b"NV\x02".to_vec();
    token.resize(latent_state::session::version::VIEW_TOKEN_BYTES, 1);
    value.metadata.insert(
        latent_node::transaction_runtime::query::VIEW_METADATA.into(),
        STANDARD.encode(&token),
    );
    let CommandOutput::Success(stored) = HttpCommandResultCodec.validate(&outcome).unwrap() else {
        unreachable!()
    };
    assert!(stored.metadata.is_empty());
    let receipt = receipt(outcome);
    let (status, response) = response(&receipt).unwrap();
    assert_eq!(status, 200);
    let bytes = serde_json::to_vec(&response).unwrap();
    assert!(bytes.len() <= http::MAX_RESPONSE_BODY);
    let frame: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(frame["state-view"], STANDARD.encode(&token));
    assert_eq!(frame["result"]["media-type"], http::VALUE_MEDIA_TYPE);
    assert!(!String::from_utf8(bytes)
        .unwrap()
        .contains("old-session=secret"));
}

#[test]
fn query_requires_the_complete_host_view_token_and_preserves_declared_error() {
    for token in [
        String::new(),
        STANDARD.encode([1u8; 16]),
        STANDARD.encode([1u8; 67]),
        "invalid".into(),
    ] {
        let mut outcome = rejection();
        let ActivationOutcome::DeclaredError { error, .. } = &mut outcome else {
            unreachable!()
        };
        error.metadata.insert(
            latent_node::transaction_runtime::query::VIEW_METADATA.into(),
            token,
        );
        assert!(response(&receipt(outcome)).is_err());
    }
    let mut token = b"NV\x02".to_vec();
    token.resize(latent_state::session::version::VIEW_TOKEN_BYTES, 1);
    let mut outcome = rejection();
    let ActivationOutcome::DeclaredError { error, .. } = &mut outcome else {
        unreachable!()
    };
    error.metadata.insert(
        latent_node::transaction_runtime::query::VIEW_METADATA.into(),
        STANDARD.encode(&token),
    );
    let receipt = receipt(outcome);
    let (status, response) = response(&receipt).unwrap();
    assert_eq!(status, 422);
    assert_eq!(
        response.result.unwrap().error_message,
        Some("original message")
    );
    assert!(response.command_id.is_none());
    assert!(response.result_expires_at.is_none());
}
