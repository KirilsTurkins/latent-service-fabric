use super::*;
pub(crate) fn input() -> serde_json::Value {
    let owners = owners::tests::input();
    serde_json::json!({"formatVersion":2,"configurationEpoch":1,"storeIdentity":"state-test",
        "checkpointRoot":std::env::temp_dir().join("state-checkpoint"),"startupTimeoutMillis":5_000,
        "store":owners["store"],"native":owners["native"],"dispatcher":owners["dispatcher"],
        "tenantQuotas":[tenant::tests::quota("a")],"operations":[{
        "tenant":"a","componentDigest":format!("sha256:{}","a".repeat(64)),
        "publication":format!("publication:sha256:{}","b".repeat(64)),"contract":"test:state/api@1.0.0",
        "function":"save","deployment":"state","binding":"state","companionDigest":format!("sha256:{}","c".repeat(64)),
        "incarnation":1,"resultPolicy":"owner","statePolicies":["state"]}]})
}

pub(in crate::config) fn data() -> PathBuf {
    std::env::temp_dir().join("state-settings")
}
#[test]
fn installed_constraints_preserve_exact_unsigned_incarnation_and_do_not_contain_grants() {
    let mut value = input();
    value["operations"][0]["incarnation"] = u64::MAX.into();
    let config: StateConfig = serde_json::from_value(value).unwrap();
    let settings = derive(&config, &data()).unwrap();
    assert_eq!(settings.operations[0].incarnation, u64::MAX);
    assert!(!settings.create_if_missing);
    assert_eq!(settings.operations[0].policies, ["state"]);
    assert!(serde_json::from_value::<StateConfig>(serde_json::json!([])).is_err());
    assert!(serde_json::from_value::<StateOperationConfig>(serde_json::json!([])).is_err());
}
#[test]
fn unsafe_present_values_duplicate_targets_and_permission_fields_refuse() {
    for (name, value) in [
        ("entity", serde_json::Value::Null),
        ("grant", true.into()),
        ("continuityProven", true.into()),
    ] {
        let mut wire = input();
        wire["operations"][0][name] = value;
        assert!(serde_json::from_value::<StateConfig>(wire).is_err());
    }
    let mut wire = input();
    wire["operations"][0]["incarnation"] = 0.into();
    assert!(derive(&serde_json::from_value(wire).unwrap(), &data()).is_err());
    let mut config: StateConfig = serde_json::from_value(input()).unwrap();
    config.operations.push(config.operations[0].clone());
    assert!(derive(&config, &data()).is_err());
    config.operations.pop();
    config.operations[0].state_policies.push("state".into());
    assert!(derive(&config, &data()).is_err());
}

#[test]
fn native_effect_installation_pins_reject_implicit_grants_null_and_ambiguous_policy_ids() {
    let effect = serde_json::json!({"requirementsDigest":format!("sha256:{}", "d".repeat(64)),
        "providerId":"http","providerIncarnation":"e".repeat(64),"credentialReference":"effect-secret",
        "stagingBinding":"intent-stage","stagingPolicies":["stage"],"dispatchBinding":"intent-dispatch","dispatchPolicies":["dispatch"]});
    let mut wire = input();
    wire["operations"][0]["deferredHttp"] = effect.clone();
    assert!(derive(&serde_json::from_value(wire.clone()).unwrap(), &data()).is_ok());
    for name in ["enabled", "grant", "credential", "continuityProven"] {
        let mut hostile = wire.clone();
        hostile["operations"][0]["deferredHttp"][name] = true.into();
        assert!(serde_json::from_value::<StateConfig>(hostile).is_err());
    }
    let mut absent = input();
    absent["operations"][0]["deferredHttp"] = serde_json::Value::Null;
    assert!(serde_json::from_value::<StateConfig>(absent).is_err());
    wire["operations"][0]["deferredHttp"]["dispatchPolicies"] =
        serde_json::json!(["dispatch", "dispatch"]);
    assert!(derive(&serde_json::from_value(wire).unwrap(), &data()).is_err());
    assert!(serde_json::from_value::<DeferredHttpConfig>(serde_json::json!([])).is_err());
}

#[test]
fn persisted_owner_identity_and_finite_limits_cannot_be_omitted_or_downgraded() {
    for name in [
        "storeIdentity",
        "checkpointRoot",
        "startupTimeoutMillis",
        "store",
        "native",
        "dispatcher",
    ] {
        let mut value = input();
        value.as_object_mut().unwrap().remove(name);
        assert!(
            serde_json::from_value::<StateConfig>(value).is_err(),
            "{name}"
        );
    }
    for name in [
        "clockCheckpoint",
        "continuityProven",
        "restoreApproved",
        "startPaused",
    ] {
        let mut value = input();
        value[name] = true.into();
        assert!(
            serde_json::from_value::<StateConfig>(value).is_err(),
            "{name}"
        );
    }
    for version in [0, 1, 3] {
        let mut value = input();
        value["formatVersion"] = version.into();
        assert!(derive(&serde_json::from_value(value).unwrap(), &data()).is_err());
    }
}

#[test]
fn checkpoint_paths_and_original_startup_duration_remain_bounded_and_separate() {
    for path in [
        PathBuf::from("relative"),
        data(),
        data().join("state"),
        data().join("state/subdir"),
        data().join("state/../checkpoint"),
    ] {
        let mut value: StateConfig = serde_json::from_value(input()).unwrap();
        value.checkpoint_root = path;
        assert!(derive(&value, &data()).is_err());
    }
    for duration in [0, 1, 999, 60_001, u64::MAX] {
        let mut value: StateConfig = serde_json::from_value(input()).unwrap();
        value.startup_timeout_millis = duration;
        assert!(derive(&value, &data()).is_err());
    }
    for duration in [1_000, 60_000] {
        let mut value: StateConfig = serde_json::from_value(input()).unwrap();
        value.startup_timeout_millis = duration;
        assert!(derive(&value, &data()).is_ok());
    }
    let value: StateConfig = serde_json::from_value(input()).unwrap();
    let settings = derive(&value, &data()).unwrap();
    assert_eq!(settings.store.root, data().join("state"));
    assert_eq!(settings.startup_timeout, Duration::from_secs(5));
    assert!(settings.dispatcher.start_paused);
    assert!(!settings.dispatcher.start_in_restore_review);
}
