use super::*;

#[test]
fn publication_receipts_preserve_all_outcomes_and_legacy_component_meaning() {
    #[derive(Clone, PartialEq, prost::Message)]
    struct LegacyPin {
        #[prost(string, tag = "2")]
        revision_id: String,
        #[prost(string, tag = "3")]
        release_digest: String,
        #[prost(uint64, tag = "4")]
        route_generation: u64,
    }
    for outcome in [
        success(),
        declared(),
        failure(PlatformErrorCode::DependencyFailed),
    ] {
        let mut value = response(outcome);
        let publication = format!("publication:sha256:{}", "a".repeat(64));
        let pin = value.receipt.resolved_revision.as_mut().unwrap();
        pin.publication_id = Some(publication.parse().unwrap());
        pin.route_generation = RouteGeneration(u64::MAX);
        let wire = invocation_response_to_proto(&value).unwrap();
        assert_eq!(wire.publication_id.as_deref(), Some(publication.as_str()));
        let legacy = LegacyPin::decode(wire.encode_to_vec().as_slice()).unwrap();
        assert_eq!(legacy.release_digest, "sha256:1234");
        assert_eq!(legacy.route_generation, u64::MAX);
        assert_eq!(invocation_response_from_proto(wire.clone()).unwrap(), value);
        let public = public_invocation_response_to_proto(value, &InvocationLimits::default());
        assert_eq!(public.publication_id, wire.publication_id);
        assert_eq!(public.release_digest, wire.release_digest);
    }
}

#[test]
fn present_invalid_publications_never_become_absent_or_create_a_missing_pin() {
    let wire = invocation_response_to_proto(&response(success())).unwrap();
    assert!(invocation_response_from_proto(wire.clone())
        .unwrap()
        .receipt
        .resolved_revision
        .unwrap()
        .publication_id
        .is_none());
    for invalid in [
        String::new(),
        "sha256:1234".into(),
        format!("publication:sha256:{}", "A".repeat(64)),
        format!("publication:sha256:{}\n", "a".repeat(64)),
    ] {
        let mut changed = wire.clone();
        changed.publication_id = Some(invalid);
        assert!(invocation_response_from_proto(changed).is_err());
    }
    let mut unresolved = response(failure(PlatformErrorCode::RouteUnavailable));
    unresolved.receipt.resolved_revision = None;
    let mut wire = invocation_response_to_proto(&unresolved).unwrap();
    assert!(wire.publication_id.is_none());
    wire.publication_id = Some(format!("publication:sha256:{}", "a".repeat(64)));
    assert!(invocation_response_from_proto(wire).is_err());
}
