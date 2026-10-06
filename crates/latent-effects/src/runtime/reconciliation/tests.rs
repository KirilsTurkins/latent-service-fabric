use super::*;
use crate::authority::EffectTime;
use crate::dispatch::EffectRecord;
use crate::payload::tests as fixture;

fn request(identity: char, version: [u8; 32]) -> ProviderReconciliationRequest {
    let value = fixture::value();
    let authority = fixture::authority(&value, &identity.to_string().repeat(64));
    let payload = PayloadRecord::new(&authority, value).unwrap();
    let mut record = EffectRecord::committed(&authority).unwrap();
    let attempt = record
        .claim(
            1,
            EffectTime {
                unix_millis: 101,
                continuity_proven: true,
            },
        )
        .unwrap();
    ProviderReconciliationRequest::new(authority, payload, attempt, version).unwrap()
}

#[test]
fn original_attempt_payload_and_version_bind_positive_confirmation() {
    let original = request('a', [1; 32]);
    let foreign = request('b', [1; 32]);
    let confirmed = ProviderConfirmation::new(
        original.attempt().clone(),
        [1; 32],
        "endpoint-incarnation:123:duplicate=1".into(),
        102,
    )
    .unwrap();
    confirmed.validate_for(original.attempt(), [1; 32]).unwrap();
    assert_eq!(
        confirmed.validate_for(foreign.attempt(), [1; 32]),
        Err(AuthorityError::Stale)
    );
    assert_eq!(
        confirmed.validate_for(original.attempt(), [2; 32]),
        Err(AuthorityError::Stale)
    );
    let authority = original.authority().clone();
    let (payload, attempt, version) = original.into_parts();
    payload.verify(&authority).unwrap();
    assert_eq!(payload.effect(), attempt.effect());
    assert_eq!(version, [1; 32]);
    assert!(ProviderReconciliationRequest::new(
        authority,
        payload,
        foreign.attempt().clone(),
        version
    )
    .is_err());
}

#[test]
fn provider_confirmation_bounds_reject_arbitrary_text_and_unknown_versions() {
    let original = request('a', [1; 32]);
    for receipt in [String::new(), "x".repeat(257), "secret\nbody".into()] {
        assert!(
            ProviderConfirmation::new(original.attempt().clone(), [1; 32], receipt, 102).is_err()
        );
    }
    assert!(
        ProviderConfirmation::new(original.attempt().clone(), [0; 32], "receipt".into(), 102)
            .is_err()
    );
    assert!(
        ProviderConfirmation::new(original.attempt().clone(), [1; 32], "receipt".into(), 0)
            .is_err()
    );
}
