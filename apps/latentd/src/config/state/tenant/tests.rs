use super::*;

pub(in crate::config::state) fn quota(tenant: &str) -> serde_json::Value {
    serde_json::json!({"tenant":tenant,"limits":{
        "stateKeys":256,"stateBytes":4_194_304,"tombstoneKeys":256,"tombstoneBytes":4_194_304,
        "resultRows":128,"resultBytes":16_777_216,"effectRows":128,"effectBytes":8_388_608,
        "payloadBytes":4_194_304,"recoveryBytes":16_777_216,"metadataRows":1024,"metadataBytes":1_048_576}})
}

#[test]
fn installed_targets_require_explicit_tenant_limits_while_empty_bootstrap_is_separate() {
    let mut input = super::super::tests::input();
    let config = serde_json::from_value(input.clone()).unwrap();
    let selected = super::super::derive(&config, &super::super::tests::data()).unwrap();
    assert_eq!(selected.tenant_quotas[0].tenant, "a");
    assert_eq!(selected.tenant_quotas[0].limits.state_bytes, 4_194_304);
    input.as_object_mut().unwrap().remove("tenantQuotas");
    let config = serde_json::from_value(input.clone()).unwrap();
    assert!(super::super::derive(&config, &super::super::tests::data()).is_err());
    input["operations"] = serde_json::json!([]);
    let config = serde_json::from_value(input).unwrap();
    assert!(super::super::derive(&config, &super::super::tests::data())
        .unwrap()
        .tenant_quotas
        .is_empty());
}

#[test]
fn missing_duplicate_oversized_or_changed_tenant_declarations_refuse_configuration() {
    let mut input = super::super::tests::input();
    input["tenantQuotas"][0]["tenant"] = "another-tenant".into();
    let config = serde_json::from_value(input).unwrap();
    assert!(super::super::derive(&config, &super::super::tests::data()).is_err());
    let mut input = super::super::tests::input();
    input["tenantQuotas"] = serde_json::json!([quota("a"), quota("a")]);
    let config = serde_json::from_value(input).unwrap();
    assert!(super::super::derive(&config, &super::super::tests::data()).is_err());
    let mut input = super::super::tests::input();
    input["tenantQuotas"] = (0..=32)
        .map(|index| quota(&format!("tenant-{index}")))
        .collect::<Vec<_>>()
        .into();
    let config = serde_json::from_value(input).unwrap();
    assert!(super::super::derive(&config, &super::super::tests::data()).is_err());
    for (name, value) in [
        ("stateKeys", 65537),
        ("stateBytes", 1_073_741_825),
        ("metadataBytes", 1024),
        ("recoveryBytes", 16_777_217),
    ] {
        let mut input = super::super::tests::input();
        input["tenantQuotas"][0]["limits"][name] = value.into();
        let config = serde_json::from_value(input).unwrap();
        assert!(
            super::super::derive(&config, &super::super::tests::data()).is_err(),
            "{name}"
        );
    }
}

#[test]
fn tenant_constraints_reject_grants_null_unknown_and_noninteger_limits() {
    assert!(
        serde_json::from_value::<TenantQuotaConfig>(serde_json::json!(["a", quota("a")["limits"]]))
            .is_err()
    );
    for (name, value) in [("grant", true.into()), ("tenant", serde_json::Value::Null)] {
        let mut input = quota("a");
        input[name] = value;
        assert!(serde_json::from_value::<TenantQuotaConfig>(input).is_err());
    }
    for (name, value) in [
        ("grant", true.into()),
        ("stateBytes", true.into()),
        ("stateBytes", serde_json::json!(1.5)),
        ("stateBytes", serde_json::Value::Null),
    ] {
        let mut input = quota("a");
        input["limits"][name] = value;
        assert!(serde_json::from_value::<TenantQuotaConfig>(input).is_err());
    }
}
