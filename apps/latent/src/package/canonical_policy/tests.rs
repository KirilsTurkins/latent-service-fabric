use super::*;

fn vector() -> Value {
    serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/signing-policy/canonical-vectors.json"
    )))
    .unwrap()
}

fn run(value: &Value) -> Result<Value, Failure> {
    canonicalize(
        &serde_json::to_vec(&value["publisherInput"]).unwrap(),
        &serde_json::to_vec(&value["builderInput"]).unwrap(),
    )
}

#[test]
fn shared_multi_key_vectors_match_the_runtime_canonical_bytes_and_digests() {
    let value = vector();
    let actual = run(&value).unwrap();
    for role in ["publisher", "builder"] {
        assert_eq!(actual[role], value["expected"][role]);
    }
    assert_eq!(actual["trustEstablished"], false);
    assert_eq!(actual["evidenceCreated"], false);
    assert_eq!(actual["executionAuthorized"], false);
}

#[test]
fn independent_key_and_requirement_permutations_keep_exact_policy_identity() {
    let mut value = vector();
    let first = run(&value).unwrap();
    for role in ["publisherInput", "builderInput"] {
        value[role]["keys"].as_array_mut().unwrap().reverse();
    }
    value["builderInput"]["requirements"]
        .as_array_mut()
        .unwrap()
        .reverse();
    assert_eq!(run(&value).unwrap(), first);
    // Requirements are alternatives, never coalesced into universal builder trust.
    let canonical: Value =
        serde_json::from_str(first["builder"]["canonicalJson"].as_str().unwrap()).unwrap();
    assert_eq!(canonical["requirements"].as_array().unwrap().len(), 2);
    assert!(canonical["requirements"]
        .as_array()
        .unwrap()
        .iter()
        .all(|row| row["sourceRevision"]
            .as_str()
            .is_some_and(|revision| revision.len() == 40)));
}

#[test]
fn duplicate_or_conflicting_keys_requirements_and_encodings_fail_without_echo() {
    for (role, field) in [
        ("publisherInput", "keys"),
        ("builderInput", "keys"),
        ("builderInput", "requirements"),
    ] {
        let mut value = vector();
        let duplicate = value[role][field][0].clone();
        value[role][field].as_array_mut().unwrap().push(duplicate);
        assert_eq!(
            run(&value).unwrap_err().data["reason"],
            "signature-invalid-policy"
        );
    }
    let mut value = vector();
    value["builderInput"]["keys"][1]["publicKey"] =
        value["builderInput"]["keys"][0]["publicKey"].clone();
    assert!(run(&value).is_err());
    for invalid in [
        "hostile-secret\r\n",
        "not-base64",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    ] {
        let mut value = vector();
        value["builderInput"]["keys"][0]["publicKey"] = json!(invalid);
        let failure = run(&value).unwrap_err();
        assert_eq!(failure.data["stage"], "builder-policy");
        assert!(!serde_json::to_string(&failure.data)
            .unwrap()
            .contains(invalid));
    }
}

#[test]
fn inventories_and_duplicate_json_fields_remain_bounded_and_fail_closed() {
    let mut value = vector();
    let key = value["publisherInput"]["keys"][0].clone();
    value["publisherInput"]["keys"] = json!(vec![key; 65]);
    assert_eq!(
        run(&value).unwrap_err().data["reason"],
        "signature-resource-limit"
    );
    let mut value = vector();
    let requirement = value["builderInput"]["requirements"][0].clone();
    value["builderInput"]["requirements"] = json!(vec![requirement; 65]);
    assert_eq!(
        run(&value).unwrap_err().data["reason"],
        "signature-resource-limit"
    );
    let builder = serde_json::to_vec(&vector()["builderInput"]).unwrap();
    assert!(canonicalize(br#"{"formatVersion":1,"formatVersion":1}"#, &builder).is_err());
    assert_eq!(
        canonicalize(&vec![b' '; 65_537], &builder)
            .unwrap_err()
            .data["reason"],
        "signature-resource-limit"
    );
}
