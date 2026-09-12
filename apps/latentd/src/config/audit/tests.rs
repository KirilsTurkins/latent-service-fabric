use super::*;

fn decode(member: &str) -> Result<super::super::NodeConfig, PlatformError> {
    let input = format!(
        r#"{{"formatVersion":1,"dataDirectory":"data","nodeId":"audit-tests","credentials":[],"audit":{member}}}"#
    );
    super::super::input::decode(input.as_bytes())
}

#[test]
fn audit_requires_closed_object_and_explicit_durable_mode() {
    for invalid in [
        "null",
        "[]",
        "{}",
        r#"{"mode":"disabled"}"#,
        r#"{"mode":"durable","token":"secret"}"#,
        r#"{"mode":"durable","records":2,"records":3}"#,
        r#"{"mode":"durable","mode":"durable"}"#,
        r#"{"mode":"durable","records":null}"#,
    ] {
        assert!(decode(invalid).is_err(), "accepted {invalid}");
    }
    assert!(decode(r#"{"mode":"durable"}"#).unwrap().audit.is_some());
}

#[cfg(target_os = "linux")]
#[test]
fn audit_defaults_match_finite_owner_budgets_and_derivation_has_no_io() {
    let parsed = decode(r#"{"mode":"durable"}"#).unwrap();
    let limits = derive(parsed.audit.as_ref()).unwrap().unwrap();
    assert_eq!(limits, AuditLimits::default());
    assert_eq!(derive(None).unwrap(), None);
    let lowered = decode(
        r#"{"mode":"durable","records":2,"diskBytes":32768,"queuedOperations":1,"queryOwners":1}"#,
    )
    .unwrap();
    let limits = derive(lowered.audit.as_ref()).unwrap().unwrap();
    assert_eq!(limits.maximum_records, 2);
    assert!(limits.maximum_metadata_bytes >= 128 * 1024 + 2 * 1536);
    assert!(limits.maximum_queued_bytes >= limits.maximum_record_bytes);
    assert!(limits.maximum_total_page_bytes >= 4 * 64 * 1024);
    limits.validate().unwrap();
}

#[cfg(target_os = "linux")]
#[test]
fn audit_rejects_each_invalid_numeric_boundary_without_overflow() {
    for member in [
        r#""records":1"#,
        r#""records":16385"#,
        r#""diskBytes":32767"#,
        r#""diskBytes":268435457"#,
        r#""queuedOperations":0"#,
        r#""queuedOperations":257"#,
        r#""queryOwners":0"#,
        r#""queryOwners":17"#,
        r#""records":18446744073709551615"#,
    ] {
        let parsed = decode(&format!(r#"{{"mode":"durable",{member}}}"#)).unwrap();
        assert!(derive(parsed.audit.as_ref()).is_err());
    }
    let maximum = decode(r#"{"mode":"durable","records":16384,"diskBytes":268435456,"queuedOperations":256,"queryOwners":16}"#).unwrap();
    derive(maximum.audit.as_ref())
        .unwrap()
        .unwrap()
        .validate()
        .unwrap();
}

#[cfg(not(target_os = "linux"))]
#[test]
fn unsupported_node_profile_fails_before_opening_an_audit_root() {
    let parsed = decode(r#"{"mode":"durable"}"#).unwrap();
    assert_eq!(
        derive(parsed.audit.as_ref()).unwrap_err().code,
        PlatformErrorCode::IncompatibleContract
    );
}
