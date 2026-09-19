use super::*;
use crate::{
    args::Cli,
    management::phase2::projection::{self, Project},
};
use clap::Parser;

fn receipt() -> proto::WebOperationReceipt {
    let package = format!("sha256:{}", "a".repeat(64)).parse().unwrap();
    proto::WebOperationReceipt {
        format_version: 1,
        publication: Some(publication(&package, "tests").unwrap()),
        operation_id: "publish-web".into(),
        action: proto::ReleaseLifecycleAction::Publish as i32,
        actor: Some(proto::ReleaseActor {
            subject: "authenticated-operator".into(),
            kind: proto::ReleaseActorKind::Administrator as i32,
        }),
        expected_generation: 0,
        resulting_generation: 1,
        disposition: proto::ReleaseOperationDisposition::Committed as i32,
        reason: proto::ReleaseLifecycleReason::Admitted as i32,
        request_digest: format!("sha256:{}", "b".repeat(64)),
        replayed: false,
    }
}

#[test]
fn web_grammar_requires_exact_publication_and_explicit_finite_mutation() {
    let selected = receipt().publication.unwrap().id;
    for arguments in [
        vec!["latent", "web", "watch"],
        vec!["latent", "web", "get", "--digest", "sha256:bad"],
        vec!["latent", "web", "publish", "package"],
        vec!["latent", "web", "restore", "--publication", &selected],
        vec![
            "latent",
            "web",
            "get",
            "--publication",
            &selected,
            "--actor",
            "admin",
        ],
    ] {
        assert!(Cli::try_parse_from(arguments).is_err());
    }
    Cli::try_parse_from([
        "latent",
        "web",
        "revoke",
        "--publication",
        &selected,
        "--operation-id",
        "revoke-web",
        "--expected-generation",
        "1",
    ])
    .unwrap()
    .validate()
    .unwrap();
    assert!(
        Cli::try_parse_from(["latent", "web", "get", "--publication", "publication:bad",])
            .unwrap()
            .validate()
            .is_err()
    );
}

#[test]
fn web_receipt_validates_closed_semantics_capacity_and_lossless_generation() {
    let original = receipt();
    projection::checked(&original, 8192).unwrap();
    for field in 0..7 {
        let mut changed = original.clone();
        match field {
            0 => changed.action = i32::MAX,
            1 => changed.reason = proto::ReleaseLifecycleReason::PolicyDenied as i32,
            2 => changed.disposition = proto::ReleaseOperationDisposition::Rejected as i32,
            3 => changed.resulting_generation = 2,
            4 => changed.request_digest = "private /host/path".into(),
            5 => changed.publication = None,
            _ => changed.actor.as_mut().unwrap().subject = String::with_capacity(257),
        }
        assert!(projection::checked(&changed, 8192).is_err());
    }
    let mut largest = original;
    largest.action = proto::ReleaseLifecycleAction::Revoke as i32;
    largest.reason = proto::ReleaseLifecycleReason::OperatorRevocation as i32;
    largest.expected_generation = u64::MAX - 1;
    largest.resulting_generation = u64::MAX;
    projection::checked(&largest, 8192).unwrap();
    assert_eq!(
        largest.project()["resultingGeneration"],
        u64::MAX.to_string()
    );
}

#[test]
fn web_status_roundtrip_preserves_admission_renewal_and_terminal_history() {
    use proto::{ReleaseEligibilityReason as Eligibility, ReleaseLifecycleReason as Reason};
    use proto::{ReleaseLifecycleState as State, ReleaseLiveEligibility as Live};

    let published = receipt();
    for (state, reason, generation, live, eligibility) in [
        (
            State::Admitted,
            Reason::Admitted,
            1,
            Live::Eligible,
            Eligibility::Verified,
        ),
        (
            State::Admitted,
            Reason::EvidenceRenewed,
            2,
            Live::Eligible,
            Eligibility::Verified,
        ),
        (
            State::Revoked,
            Reason::OperatorRevocation,
            2,
            Live::Denied,
            Eligibility::Revoked,
        ),
        (
            State::Retired,
            Reason::OperatorRetirement,
            2,
            Live::Denied,
            Eligibility::Retired,
        ),
    ] {
        let response = proto::GetWebPublicationResponse {
            record: Some(proto::WebLifecycleRecord {
                publication: published.publication.clone(),
                package_digest: format!("sha256:{}", "a".repeat(64)),
                web_manifest_digest: format!("sha256:{}", "c".repeat(64)),
                assets_digest: format!("sha256:{}", "d".repeat(64)),
                state: state as i32,
                generation,
                actor: published.actor.clone(),
                reason: reason as i32,
                operation_id: "selected-web-operation".into(),
                evidence_revision_digest: Some(format!("sha256:{}", "e".repeat(64))),
            }),
            eligibility: live as i32,
            eligibility_reason: eligibility as i32,
            renderer: Some(proto::WebRendererDescriptor {
                component_digest: format!("sha256:{}", "f".repeat(64)),
                profile: proto::WebRendererProfile::AngularSsrComponentV1 as i32,
                profile_digest: latent_manifest::renderer_profile_digest(
                    latent_manifest::RendererProfile::AngularSsrComponentV1,
                )
                .to_string(),
                component_bytes: 24 * 1024 * 1024,
            }),
        };
        let decoded =
            proto::GetWebPublicationResponse::decode(response.encode_to_vec().as_slice()).unwrap();
        projection::checked(&decoded, 8192).unwrap();
        assert_eq!(
            decoded.project()["record"]["generation"],
            generation.to_string()
        );
    }
}

#[test]
fn web_receipt_cannot_substitute_tenant_publication_operation_or_transition() {
    let original = receipt();
    let selected = original.publication.clone().unwrap();
    let operation = proto::ReleaseOperationPrecondition {
        operation_id: original.operation_id.clone(),
        expected_generation: Some(0),
    };
    let check = |value: &proto::WebOperationReceipt| {
        execute::association(
            value,
            &selected,
            &operation,
            original.action,
            original.reason,
            "tests",
        )
    };
    check(&original).unwrap();
    for field in 0..6 {
        let mut changed = original.clone();
        match field {
            0 => changed.publication.as_mut().unwrap().tenant = "foreign".into(),
            1 => {
                changed.publication.as_mut().unwrap().id =
                    format!("publication:sha256:{}", "c".repeat(64));
            }
            2 => changed.operation_id = "other".into(),
            3 => changed.expected_generation = 1,
            4 => changed.action = proto::ReleaseLifecycleAction::Revoke as i32,
            _ => changed.reason = proto::ReleaseLifecycleReason::OperatorRevocation as i32,
        }
        assert!(check(&changed).is_err());
    }
}

#[test]
fn web_lookup_preserves_unknown_and_uncertain_without_retry_or_false_commit() {
    for disposition in [
        proto::ReleaseOperationLookupDisposition::Unknown,
        proto::ReleaseOperationLookupDisposition::Uncertain,
    ] {
        let response = proto::GetWebOperationResponse {
            disposition: disposition as i32,
            operation: None,
            tenant: "tests".into(),
        };
        assert!(
            !execute::lookup(response.clone(), "publish-web", "tests", 8192)
                .unwrap()
                .outcome_known
        );
        let mut inconsistent = response;
        inconsistent.operation = Some(receipt());
        assert!(execute::lookup(inconsistent, "publish-web", "tests", 8192).is_err());
    }
    let response = proto::GetWebOperationResponse {
        disposition: proto::ReleaseOperationLookupDisposition::Found as i32,
        operation: Some(receipt()),
        tenant: "tests".into(),
    };
    assert!(
        execute::lookup(response.clone(), "publish-web", "tests", 8192)
            .unwrap()
            .outcome_known
    );
    assert!(execute::lookup(response.clone(), "another", "tests", 8192).is_err());
    assert!(execute::lookup(response, "publish-web", "foreign", 8192).is_err());
}

#[test]
fn web_preparation_requires_a_finite_wait_and_is_descriptive_not_execution_authority() {
    let selected = receipt().publication.unwrap();
    for wait in ["0", "300001"] {
        assert!(Cli::try_parse_from([
            "latent",
            "web",
            "prepare",
            "--publication",
            &selected.id,
            "--lifecycle-generation",
            "1",
            "--maximum-wait-ms",
            wait,
        ])
        .is_err());
    }
    Cli::try_parse_from([
        "latent",
        "web",
        "prepare",
        "--publication",
        &selected.id,
        "--lifecycle-generation",
        "1",
        "--maximum-wait-ms",
        "300000",
    ])
    .unwrap()
    .validate()
    .unwrap();
    let response = proto::PrepareWebPublicationResponse {
        publication: Some(selected),
        lifecycle_generation: 1,
        component_digest: format!("sha256:{}", "c".repeat(64)),
        prepared: true,
    };
    projection::checked(&response, 8192).unwrap();
    assert_eq!(response.clone().project()["executionAuthorized"], false);
    for field in 0..4 {
        let mut invalid = response.clone();
        match field {
            0 => invalid.publication = None,
            1 => invalid.lifecycle_generation = 0,
            2 => invalid.prepared = false,
            _ => invalid.component_digest = "private /host/path".into(),
        }
        assert!(projection::checked(&invalid, 8192).is_err());
    }
}
