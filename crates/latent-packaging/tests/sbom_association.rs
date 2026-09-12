mod fixtures;
#[path = "sbom_association/policy.rs"]
mod policy;
#[path = "sbom_association/support.rs"]
mod support;

use latent_packaging::{
    attach_package_sbom, build_package, evaluate_sboms, inspect_sbom_association, PackagingLimits,
    SbomEntryKind, SbomEvidenceLimits, SbomEvidenceRef, SbomPresence, SBOM_PATH,
};
use support::{assets, embed, inventory};

#[test]
fn embedded_assets_and_capsule_wit_outputs_are_checked() {
    for input in [
        assets(),
        support::ssr(),
        fixtures::capsule(fixtures::component::Options::default()),
    ] {
        let contents = inventory(&input);
        let bundle =
            build_package(embed(input, contents.clone()), PackagingLimits::default()).unwrap();
        let checked = bundle.sbom().unwrap();
        assert_eq!(checked.package_digest(), bundle.layout().digest());
        assert_eq!(checked.entry_count(), contents.entries.len());
        if bundle.surface().is_some() {
            assert_eq!(checked.counts(SbomEntryKind::WitPackage).entries(), 2);
            assert_eq!(checked.counts(SbomEntryKind::Component).entries(), 1);
        }
        let evidence = attach_package_sbom(&bundle, SbomEvidenceLimits::default()).unwrap();
        assert_eq!(evidence.payload_bytes(), bundle.blob(SBOM_PATH).unwrap());
        let association =
            inspect_sbom_association(&bundle, evidence.as_ref(), SbomEvidenceLimits::default())
                .unwrap();
        assert_eq!(association.inventory_digest(), checked.inventory_digest());
        let policy = support::policy(SbomPresence::Required, SbomPresence::Required);
        let result = evaluate_sboms(
            &bundle,
            &[evidence.as_ref()],
            &policy,
            SbomEvidenceLimits::default(),
        )
        .unwrap();
        assert_eq!(result.policy_digest(), policy.digest());
        assert_eq!(result.referrer_digest(), Some(evidence.digest()));
    }
}

#[test]
fn a_small_referrer_can_associate_a_package_manifest_larger_than_four_kib() {
    let mut input = assets();
    for index in 0..20 {
        let mut layer = input.layers[0].clone();
        layer.path = format!("assets/file-{index}.html");
        input.layers.push(layer);
    }
    let contents = inventory(&input);
    let bundle = build_package(embed(input, contents), PackagingLimits::default()).unwrap();
    assert!(bundle.manifest_bytes().len() > 4096);
    let evidence = attach_package_sbom(&bundle, SbomEvidenceLimits::default()).unwrap();
    assert!(evidence.manifest_bytes().len() < 4096);
    inspect_sbom_association(&bundle, evidence.as_ref(), SbomEvidenceLimits::default()).unwrap();
}

#[test]
fn copied_inventory_cannot_cover_changed_outputs_or_package_identity() {
    let original = assets();
    let contents = inventory(&original);
    let mut changed = original.clone();
    changed.layers[0].bytes.push(b'!');
    assert_eq!(
        build_package(embed(changed, contents.clone()), PackagingLimits::default())
            .unwrap_err()
            .message,
        "sbom-output-identity-mismatch"
    );
    let mut renamed = original;
    renamed.name = "another-package".into();
    assert_eq!(
        build_package(embed(renamed, contents), PackagingLimits::default())
            .unwrap_err()
            .message,
        "sbom-package-identity-mismatch"
    );
}

#[test]
fn a_missing_output_and_wrong_wit_package_version_are_rejected() {
    let input = fixtures::capsule(fixtures::component::Options::default());
    let mut missing = inventory(&input);
    missing
        .entries
        .retain(|entry| entry.kind != SbomEntryKind::Component);
    assert_eq!(
        build_package(embed(input.clone(), missing), PackagingLimits::default())
            .unwrap_err()
            .message,
        "missing-sbom-output"
    );
    let mut wrong = inventory(&input);
    wrong
        .entries
        .iter_mut()
        .find(|entry| entry.kind == SbomEntryKind::WitPackage)
        .unwrap()
        .version = Some("1.0.1".into());
    assert_eq!(
        build_package(embed(input, wrong), PackagingLimits::default())
            .unwrap_err()
            .message,
        "sbom-wit-identity-mismatch"
    );
}

#[test]
fn occupied_reserved_path_is_always_inspected_and_its_byte_limit_is_honored() {
    let input = assets();
    let mut bad_media = embed(input.clone(), inventory(&input));
    bad_media.layers.last_mut().unwrap().media_type = "application/json".into();
    assert_eq!(
        build_package(bad_media, PackagingLimits::default())
            .unwrap_err()
            .message,
        "invalid-embedded-sbom-layer"
    );
    let mut malformed = embed(input.clone(), inventory(&input));
    malformed.layers.last_mut().unwrap().bytes = b"{}".to_vec();
    assert!(build_package(malformed, PackagingLimits::default()).is_err());
    let prepared = embed(input.clone(), inventory(&input));
    let bytes = prepared.layers.last().unwrap().bytes.len();
    let mut limits = PackagingLimits::default();
    limits.sbom.max_document_bytes = bytes;
    assert!(build_package(prepared.clone(), limits).is_ok());
    limits.sbom.max_document_bytes -= 1;
    assert!(build_package(prepared, limits).is_err());
}

#[test]
fn detached_subject_payload_and_empty_config_are_exact() {
    let input = assets();
    let bundle = build_package(
        embed(input.clone(), inventory(&input)),
        PackagingLimits::default(),
    )
    .unwrap();
    let limits = SbomEvidenceLimits::default();
    let evidence = attach_package_sbom(&bundle, limits).unwrap();
    let mut wrong_subject: serde_json::Value =
        serde_json::from_slice(evidence.manifest_bytes()).unwrap();
    wrong_subject["subject"]["digest"] = serde_json::json!(format!("sha256:{}", "f".repeat(64)));
    let manifest = serde_json::to_vec(&wrong_subject).unwrap();
    assert!(inspect_sbom_association(
        &bundle,
        SbomEvidenceRef {
            manifest: &manifest,
            ..evidence.as_ref()
        },
        limits
    )
    .is_err());
    let mut altered = evidence.payload_bytes().to_vec();
    altered.push(b' ');
    assert!(inspect_sbom_association(
        &bundle,
        SbomEvidenceRef {
            payload: &altered,
            ..evidence.as_ref()
        },
        limits
    )
    .is_err());
    assert!(inspect_sbom_association(
        &bundle,
        SbomEvidenceRef {
            config: b"[]",
            ..evidence.as_ref()
        },
        limits
    )
    .is_err());
}

#[test]
fn duplicate_conflicting_and_malformed_discovery_never_selects_a_winner() {
    let input = assets();
    let bundle = build_package(
        embed(input.clone(), inventory(&input)),
        PackagingLimits::default(),
    )
    .unwrap();
    let limits = SbomEvidenceLimits::default();
    let evidence = attach_package_sbom(&bundle, limits).unwrap();
    let policy = support::policy(SbomPresence::Optional, SbomPresence::Optional);
    assert_eq!(
        evaluate_sboms(
            &bundle,
            &[evidence.as_ref(), evidence.as_ref()],
            &policy,
            limits
        )
        .unwrap_err()
        .message,
        "duplicate-sbom-association"
    );
    let mut manifest = evidence.manifest_bytes().to_vec();
    manifest.push(b' ');
    let different = SbomEvidenceRef {
        manifest: &manifest,
        ..evidence.as_ref()
    };
    for entries in [
        [evidence.as_ref(), different],
        [different, evidence.as_ref()],
    ] {
        assert_eq!(
            evaluate_sboms(&bundle, &entries, &policy, limits)
                .unwrap_err()
                .message,
            "conflicting-sbom-associations"
        );
    }
    let malformed = SbomEvidenceRef {
        manifest: b"{}",
        ..evidence.as_ref()
    };
    for entries in [
        [evidence.as_ref(), malformed],
        [malformed, evidence.as_ref()],
    ] {
        assert_eq!(
            evaluate_sboms(&bundle, &entries, &policy, limits)
                .unwrap_err()
                .message,
            "invalid-sbom-association-set"
        );
    }
}
