#[test]
fn generated_protobuf_and_domain_round_trips_preserve_phase_one_fields() {
    let domain = domain_request();
    let proto_request = invocation_request_to_proto(&domain);
    assert_eq!(
        invocation_request_from_proto(proto_request.clone()).unwrap(),
        domain
    );

    let mut encoded = proto_request.encode_to_vec();
    encoded.extend_from_slice(&[0x98, 0x06, 0x01]);
    assert_eq!(
        proto::InvokeRequest::decode(encoded.as_slice()).unwrap(),
        proto_request
    );

    for outcome in [success(), declared_error()] {
        let response = response(outcome);
        assert_eq!(
            invocation_response_from_proto(invocation_response_to_proto(&response)).unwrap(),
            response
        );
    }

    let error = PlatformError {
        code: PlatformErrorCode::DependencyFailed,
        message: "dependency unavailable".to_owned(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "retry".to_owned(),
            fields: Metadata::from([("retry_after_millis".to_owned(), "25".to_owned())]),
        }],
    };
    let wire_error = platform_error_to_proto(&error);
    assert_eq!(wire_error.code, "dependency-failed");
    assert_eq!(platform_error_from_proto(wire_error).unwrap(), error);

    let disposition =
        CancelDisposition::AlreadyTerminal(ActivationTerminalState::DependencyFailed);
    assert_eq!(
        cancel_disposition_from_proto(cancel_disposition_to_proto(disposition)).unwrap(),
        disposition
    );
}
