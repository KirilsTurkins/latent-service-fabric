use super::*;

#[test]
fn output_failure_preserves_managed_recovery_without_bulk_response() {
    let data = json!({
        "recovery":{"family":"deployment","tenant":"tests","operationId":"apply-blue",
            "deploymentId":"blue","expectedGeneration":"0","expectedStateVersion":u64::MAX.to_string()},
        "auditAck":{"status":"durable","attemptSequence":"12"},
        "deployment":{"manifest":{"irrelevant":"bulk"}},
        "evidence":[{"payload":"must not retain"}]
    });
    let retained = receipt(&data);
    assert_eq!(retained["recovery"], data["recovery"]);
    assert_eq!(retained["auditAck"], data["auditAck"]);
    assert!(retained.get("deployment").is_none());
    assert!(retained.get("evidence").is_none());
    assert!(serde_json::to_vec(&retained).unwrap().len() < 512);
}

#[test]
fn local_output_failure_retains_completed_remote_result_and_exact_receipt() {
    let mut failure = Failure::local(
        "payload-output-failed",
        "The payload file could not be written.",
    );
    failure.request_dispatched = true;
    failure.outcome_known = true;
    failure.data = json!({
        "activationId": "known",
        "resolvedRevision": {"revisionId":"revision", "releaseDigest":"sha256:release",
            "routeGeneration":u64::MAX.to_string()},
        "remoteCompleted": true,
        "payload": {"encoding":"base64", "data":"AP8=", "byteLength":"2",
            "mediaType":"application/octet-stream"}
    });
    let outcome = Outcome::from(failure);
    let document = outcome.document("invoke");
    assert_eq!(outcome.exit_code(), 2);
    assert_eq!(document["category"], "local-error");
    assert_eq!(document["requestDispatched"], true);
    assert_eq!(document["outcomeKnown"], true);
    assert_eq!(document["data"]["remoteCompleted"], true);
    assert_eq!(document["data"]["payload"]["data"], "AP8=");
    assert_eq!(
        document["data"]["resolvedRevision"]["routeGeneration"],
        u64::MAX.to_string()
    );
    assert_eq!(receipt(&outcome.data)["activationId"], "known");
    assert_eq!(
        receipt(&outcome.data)["resolvedRevision"],
        outcome.data["resolvedRevision"]
    );
    assert!(receipt(&outcome.data).get("payload").is_none());
}

#[test]
fn unknown_outcome_and_absent_identity_survive_document_conversion() {
    for dispatched in [false, true] {
        let mut failure = Failure::interrupted(dispatched);
        failure.data = json!({"activationId":null});
        let outcome = Outcome::from(failure);
        let document = outcome.document("invoke");
        assert_eq!(outcome.exit_code(), 130);
        assert_eq!(document["requestDispatched"], dispatched);
        assert_eq!(document["outcomeKnown"], !dispatched);
        assert!(document["data"]["activationId"].is_null());
        assert!(document["data"].get("disposition").is_none());
    }
}

#[test]
fn requested_control_characters_are_escaped_and_roundtrip_as_data() {
    let text = "domain\u{1b}[31m\n\r\0\"quoted\" λ";
    let outcome = Outcome::domain_error(json!({"declaredError":{"code":text}}));
    let document = outcome.document("invoke");
    let mut output = BoundedOutput(Vec::new());
    serde_json::to_writer_pretty(&mut output, &document).unwrap();
    assert!(!output.0.contains(&0x1b));
    assert!(!output.0.contains(&0));
    let decoded: Value = serde_json::from_slice(&output.0).unwrap();
    assert_eq!(decoded["data"]["declaredError"]["code"], text);
    assert_eq!(decoded["category"], "declared-error");
    assert!(decoded["error"].is_null());
}
