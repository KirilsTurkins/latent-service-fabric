use super::*;
use latent_core::{PlatformErrorCode, ReleaseDigest};

fn renderer(repo: &DirectoryArtifactRepository, operation: &str, html: &[u8]) -> PublicationRef {
    repo.publish_web_package(
        context(operation, 0),
        renderer_test_upload(html),
        &mut |_| Ok(()),
    )
    .unwrap()
    .receipt
    .publication
}

fn component() -> ReleaseDigest {
    crate::content_digest(b"\0asm\x0d\0\x01\0")
}

#[test]
fn only_catalog_verified_web_metadata_selects_public_world_validation() {
    use latent_manifest::{
        JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
    };

    let root = TempRoot::new();
    let repo = Arc::new(open(&root));
    let publication = renderer(&repo, "projection-validation", b"public assets");
    let source = repo.clone().owned_preparation_source().unwrap();
    let artifact = source
        .fetch_blocking_selected(
            &component(),
            Some(&publication.id),
            repo.repository_read_limits(),
        )
        .unwrap();
    let supplied = crate::VerifiedArtifactMetadata::from_artifact(artifact).unwrap();
    assert!(!supplied.is_web_execution_projection());
    assert!(Phase1ManifestValidator
        .validate_capsule(supplied.manifest())
        .is_err());
    let mut deployment = JsonManifestCodec::default()
        .decode_deployment(include_bytes!(
            "../../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
    deployment.metadata.tenant = Some(tenant());
    deployment.metadata.namespace = None;
    deployment.service = latent_core::ServiceId(supplied.manifest().metadata.name.clone());
    deployment.release = component();
    deployment.publication = Some(publication.id.clone());
    deployment.grants.clear();
    deployment.resources = supplied
        .manifest()
        .execution
        .resource_budget_ceiling
        .clone();
    for revoked in [false, true] {
        if revoked {
            revoke(&repo, &publication).unwrap();
        }
        let historical = repo
            .selected_historical_snapshot(&component(), Some(&publication.id))
            .unwrap();
        assert!(historical.metadata().is_web_execution_projection());
        Phase1ManifestValidator
            .validate_web_execution_projection(&deployment, historical.metadata().manifest())
            .unwrap();
        assert_eq!(
            matches!(
                historical.into_parts().1,
                HistoricalExecutionState::Denied(_)
            ),
            revoked
        );
    }
}

#[test]
fn exact_web_projection_keeps_package_authority_separate_from_executable_deduplication() {
    let root = TempRoot::new();
    let repo = Arc::new(open(&root));
    let first = renderer(&repo, "first", b"first assets");
    let second = renderer(&repo, "second", b"second assets");
    let source = repo.clone().owned_preparation_source().unwrap();
    let selected = source
        .execution_eligibility_selected(&component(), Some(&first.id))
        .unwrap()
        .unwrap();
    let repeated = source
        .execution_eligibility_selected(&component(), Some(&first.id))
        .unwrap()
        .unwrap();
    let other = source
        .execution_eligibility_selected(&component(), Some(&second.id))
        .unwrap()
        .unwrap();
    assert_eq!(selected, repeated);
    assert_eq!(selected.cache_digest(), repeated.cache_digest());
    assert_ne!(selected, other);
    assert_ne!(selected.cache_digest(), other.cache_digest());
    assert!(selected.admission().is_none());
    assert!(selected.web_projection().is_some());
    assert_eq!(selected.publication(), &first.id);
    assert!(repo.release_eligibility(&component()).is_err());
    assert!(repo.execution_eligibility(&component()).is_err());
    assert!(repo.fetch_publication(&first).is_err());
    assert!(source.identity(&component()).is_err());
    let first_identity = source
        .identity_selected(&component(), Some(&first.id))
        .unwrap()
        .unwrap();
    let second_identity = source
        .identity_selected(&component(), Some(&second.id))
        .unwrap()
        .unwrap();
    assert_ne!(first_identity, second_identity);
    assert_ne!(first_identity.metadata(), second_identity.metadata());
    assert_fetch_bounds(&repo, &source, &first);
    let mut starts = 0;
    ReleaseUseEligibility::with_all_current(&[selected.clone(), other.clone()], &mut |check| {
        check.check()?;
        starts += 1;
        Ok(())
    })
    .unwrap();
    assert_eq!(starts, 1);
    let detached_lifecycle = selected.lifecycle().clone();
    revoke(&repo, &first).unwrap();
    assert!(selected.check_current().is_err());
    assert!(detached_lifecycle.check_current().is_err());
    other.check_current().unwrap();
    assert!(source
        .identity_selected(&component(), Some(&first.id))
        .is_err());
    let historical = repo
        .selected_historical_snapshot(&component(), Some(&first.id))
        .unwrap();
    assert_eq!(historical.metadata().verified_digest(), &component());
    assert!(matches!(
        historical.into_parts().1,
        HistoricalExecutionState::Denied(_)
    ));
    drop(source);
    drop(repo);
    assert!(other.check_current().is_err());
    let restarted = open(&root);
    assert!(restarted.publication_execution_eligibility(&first).is_err());
    restarted
        .publication_execution_eligibility(&second)
        .unwrap()
        .check_current()
        .unwrap();
    let new_identity = restarted
        .selected_preparation_identity(&component(), Some(&second.id))
        .unwrap()
        .unwrap();
    assert_ne!(new_identity, second_identity);
}

#[test]
fn historical_web_layout_retains_its_read_lease_without_reviving_revoked_authority() {
    let root = TempRoot::new();
    let repo = open(&root);
    let publication = renderer(&repo, "historical-layout", b"immutable green assets");
    let package = repo
        .select_web_publication(&publication)
        .unwrap()
        .eligibility()
        .layout()
        .package()
        .clone();
    revoke(&repo, &publication).unwrap();
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 0);
    let historical = repo
        .selected_historical_snapshot(&component(), Some(&publication.id))
        .unwrap();
    assert_eq!(historical.web_layout().unwrap().package(), &package);
    assert!(matches!(
        historical.state(),
        HistoricalExecutionState::Denied(_)
    ));
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 1);
    assert!(repo.select_web_publication(&publication).is_err());
    drop(historical);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 0);
}

fn assert_fetch_bounds(
    repo: &DirectoryArtifactRepository,
    source: &OwnedArtifactPreparationSource,
    first: &PublicationRef,
) {
    let artifact = source
        .fetch_blocking_selected(&component(), Some(&first.id), repo.repository_read_limits())
        .unwrap();
    assert_eq!(artifact.component_bytes, b"\0asm\x0d\0\x01\0");
    assert_eq!(artifact.manifest.world.0, WEB_WORLD);
    assert_eq!(artifact.manifest.exports[0].contract.0, WEB_CONTRACT);
    assert_eq!(artifact.manifest.metadata.tenant, Some(tenant()));
    assert_eq!(
        artifact
            .manifest
            .execution
            .resource_budget_ceiling
            .outbound_requests,
        0
    );
    let limits = ArtifactPreparationReadLimits {
        maximum_component_bytes: 7,
        ..repo.repository_read_limits()
    };
    assert_eq!(
        source
            .fetch_blocking_selected(&component(), Some(&first.id), limits)
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let wrong = crate::content_digest(b"other renderer");
    for digest in [&component(), &wrong] {
        assert_eq!(
            repo.select_execution_publication(&TenantId("foreign".into()), digest, Some(&first.id))
                .unwrap_err()
                .code,
            PlatformErrorCode::NotFound
        );
    }
    assert!(repo
        .select_execution_publication(&tenant(), &wrong, Some(&first.id))
        .is_err());
}

#[test]
fn web_projection_rejects_foreign_catalog_even_with_the_same_admission_authority() {
    let authority: Arc<dyn AdmissionAuthority> = Arc::new(Host);
    let first_root = TempRoot::new();
    let second_root = TempRoot::new();
    let open_with = |root: &TempRoot| {
        DirectoryArtifactRepository::open_enforced(
            root.path(),
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            Arc::clone(&authority),
        )
        .unwrap()
    };
    let first = open_with(&first_root);
    let second = open_with(&second_root);
    let reference = renderer(&first, "first", b"assets");
    renderer(&second, "second", b"assets");
    let selection = first.select_web_publication(&reference).unwrap();
    assert!(ReleaseUseEligibility::from_web(
        &second.lifecycle_authority(),
        selection.eligibility().clone()
    )
    .is_err());
    let token = first.publication_execution_eligibility(&reference).unwrap();
    assert!(token
        .check_for_catalog(&second.lifecycle_authority())
        .is_err());
    assert!(token.authorize_tenant(&TenantId("other".into())).is_err());
    let other = second
        .publication_execution_eligibility(&reference)
        .unwrap();
    assert!(ReleaseUseEligibility::with_all_current(&[token, other], &mut |_| Ok(())).is_err());
}

#[test]
fn browser_layout_and_retained_receipts_never_supply_an_execution_projection() {
    let root = TempRoot::new();
    let repo = open(&root);
    let reference = publish(&repo).unwrap().receipt.publication;
    assert!(repo.publication_execution_eligibility(&reference).is_err());
    assert!(repo
        .selected_metadata(&component(), Some(&reference.id))
        .is_err());
    let selection = repo.select_web_publication(&reference).unwrap();
    assert!(ReleaseUseEligibility::from_web(
        &repo.lifecycle_authority(),
        selection.eligibility().clone()
    )
    .is_err());
}

#[test]
fn denied_web_projection_still_rejects_tampered_renderer_instead_of_hiding_corruption() {
    let root = TempRoot::new();
    let repo = open(&root);
    let reference = renderer(&repo, "first", b"assets");
    revoke(&repo, &reference).unwrap();
    let directory = root
        .path()
        .join("web/publications")
        .join(reference.id.hex());
    let stored: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("web-admission.json")).unwrap())
            .unwrap();
    let layer = stored["layers"]
        .as_array()
        .unwrap()
        .iter()
        .find(|layer| layer["path"] == "server/renderer.wasm")
        .unwrap();
    std::fs::write(
        directory.join(layer["blob"]["file"].as_str().unwrap()),
        b"corrupt!",
    )
    .unwrap();
    assert!(
        matches!(repo.selected_historical_snapshot(&component(), Some(&reference.id)), Err(failure) if failure.code == PlatformErrorCode::CorruptArtifact)
    );
}

#[test]
fn web_evidence_renewal_preserves_immutable_cache_identity_but_retires_start_authority() {
    let root = TempRoot::new();
    let repo = open(&root);
    let reference = renderer(&repo, "first", b"assets");
    let selected = repo.publication_execution_eligibility(&reference).unwrap();
    let identity = repo
        .selected_preparation_identity(&component(), Some(&reference.id))
        .unwrap();
    let evidence = renderer_test_upload(b"assets");
    repo.renew_web_evidence(
        context("renew", 1),
        &reference,
        ReleaseEvidenceUpload {
            signatures: evidence.signatures,
            provenance: evidence.provenance,
            sboms: evidence.sboms,
        },
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(selected.check_current().is_err());
    let renewed = repo.publication_execution_eligibility(&reference).unwrap();
    assert_ne!(selected.cache_digest(), renewed.cache_digest());
    assert_eq!(
        identity,
        repo.selected_preparation_identity(&component(), Some(&reference.id))
            .unwrap()
    );
    renewed
        .with_current(&mut |check| {
            assert!(repo
                .transition_web_publication(
                    context("revoke", 2),
                    &reference,
                    ReleaseLifecycleAction::Revoke,
                    ReleaseLifecycleReason::OperatorRevocation,
                    &mut |_| Ok(())
                )
                .is_err());
            check.check()
        })
        .unwrap();
    assert!(repo
        .web_operation_status(&reference.scope, "revoke")
        .unwrap()
        .is_none());
    repo.transition_web_publication(
        context("revoke", 2),
        &reference,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(renewed.check_current().is_err());
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 2);
    drop(selected);
    drop(renewed);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 0);
}
