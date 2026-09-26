use super::*;
fn policy() -> proto::Policy {
    let document =
        domain::CapabilityPolicy::parse(br#"{"formatVersion":1,"tenant":"tests","rules":[]}"#)
            .unwrap();
    proto::Policy {
        id: "p".into(),
        metadata: Some(proto::ObjectMetadata {
            name: "p".into(),
            tenant: Some("tests".into()),
            ..proto::ObjectMetadata::default()
        }),
        document: String::from_utf8(document.canonical().to_vec()).unwrap(),
        generation: 2,
        language: domain::LANGUAGE.into(),
        record_kind: proto::CapabilityPolicyRecordKind::Policy as i32,
        content_digest: document.digest().into(),
        revoked: false,
    }
}
#[test]
fn response_scope_document_digest_and_revision_are_checked_before_output() {
    let good = policy();
    let kind = proto::CapabilityPolicyRecordKind::Policy as i32;
    assert!(record(&good, "tests", kind, Some("p")).is_ok());
    for field in 0..7 {
        let mut value = good.clone();
        match field {
            0 => value.metadata.as_mut().unwrap().tenant = Some("foreign".into()),
            1 => value.id = "other".into(),
            2 => value.document.push(' '),
            3 => value.content_digest = format!("sha256:{}", "1".repeat(64)),
            4 => value.generation = 0,
            5 => value.language = "future-profile".into(),
            _ => value.revoked = true,
        }
        assert!(record(&value, "tests", kind, Some("p")).is_err());
    }
}
