//! Real signed browser/SSR packages through the concrete scoped catalog.
#[path = "web_registry.rs"]
mod registry;

use super::{support, Fixture, SupplyChainAuthority, NOW};
use latent_artifacts::{web::*, *};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use std::{path::Path, sync::Arc};

fn fixture() -> Fixture {
    let mut fixture = Fixture::new();
    fixture.enable_web_builder();
    fixture
}
fn tenant() -> TenantId {
    TenantId("tests".into())
}
fn context(name: &str, operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(name.into())),
        actor: ReleaseActor {
            subject: "trusted-web-test-adapter".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
fn authority(fixture: &Fixture, path: &Path) -> Arc<SupplyChainAuthority> {
    Arc::new(
        SupplyChainAuthority::open(path, fixture.approved(), fixture.clock.clone(), 5).unwrap(),
    )
}
fn open(path: &Path, authority: &Arc<SupplyChainAuthority>) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open_enforced(
        path,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        authority.clone(),
    )
    .unwrap()
}
fn upload(fixture: &Fixture, corrected: bool) -> PackageAdmissionUpload {
    fixture.web_upload(support::web_input(None), true, corrected)
}
fn publish(
    repo: &DirectoryArtifactRepository,
    fixture: &Fixture,
    name: &str,
    operation: &str,
    corrected: bool,
) -> PublicationRef {
    repo.publish_web_package(
        context(name, operation, 0),
        upload(fixture, corrected),
        &mut |_| Ok(()),
    )
    .unwrap()
    .receipt
    .publication
}
fn revoke(
    repo: &DirectoryArtifactRepository,
    reference: &PublicationRef,
    operation: &str,
    generation: u64,
) -> Result<WebMutationResult, PlatformError> {
    repo.transition_web_publication(
        context(&reference.scope.tenant().unwrap().0, operation, generation),
        reference,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
}
fn evidence(fixture: &Fixture) -> ReleaseEvidenceUpload {
    let upload = upload(fixture, false);
    ReleaseEvidenceUpload {
        signatures: upload.signatures,
        provenance: upload.provenance,
        sboms: upload.sboms,
    }
}

#[test]
fn web_catalog_browser_roundtrip_restart_and_private_layers_never_become_public_assets() {
    let fixture = fixture();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let reference = publish(&repo, &fixture, "tests", "publish", false);
    let selected = repo.select_web_publication(&reference).unwrap();
    let url = selected.asset_url("/index.html").unwrap();
    assert!(url.contains(reference.id.as_str()));
    for private in [
        "/metadata/private.json",
        "/metadata/web-application.json",
        "/package/sbom.cdx.json",
        "/server/renderer.wasm",
        "/../index.html",
    ] {
        assert!(
            repo.read_web_asset(&reference, private).is_err(),
            "{private}"
        );
    }
    assert!(repo.read_web_renderer(&reference).is_err());
    assert!(
        repo.fetch_publication(&reference).is_err(),
        "web is not a fabricated capsule publication"
    );
    let read = repo.read_web_asset(&reference, "/index.html").unwrap();
    assert_eq!(read.bytes(), b"<h1>Example</h1>");
    assert_eq!(read.media_type(), "text/html");
    read.with_current(&tenant(), &mut |check| check.check())
        .unwrap();
    assert!(read
        .with_current(&TenantId("other".into()), &mut |_| Ok(()))
        .is_err());
    let held = read.selection().eligibility().clone();
    drop(read);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 2);
    drop(held);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 1);
    assert_eq!(
        std::fs::read(path.join("ADMISSION_MODE")).unwrap(),
        b"lsf-enforced-admission-web-v2\n"
    );
    let storage = repo.publication_storage_snapshot().unwrap();
    assert_eq!(storage.retained_publications, 1);
    repo.reclaim_uncommitted_content(1024).unwrap();
    assert_eq!(
        repo.read_web_asset(&reference, "/index.html")
            .unwrap()
            .bytes(),
        b"<h1>Example</h1>"
    );
    drop(repo);
    assert!(selected.with_current(&tenant(), &mut |_| Ok(())).is_err());
    fixture.clock.set(NOW + 5);
    authority.renew_clock_lease().unwrap();
    let reopened = open(&path, &authority);
    let current = reopened.select_web_publication(&reference).unwrap();
    assert_eq!(current.asset_url("/index.html").unwrap(), url);
    assert_eq!(
        reopened
            .web_operation_status(&reference.scope, "publish")
            .unwrap()
            .unwrap()
            .publication,
        reference
    );
    assert!(selected.with_current(&tenant(), &mut |_| Ok(())).is_err());
}

#[test]
fn web_catalog_corrected_inventory_and_independent_tenants_never_share_revocation_authority() {
    let mut fixture = fixture();
    fixture.policy["tenants"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::json!({"tenant":"other","publishers":["publisher-a"]}));
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let first = publish(&repo, &fixture, "tests", "original", false);
    let corrected = publish(&repo, &fixture, "tests", "corrected", true);
    let other = publish(&repo, &fixture, "other", "original", false);
    assert_ne!(first, corrected);
    assert_ne!(first, other);
    let first_read = repo.read_web_asset(&first, "/index.html").unwrap();
    let other_read = repo.read_web_asset(&other, "/index.html").unwrap();
    let corrected_read = repo.read_web_asset(&corrected, "/index.html").unwrap();
    assert_eq!(first_read.bytes(), corrected_read.bytes());
    assert_ne!(
        first_read.selection().asset_url("/index.html").unwrap(),
        corrected_read.selection().asset_url("/index.html").unwrap()
    );
    assert!(revoke(&repo, &first, "wrong-generation", 0).is_err());
    first_read
        .with_current(&tenant(), &mut |_| {
            assert!(revoke(&repo, &first, "blocked-start-cutover", 1).is_err());
            Ok(())
        })
        .unwrap();
    revoke(&repo, &first, "revoke", 1).unwrap();
    assert!(first_read.with_current(&tenant(), &mut |_| Ok(())).is_err());
    corrected_read
        .with_current(&tenant(), &mut |_| Ok(()))
        .unwrap();
    other_read
        .with_current(&TenantId("other".into()), &mut |_| Ok(()))
        .unwrap();
    assert!(repo.reverify_web_publication(&first).is_err());
    assert!(repo
        .renew_web_evidence(
            context("tests", "renew-revoked", 2),
            &first,
            evidence(&fixture),
            &mut |_| Ok(())
        )
        .is_err());
    assert!(revoke(&repo, &first, "revoke", 1).unwrap().replay);
    drop(repo);
    let reopened = open(&path, &authority);
    assert_eq!(
        reopened
            .web_publication_status(&first)
            .unwrap()
            .record
            .state,
        ReleaseLifecycleState::Revoked
    );
    assert!(reopened.select_web_publication(&first).is_err());
    reopened.read_web_asset(&corrected, "/index.html").unwrap();
    reopened.read_web_asset(&other, "/index.html").unwrap();
}

#[test]
fn web_catalog_renewal_replaces_only_evidence_and_invalidates_old_use_tokens_after_restart() {
    let fixture = fixture();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let reference = publish(&repo, &fixture, "tests", "publish", false);
    let original = repo.select_web_publication(&reference).unwrap();
    let content = repo.publication_storage_snapshot().unwrap();
    fixture.clock.set(NOW + 60);
    authority.renew_clock_lease().unwrap();
    assert!(original.with_current(&tenant(), &mut |_| Ok(())).is_err());
    repo.reverify_web_publication(&reference).unwrap();
    let refreshed = repo.select_web_publication(&reference).unwrap();
    let renewed = repo
        .renew_web_evidence(
            context("tests", "renew", 1),
            &reference,
            evidence(&fixture),
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(renewed.receipt.resulting_generation, 2);
    assert!(refreshed.with_current(&tenant(), &mut |_| Ok(())).is_err());
    assert!(repo
        .web_publication_status(&reference)
        .unwrap()
        .record
        .evidence_revision
        .is_some());
    let after = repo.publication_storage_snapshot().unwrap();
    assert_eq!(content.shared_blob_bytes, after.shared_blob_bytes);
    assert_eq!(content.publication_file_bytes, after.publication_file_bytes);
    assert!(after.web_control_bytes > content.web_control_bytes);
    let current = repo.select_web_publication(&reference).unwrap();
    assert_eq!(
        current.asset_url("/index.html").unwrap(),
        original.asset_url("/index.html").unwrap()
    );
    assert!(
        repo.renew_web_evidence(
            context("tests", "renew", 1),
            &reference,
            evidence(&fixture),
            &mut |_| Ok(())
        )
        .unwrap()
        .replay
    );
    drop(repo);
    let reopened = open(&path, &authority);
    assert_eq!(
        reopened
            .select_web_publication(&reference)
            .unwrap()
            .eligibility()
            .generation(),
        2
    );
    assert!(refreshed.with_current(&tenant(), &mut |_| Ok(())).is_err());
}

#[test]
fn web_catalog_preflight_rejection_and_bad_evidence_leave_no_publication_or_mode_upgrade() {
    let fixture = fixture();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let before = repo.publication_storage_snapshot().unwrap();
    let failure = repo
        .publish_web_package(
            context("tests", "publish", 0),
            upload(&fixture, false),
            &mut |_| {
                Err(PlatformError {
                    code: PlatformErrorCode::ResourceExhausted,
                    message: "test-response-budget".into(),
                    retryable: false,
                    details: vec![],
                })
            },
        )
        .unwrap_err();
    assert_eq!(failure.message, "test-response-budget");
    assert_eq!(repo.publication_storage_snapshot().unwrap(), before);
    assert!(!path.join("web").exists());
    assert_eq!(
        std::fs::read(path.join("ADMISSION_MODE")).unwrap(),
        b"lsf-enforced-admission-v1\n"
    );
    for index in 0..3 {
        let mut bad = upload(&fixture, false);
        match index {
            0 => bad.signatures.clear(),
            1 => bad.provenance[0].payload[0] ^= 1,
            _ => bad.layers[0].1[0] ^= 1,
        }
        assert!(repo
            .publish_web_package(context("tests", "publish", 0), bad, &mut |_| Ok(()))
            .is_err());
        assert!(!path.join("web").exists());
    }
    publish(&repo, &fixture, "tests", "publish", false);
}

#[test]
fn web_catalog_current_grants_do_not_hide_missing_or_changed_original_content_on_restart() {
    for remove_head in [false, true] {
        let fixture = fixture();
        let root = tempfile::tempdir().unwrap();
        let authority = authority(&fixture, &root.path().join("trust"));
        let path = root.path().join("catalog");
        let repo = open(&path, &authority);
        let reference = publish(&repo, &fixture, "tests", "publish", false);
        revoke(&repo, &reference, "revoke", 1).unwrap();
        drop(repo);
        if remove_head {
            std::fs::remove_file(path.join("web/HEAD")).unwrap();
        } else {
            std::fs::write(
                path.join("web/publications")
                    .join(reference.id.hex())
                    .join("admission-0003.bin"),
                b"changed",
            )
            .unwrap();
        }
        fixture.clock.set(2100);
        assert!(DirectoryArtifactRepository::open_enforced(
            &path,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            authority.clone()
        )
        .is_err());
    }
}

#[test]
fn web_catalog_and_capsules_conserve_one_combined_entry_ceiling() {
    for web_first in [false, true] {
        let fixture = fixture();
        let root = tempfile::tempdir().unwrap();
        let authority = authority(&fixture, &root.path().join("trust"));
        let repo = DirectoryArtifactRepository::open_enforced(
            root.path().join("catalog"),
            DirectoryArtifactRepositoryConfig {
                max_index_entries: 1,
                ..DirectoryArtifactRepositoryConfig::default()
            },
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap();
        if web_first {
            publish(&repo, &fixture, "tests", "web", false);
            assert!(super::catalog::ready(repo.admit_package(
                &tenant(),
                fixture.upload(),
                &mut |_| Ok(())
            ))
            .is_err());
        } else {
            super::catalog::ready(repo.admit_package(&tenant(), fixture.upload(), &mut |_| Ok(())))
                .unwrap();
            assert!(repo
                .publish_web_package(
                    context("tests", "web", 0),
                    upload(&fixture, false),
                    &mut |_| Ok(())
                )
                .is_err());
        }
        assert_eq!(
            repo.publication_storage_snapshot()
                .unwrap()
                .retained_publications,
            1
        );
    }
}

#[test]
fn web_catalog_reclaims_only_unselected_evidence_and_keeps_the_current_revision_after_restart() {
    let fixture = fixture();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let reference = publish(&repo, &fixture, "tests", "publish", false);
    for generation in 1..=2 {
        fixture.clock.set(NOW + generation);
        authority.renew_clock_lease().unwrap();
        repo.renew_web_evidence(
            context("tests", &format!("renew-{generation}"), generation),
            &reference,
            evidence(&fixture),
            &mut |_| Ok(()),
        )
        .unwrap();
    }
    let before = repo.publication_storage_snapshot().unwrap();
    assert_eq!(repo.reclaim_uncommitted_web_content(1).unwrap(), 1);
    assert_eq!(repo.reclaim_uncommitted_web_content(1024).unwrap(), 0);
    let after = repo.publication_storage_snapshot().unwrap();
    assert_eq!(before.retained_publications, after.retained_publications);
    assert!(after.web_control_bytes < before.web_control_bytes);
    repo.read_web_asset(&reference, "/index.html").unwrap();
    drop(repo);
    let reopened = open(&path, &authority);
    assert_eq!(
        reopened
            .select_web_publication(&reference)
            .unwrap()
            .eligibility()
            .generation(),
        3
    );
    assert!(
        reopened
            .renew_web_evidence(
                context("tests", "renew-1", 1),
                &reference,
                evidence(&fixture),
                &mut |_| Ok(())
            )
            .unwrap()
            .replay
    );
}

#[test]
#[ignore = "Built public async web component; required by tools/validate_contracts.sh"]
fn actual_web_component_catalog_keeps_renderer_and_assets_exact_through_revocation_and_restart() {
    let component =
        std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").expect("public web component"))
            .unwrap();
    let fixture = fixture();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let first = repo
        .publish_web_package(
            context("tests", "ssr", 0),
            fixture.web_upload(support::web_input(Some(&component)), true, false),
            &mut |_| Ok(()),
        )
        .unwrap()
        .receipt
        .publication;
    let corrected = repo
        .publish_web_package(
            context("tests", "corrected-ssr", 0),
            fixture.web_upload(support::web_input(Some(&component)), true, true),
            &mut |_| Ok(()),
        )
        .unwrap()
        .receipt
        .publication;
    assert_ne!(first, corrected);
    let held = repo.read_web_renderer(&first).unwrap();
    assert_eq!(held.bytes(), component);
    assert_eq!(
        repo.read_web_renderer(&corrected).unwrap().bytes(),
        component
    );
    assert!(repo
        .read_web_asset(&first, "/server/renderer.wasm")
        .is_err());
    revoke(&repo, &first, "revoke-ssr", 1).unwrap();
    assert!(held.with_current(&tenant(), &mut |_| Ok(())).is_err());
    repo.read_web_renderer(&corrected)
        .unwrap()
        .with_current(&tenant(), &mut |check| check.check())
        .unwrap();
    drop(repo);
    let reopened = open(&path, &authority);
    assert!(reopened.read_web_renderer(&first).is_err());
    assert_eq!(
        reopened.read_web_renderer(&corrected).unwrap().bytes(),
        component
    );
    assert_eq!(
        reopened
            .read_web_asset(&corrected, "/index.html")
            .unwrap()
            .bytes(),
        b"<h1>Example</h1>"
    );
    // The Angular execution profile is now supported. This small Wasm fixture
    // checks its public ABI/catalog association, not Angular compilation or T1
    // execution qualification (which have independent build/runtime gates).
    let mut angular = support::web_input(Some(&component));
    let metadata = angular
        .layers
        .iter_mut()
        .find(|layer| layer.path == WEB_MANIFEST_PATH)
        .unwrap();
    let mut web: WebApplicationManifest = serde_json::from_slice(&metadata.bytes).unwrap();
    web.renderer.as_mut().unwrap().profile = WebRendererProfile::AngularSsrComponentV1;
    web.renderer.as_mut().unwrap().profile_digest =
        renderer_profile_digest(WebRendererProfile::AngularSsrComponentV1).to_string();
    metadata.bytes = serde_json::to_vec(&web).unwrap();
    let selected = reopened
        .publish_web_package(
            context("tests", "angular-profile", 0),
            fixture.web_upload(angular.clone(), true, false),
            &mut |_| Ok(()),
        )
        .unwrap()
        .receipt
        .publication;
    assert_eq!(
        reopened.read_web_renderer(&selected).unwrap().bytes(),
        component
    );

    // A valid enum name never makes a stale/unknown compatibility digest valid.
    web.renderer.as_mut().unwrap().profile_digest = format!("sha256:{}", "0".repeat(64));
    angular
        .layers
        .iter_mut()
        .find(|layer| layer.path == WEB_MANIFEST_PATH)
        .unwrap()
        .bytes = serde_json::to_vec(&web).unwrap();
    assert!(reopened
        .publish_web_package(
            context("tests", "unsupported-renderer", 0),
            fixture.web_upload(angular, true, false),
            &mut |_| Ok(())
        )
        .is_err());
}
