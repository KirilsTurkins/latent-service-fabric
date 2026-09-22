use clap::Parser;
use std::time::Duration;

use super::{bounds, prepare, proto, release, response};
use crate::management::{
    association,
    phase2::projection::{self, Project},
};
use crate::{
    args::Cli,
    config::{InputLimits, ResolvedConfig},
    operation::Operation,
};

#[test]
fn static_audit_projection_retains_exact_web_identity_and_rejects_hybrids() {
    let mut value = proto::AuditIdentities {
        trigger: Some("site".into()),
        trigger_generation: Some(1),
        publication_id: Some(format!("publication:sha256:{}", "a".repeat(64))),
        static_web: Some(proto::AuditStaticWebTarget {
            web_manifest_digest: format!("sha256:{}", "b".repeat(64)),
            assets_digest: format!("sha256:{}", "c".repeat(64)),
            web_generation: u64::MAX,
        }),
        ..Default::default()
    };
    projection::checked(&value, 4096).unwrap();
    let output = value.clone().project();
    assert_eq!(output["trigger"], "site");
    assert_eq!(output["staticWeb"]["webGeneration"], u64::MAX.to_string());
    assert!(output["componentDigest"].is_null());
    value.component_digest = Some(format!("sha256:{}", "d".repeat(64)));
    assert!(projection::checked(&value, 4096).is_err());
    value.component_digest = None;
    value.static_web.as_mut().unwrap().web_generation = 0;
    assert!(projection::checked(&value, 4096).is_err());
    value.static_web.as_mut().unwrap().web_generation = 1;
    value.static_web.as_mut().unwrap().assets_digest = "wrong".into();
    assert!(projection::checked(&value, 4096).is_err());
}

fn publication(digit: &str) -> proto::PublicationRef {
    proto::PublicationRef {
        id: format!("publication:sha256:{}", digit.repeat(64)),
        tenant: "examples".into(),
    }
}

#[test]
fn cli_selects_exact_publication_in_configured_scope_and_preserves_legacy_digest() {
    let config = ResolvedConfig {
        endpoint: "http://127.0.0.1:1".into(),
        tenant: "examples".into(),
        token: "x".repeat(32),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
    };
    let expected = publication("b");
    for command in ["get", "lifecycle", "revoke", "retire"] {
        let mut args = vec!["latent", "release", command, "--publication", &expected.id];
        if matches!(command, "revoke" | "retire") {
            args.extend([
                "--operation-id",
                "exact-operation",
                "--expected-generation",
                "18446744073709551615",
            ]);
        }
        let parsed = Cli::try_parse_from(args).unwrap();
        parsed.validate().unwrap();
        let (digest, selected) = match prepare::prepare(&parsed.command, &config).unwrap() {
            Operation::GetRelease(value) => (value.digest, value.publication),
            Operation::GetReleaseLifecycle(value) => (value.digest, value.publication),
            Operation::ChangeReleaseLifecycle(value) => {
                assert_eq!(value.operation.unwrap().expected_generation, Some(u64::MAX));
                (value.digest, value.publication)
            }
            _ => panic!("wrong operation"),
        };
        assert!(digest.is_empty());
        assert_eq!(selected, Some(expected.clone()));
    }
    let digest = release().digest;
    let parsed = Cli::try_parse_from(["latent", "release", "get", &digest]).unwrap();
    let Operation::GetRelease(value) = prepare::prepare(&parsed.command, &config).unwrap() else {
        panic!()
    };
    assert_eq!(value.digest, digest);
    assert!(value.publication.is_none());
    assert!(Cli::try_parse_from([
        "latent",
        "release",
        "get",
        &digest,
        "--publication",
        &expected.id
    ])
    .is_err());
    assert!(Cli::try_parse_from(["latent", "release", "get"]).is_err());
    for invalid in [String::new(), expected.id.to_uppercase(), digest] {
        let parsed =
            Cli::try_parse_from(["latent", "release", "get", "--publication", &invalid]).unwrap();
        assert!(parsed.validate().is_err());
        assert!(prepare::prepare(&parsed.command, &config).is_err());
    }
}

#[test]
fn exact_reply_cannot_substitute_another_publication_with_the_same_component() {
    let expected = publication("a");
    let other = publication("b");
    let component = release().digest;
    association::selected_publication(Some(&expected), Some(&component), Some(&expected), "")
        .unwrap();
    assert!(
        association::selected_publication(Some(&other), Some(&component), Some(&expected), "")
            .is_err()
    );
    assert!(
        association::selected_publication(None, Some(&component), Some(&expected), "").is_err()
    );
    assert!(association::selected_publication(
        Some(&expected),
        Some(&component),
        Some(&expected),
        &component
    )
    .is_err());
    let mut foreign = expected.clone();
    foreign.tenant = "foreign".into();
    assert!(association::selected_publication(
        Some(&foreign),
        Some(&component),
        Some(&expected),
        ""
    )
    .is_err());
}

#[test]
fn release_and_audit_output_preserve_distinct_bounded_publication_identity() {
    let mut value = release();
    value.publication = Some(publication("b"));
    value.package_digest = Some(format!("sha256:{}", "c".repeat(64)));
    bounds::checked(&value, 4096).unwrap();
    let output = response::release(value.clone()).unwrap();
    assert_eq!(
        output["publication"]["id"],
        value.publication.as_ref().unwrap().id
    );
    assert_eq!(output["publication"]["tenant"], "examples");
    assert_eq!(
        output["packageDigest"],
        value.package_digest.clone().unwrap()
    );
    assert_eq!(output["digest"], value.digest);
    assert_eq!(output["sizeBytes"], u64::MAX.to_string());
    value.publication.as_mut().unwrap().tenant = "foreign".into();
    assert!(bounds::checked(&value, 4096).is_err());
    let mut identities = proto::AuditIdentities {
        publication_id: Some(publication("b").id),
        lifecycle_generation: Some(u64::MAX),
        ..proto::AuditIdentities::default()
    };
    projection::checked(&identities, 4096).unwrap();
    let output = identities.clone().project();
    assert_eq!(
        output["publicationId"],
        identities.publication_id.clone().unwrap()
    );
    assert_eq!(output["lifecycleGeneration"], u64::MAX.to_string());
    identities.publication_id = Some(String::new());
    assert!(projection::checked(&identities, 4096).is_err());
}
