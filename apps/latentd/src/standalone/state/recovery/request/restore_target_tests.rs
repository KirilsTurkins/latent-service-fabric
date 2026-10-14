use super::*;
use latent_state::embedded::StoreError;
use latent_state::store_identity::MAXIMUM_ENCODED_BYTES;
use serde_json::{json, Value};

fn request(action: &str) -> Value {
    let root = std::env::temp_dir();
    let mut value = json!({
        "publication":format!("publication:sha256:{}", "1".repeat(64)),
        "request":{"action":action,"file":{"root":root,"name":"original-snapshot"},
            "destinationRoot":root.join("distinct-target"),"operationId":"original-restore",
            "destinationCheckpointRoot":root.join("distinct-checkpoint"),
            "snapshotDigest":format!("sha256:{}", "2".repeat(64)),
            "manifestDigest":format!("sha256:{}", "3".repeat(64))}
    });
    if action == "restore" {
        value["request"]["windowAcknowledgement"] = format!("sha256:{}", "4".repeat(64)).into();
    }
    value
}

fn decode(value: &Value) -> Result<NativeRecoveryRequest, PlatformError> {
    NativeRecoveryRequest::decode(&serde_json::to_vec(value).unwrap())
}

#[test]
fn explicit_restore_target_uses_original_identity_parser_and_unchanged_purposes() {
    let source = StoreIdentity::new("original-source".into()).unwrap();
    for action in ["inspect-restore", "restore"] {
        let mut input = request(action);
        input["request"]["destinationStoreIdentity"] = "explicit-target".into();
        let decoded = decode(&input).unwrap();
        assert_eq!(
            decoded
                .request
                .restore_destination_identity(&source)
                .unwrap(),
            StoreIdentity::new("explicit-target".into()).unwrap()
        );
        assert_eq!(
            decoded.request.purposes(),
            if action == "restore" {
                &["namespace-inspect-restore", "namespace-restore"][..]
            } else {
                &["namespace-inspect-restore"][..]
            }
        );
        for invalid in [
            json!(""),
            json!("x".repeat(129)),
            json!("foreign/path"),
            json!("é"),
            json!("target\n"),
            json!(true),
            json!(42),
            json!({"approved":true}),
        ] {
            input["request"]["destinationStoreIdentity"] = invalid;
            assert!(decode(&input).is_err());
        }
        input["request"]["destinationStoreIdentity"] = "x".repeat(128).into();
        assert_eq!(
            decode(&input)
                .unwrap()
                .request
                .restore_destination_identity(&source)
                .unwrap()
                .as_str()
                .len(),
            128
        );
    }
}

#[test]
fn omitted_restore_target_keeps_original_selection_without_inventing_an_identity() {
    let source = StoreIdentity::new("original-source".into()).unwrap();
    for action in ["inspect-restore", "restore"] {
        let input = request(action);
        assert_eq!(
            decode(&input)
                .unwrap()
                .request
                .restore_destination_identity(&source)
                .unwrap(),
            source
        );
    }
    assert!(Action::Review {}
        .restore_destination_identity(&source)
        .is_err());
}

#[test]
fn oversized_original_restore_identity_allocation_is_refused_before_any_clone() {
    let mut original = String::with_capacity(MAXIMUM_ENCODED_BYTES);
    original.push_str("otherwise-valid-target");
    assert!(original.capacity() >= MAXIMUM_ENCODED_BYTES);
    assert_eq!(
        validated_restore_identity(Some(original)),
        Err(StoreError::Invalid)
    );
    assert_eq!(validated_restore_identity(None), Ok(None));
}

#[test]
fn explicit_restore_target_cannot_supply_grants_cutoffs_or_unknown_fields() {
    for action in ["inspect-restore", "restore"] {
        for field in [
            "approved",
            "grant",
            "deadline",
            "continuity",
            "destinationIdentity",
        ] {
            let mut input = request(action);
            input["request"]["destinationStoreIdentity"] = "explicit-target".into();
            input["request"][field] = true.into();
            assert!(decode(&input).is_err());
        }
    }
}
