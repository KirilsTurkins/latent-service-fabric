use super::web_component;
use latent_artifacts::{
    web::{WebLifecycleRecord, WebPublicationStatus, WebRenderer, WebRendererProfile},
    LifecycleScope, PublicationRef, ReleaseActor, ReleaseActorKind, ReleaseEligibilityReason,
    ReleaseLifecycleReason, ReleaseLifecycleState, ReleaseLiveEligibility,
};
use latent_core::{PackageDigest, TenantId};
use tonic::Code;

fn status() -> WebPublicationStatus {
    let package: PackageDigest = format!("sha256:{}", "a".repeat(64)).parse().unwrap();
    let assets = format!("sha256:{}", "b".repeat(64));
    WebPublicationStatus {
        record: WebLifecycleRecord {
            publication: PublicationRef::package(
                LifecycleScope::Tenant(TenantId("tests".into())),
                &package,
            )
            .unwrap(),
            package,
            manifest: format!("sha256:{}", "c".repeat(64)).parse().unwrap(),
            assets: assets.parse().unwrap(),
            state: ReleaseLifecycleState::Admitted,
            generation: 1,
            actor: ReleaseActor {
                subject: "authenticated-operator".into(),
                kind: ReleaseActorKind::Administrator,
            },
            reason: ReleaseLifecycleReason::Admitted,
            operation_id: "web-create".into(),
            evidence_revision: None,
        },
        eligibility: ReleaseLiveEligibility::Eligible,
        eligibility_reason: ReleaseEligibilityReason::Verified,
        renderer: Some(WebRenderer {
            layer: "renderer.wasm".into(),
            digest: format!("sha256:{}", "d".repeat(64)),
            size: 1024,
            profile: WebRendererProfile::AngularSsrComponentV1,
            profile_digest: format!("sha256:{}", "e".repeat(64)),
            assets_digest: assets,
            backend_profile: Default::default(),
        }),
    }
}

#[test]
fn web_normalization_retains_historical_identity_without_granting_execution() {
    for (state, eligibility, reason) in [
        (
            ReleaseLifecycleState::Admitted,
            ReleaseLiveEligibility::Eligible,
            ReleaseEligibilityReason::Verified,
        ),
        (
            ReleaseLifecycleState::Admitted,
            ReleaseLiveEligibility::Unknown,
            ReleaseEligibilityReason::AuthorityUnavailable,
        ),
        (
            ReleaseLifecycleState::Revoked,
            ReleaseLiveEligibility::Denied,
            ReleaseEligibilityReason::Revoked,
        ),
        (
            ReleaseLifecycleState::Retired,
            ReleaseLiveEligibility::Denied,
            ReleaseEligibilityReason::Retired,
        ),
    ] {
        let mut value = status();
        value.record.state = state;
        value.eligibility = eligibility;
        value.eligibility_reason = reason;
        let reference = value.record.publication.clone();
        assert_eq!(
            web_component(value, &reference).unwrap(),
            format!("sha256:{}", "d".repeat(64))
        );
    }
}

#[test]
fn web_normalization_rejects_foreign_or_copied_publication_associations() {
    for field in 0..3 {
        let mut value = status();
        let reference = value.record.publication.clone();
        match field {
            0 => {
                value.record.publication.scope = LifecycleScope::Tenant(TenantId("foreign".into()));
            }
            1 => value.record.publication.scope = LifecycleScope::LocalUnscoped,
            _ => value.record.package = format!("sha256:{}", "f".repeat(64)).parse().unwrap(),
        }
        assert_eq!(
            web_component(value, &reference).unwrap_err().code(),
            Code::Internal
        );
    }
}

#[test]
fn web_normalization_rejects_browser_only_and_invalid_renderer_metadata() {
    let mut value = status();
    let reference = value.record.publication.clone();
    value.renderer = None;
    assert_eq!(
        web_component(value, &reference).unwrap_err().code(),
        Code::InvalidArgument
    );
    for field in 0..2 {
        let mut value = status();
        let renderer = value.renderer.as_mut().unwrap();
        match field {
            0 => renderer.digest = "not-a-component".into(),
            _ => renderer.assets_digest = format!("sha256:{}", "f".repeat(64)),
        }
        assert_eq!(
            web_component(value, &reference).unwrap_err().code(),
            Code::Internal
        );
    }
}
