use super::*;
use latent_activation::ActivationSuccess;
use latent_core::{BudgetConsumption, Metadata};

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

#[test]
fn promised_http_result_rejects_unrepresentable_body_media_and_headers() {
    let validator = HttpResultValidator;
    assert!(validator.validate(&success(RESULT_BYTES)).is_ok());
    let mut hosted = success(2);
    let ActivationOutcome::Succeeded(value) = &mut hosted else {
        unreachable!()
    };
    value.metadata.insert("cell-id".into(), "cell-1".into());
    value
        .metadata
        .insert("cell-disposition".into(), "released".into());
    assert!(validator.validate(&hosted).is_ok());
    assert!(validator.validate(&success(RESULT_BYTES + 1)).is_err());
    let mut outcome = success(2);
    let ActivationOutcome::Succeeded(value) = &mut outcome else {
        unreachable!()
    };
    value.output_media_type = "text/html".into();
    assert!(validator.validate(&outcome).is_err());
    for name in ["set-cookie", "csrf-token", "authorization", "cache-control"] {
        let mut outcome = success(2);
        let ActivationOutcome::Succeeded(value) = &mut outcome else {
            unreachable!()
        };
        value.metadata.insert(name.into(), "private".into());
        assert!(validator.validate(&outcome).is_err());
    }
}

#[test]
fn durable_receipt_status_is_independent_of_application_body_availability() {
    for (outcome, status, disposition) in [
        (t::CommandOutcome::Committed, 200, "committed"),
        (t::CommandOutcome::Rejected, 422, "rejected"),
        (t::CommandOutcome::Aborted, 409, "aborted"),
        (
            t::CommandOutcome::RecoveryRequired,
            503,
            "recovery-required",
        ),
    ] {
        let (actual, body) = project(
            t::LookupCommandResponse {
                command: Some(t::CommandInspection {
                    command_id: "c".repeat(64),
                    attempt_id: "1".into(),
                    outcome: outcome as i32,
                    ..Default::default()
                }),
            }
            .into(),
        )
        .unwrap();
        assert_eq!(
            (actual, body.disposition, body.representation),
            (status, disposition, "receipt-only")
        );
        assert!(body.result.is_none());
    }
}
