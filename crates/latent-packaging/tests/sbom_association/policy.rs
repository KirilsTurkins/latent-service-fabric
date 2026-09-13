use latent_packaging::{
    attach_package_sbom, build_package, evaluate_sboms, PackagingLimits, SbomEntryKind,
    SbomEvidenceLimits, SbomPolicy, SbomPolicyConfig, SbomPresence,
};

use super::support::{assets, embed, inventory, policy};

#[test]
fn optional_absence_and_each_required_presence_are_explicit() {
    let bundle = build_package(assets(), PackagingLimits::default()).unwrap();
    let limits = SbomEvidenceLimits::default();
    let optional = policy(SbomPresence::Optional, SbomPresence::Optional);
    let result = evaluate_sboms(&bundle, &[], &optional, limits).unwrap();
    assert!(result.inventory_digest().is_none());
    assert!(result.referrer_digest().is_none());
    let embedded = policy(SbomPresence::Required, SbomPresence::Optional);
    assert_eq!(
        evaluate_sboms(&bundle, &[], &embedded, limits)
            .unwrap_err()
            .message,
        "required-embedded-sbom-missing"
    );
    let detached = policy(SbomPresence::Optional, SbomPresence::Required);
    assert_eq!(
        evaluate_sboms(&bundle, &[], &detached, limits)
            .unwrap_err()
            .message,
        "required-detached-sbom-missing"
    );
}

#[test]
fn unavailable_attribution_stays_valid_until_required_by_role() {
    let input = assets();
    let bundle = build_package(
        embed(input.clone(), inventory(&input)),
        PackagingLimits::default(),
    )
    .unwrap();
    let limits = SbomEvidenceLimits::default();
    let optional = policy(SbomPresence::Required, SbomPresence::Optional);
    evaluate_sboms(&bundle, &[], &optional, limits).unwrap();
    let mut source = optional.config().clone();
    source.require_source = vec![SbomEntryKind::Asset];
    assert_eq!(
        evaluate_sboms(&bundle, &[], &SbomPolicy::new(source).unwrap(), limits)
            .unwrap_err()
            .message,
        "required-sbom-source-unavailable"
    );
    let mut license = optional.config().clone();
    license.require_license = vec![SbomEntryKind::Asset];
    assert_eq!(
        evaluate_sboms(&bundle, &[], &SbomPolicy::new(license).unwrap(), limits)
            .unwrap_err()
            .message,
        "required-sbom-license-unavailable"
    );
    let mut known = inventory(&input);
    known.entries[0].source = Some("https://example.invalid/source".into());
    known.entries[0].license_expression = Some("Apache-2.0".into());
    let attributed = build_package(embed(input, known), PackagingLimits::default()).unwrap();
    let mut both = optional.config().clone();
    both.require_source = vec![SbomEntryKind::Asset];
    both.require_license = vec![SbomEntryKind::Asset];
    evaluate_sboms(&attributed, &[], &SbomPolicy::new(both).unwrap(), limits).unwrap();
}

#[test]
fn policy_identity_binds_all_choices_and_normalizes_only_role_order() {
    let config = SbomPolicyConfig {
        format_version: 1,
        embedded: SbomPresence::Optional,
        detached: SbomPresence::Optional,
        require_source: vec![SbomEntryKind::Asset, SbomEntryKind::Component],
        require_license: vec![],
    };
    let first = SbomPolicy::new(config.clone()).unwrap();
    let mut reordered = config.clone();
    reordered.require_source.reverse();
    assert_eq!(first.digest(), SbomPolicy::new(reordered).unwrap().digest());
    let second = SbomPolicy::from_json(first.canonical_bytes()).unwrap();
    assert_eq!(first.digest(), second.digest());
    for change in 0..4 {
        let mut changed = config.clone();
        match change {
            0 => changed.embedded = SbomPresence::Required,
            1 => changed.detached = SbomPresence::Required,
            2 => changed.require_source.clear(),
            _ => changed.require_license = vec![SbomEntryKind::Asset],
        }
        assert_ne!(first.digest(), SbomPolicy::new(changed).unwrap().digest());
    }
    let mut capacity = config;
    capacity.require_source.reserve(100_000);
    let checked = SbomPolicy::new(capacity).unwrap();
    assert!(checked.config().require_source.capacity() < 100);
}

#[test]
fn policy_json_shape_and_role_bounds_fail_before_acceptance() {
    let policy = policy(SbomPresence::Optional, SbomPresence::Optional);
    let canonical = std::str::from_utf8(policy.canonical_bytes()).unwrap();
    let duplicate = canonical.replacen('{', "{\"formatVersion\":1,", 1);
    assert!(SbomPolicy::from_json(duplicate.as_bytes()).is_err());
    let unknown = canonical.replacen('{', "{\"allowAnything\":1,", 1);
    assert!(SbomPolicy::from_json(unknown.as_bytes()).is_err());
    let null = canonical.replace("\"requireSource\":[]", "\"requireSource\":null");
    assert!(SbomPolicy::from_json(null.as_bytes()).is_err());
    let nested = canonical.replace("\"requireSource\":[]", "\"requireSource\":[[[[[[]]]]]]");
    assert!(SbomPolicy::from_json(nested.as_bytes()).is_err());
    let oversized = vec![b' '; 4097];
    assert!(SbomPolicy::from_json(&oversized).is_err());
    let mut repeated = policy.config().clone();
    repeated.require_source = vec![SbomEntryKind::Asset; 2];
    assert_eq!(
        SbomPolicy::new(repeated).unwrap_err().message,
        "duplicate-sbom-policy-role"
    );
    let mut too_many = policy.config().clone();
    too_many.require_source = vec![SbomEntryKind::Asset; 10];
    assert_eq!(
        SbomPolicy::new(too_many).unwrap_err().message,
        "sbom-policy-role-limit"
    );
}

#[test]
fn association_byte_and_count_limits_have_exact_boundaries() {
    let input = assets();
    let bundle = build_package(
        embed(input.clone(), inventory(&input)),
        PackagingLimits::default(),
    )
    .unwrap();
    let evidence = attach_package_sbom(&bundle, SbomEvidenceLimits::default()).unwrap();
    let limits = SbomEvidenceLimits {
        max_referrers: 1,
        max_manifest_bytes: evidence.manifest_bytes().len(),
        max_payload_bytes: evidence.payload_bytes().len(),
        max_total_bytes: evidence.manifest_bytes().len() + evidence.payload_bytes().len() + 2,
    };
    let policy = policy(SbomPresence::Required, SbomPresence::Required);
    evaluate_sboms(&bundle, &[evidence.as_ref()], &policy, limits).unwrap();
    for choice in 0..3 {
        let mut lowered = limits;
        match choice {
            0 => lowered.max_manifest_bytes -= 1,
            1 => lowered.max_payload_bytes -= 1,
            _ => lowered.max_total_bytes -= 1,
        }
        assert!(evaluate_sboms(&bundle, &[evidence.as_ref()], &policy, lowered).is_err());
    }
    assert_eq!(
        evaluate_sboms(
            &bundle,
            &[evidence.as_ref(), evidence.as_ref()],
            &policy,
            limits
        )
        .unwrap_err()
        .message,
        "sbom-evidence-count-limit"
    );
    let raised = SbomEvidenceLimits {
        max_referrers: usize::MAX,
        ..limits
    };
    assert_eq!(
        evaluate_sboms(&bundle, &[], &policy, raised)
            .unwrap_err()
            .message,
        "invalid-sbom-evidence-limits"
    );
}
