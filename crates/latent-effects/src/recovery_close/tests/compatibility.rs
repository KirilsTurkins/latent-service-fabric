//! Incoming v1/v2 management formats keep their exact closed legacy body.
use super::*;
use crate::dispatch::{EffectManagementFact, EffectManagementStamp};

#[test]
fn legacy_v1_v2_shapes_round_trip_exactly_and_refuse_close_field_smuggling() {
    let fixture = Fixture::new(true);
    let original =
        EffectRecord::decode(&fixture.row(&effect_row_key(&fixture.effect).unwrap())).unwrap();
    let mut managed = original.clone();
    managed
        .stamp_managed(EffectManagementStamp {
            sequence: 1,
            operation_digest: "b".repeat(64),
            fact: EffectManagementFact::RedriveScheduled,
            original_attempt: None,
            provider_receipt: None,
            provider_observed_at_millis: None,
            observed_at_millis: original.latest().unwrap().observed_at_millis,
        })
        .unwrap();
    for (record, version) in [(original, 1), (managed, 2)] {
        let encoded = record.encode().unwrap();
        assert_eq!(encoded[4], version);
        let decoded = EffectRecord::decode(&encoded).unwrap();
        assert_eq!(decoded, record);
        assert_eq!(decoded.encode().unwrap(), encoded);
        let body: serde_json::Value = serde_json::from_slice(&encoded[5..]).unwrap();
        assert!(body.get("record").is_none());
        assert!(body.get("receipt_digest").is_none());
        assert!(body.get("recovery_close").is_none());
        for marker in [serde_json::Value::Null, serde_json::json!(vec![1; 32])] {
            let mut forged = body.clone();
            forged["recovery_close"] = marker;
            let mut bytes = encoded[..5].to_vec();
            bytes.extend(serde_json::to_vec(&forged).unwrap());
            assert!(EffectRecord::decode(&bytes).is_err());
        }
    }
}

#[test]
fn v3_close_envelope_rejects_zero_links_unknown_fields_and_legacy_header_downgrades() {
    let fixture = Fixture::new(false);
    let prepared = fixture.prepare(&fixture.plan());
    fixture.store.apply(prepared.batch).unwrap();
    let encoded = fixture.row(&effect_row_key(&fixture.effect).unwrap());
    assert!(encoded.starts_with(b"LER\0\x03"));
    let record = EffectRecord::decode(&encoded).unwrap();
    assert_eq!(record.encode().unwrap(), encoded);
    let body: serde_json::Value = serde_json::from_slice(&encoded[5..]).unwrap();
    assert!(body["record"].get("recovery_close").is_none());
    assert_eq!(body.as_object().unwrap().len(), 2);
    for version in [1, 2, 4] {
        let mut downgraded = encoded.clone();
        downgraded[4] = version;
        assert!(EffectRecord::decode(&downgraded).is_err());
    }
    for (field, value) in [
        ("receipt_digest", serde_json::json!(vec![0; 32])),
        ("extra", serde_json::Value::Null),
    ] {
        let mut changed = body.clone();
        changed[field] = value;
        let mut bytes = encoded[..5].to_vec();
        bytes.extend(serde_json::to_vec(&changed).unwrap());
        assert!(EffectRecord::decode(&bytes).is_err());
    }
}
