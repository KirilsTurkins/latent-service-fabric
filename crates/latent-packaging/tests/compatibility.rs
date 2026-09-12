mod fixtures;

use fixtures::{capsule, component::Options, mutate_json};
use latent_artifacts::package::{artifact_blob_digest, LayerRole, PackageKind};
use latent_contracts::{ComparisonLimits, StructuralCompatibility as Level};
use latent_packaging::{
    build_package, compare_packages, BreakingChangeAllowance, CheckedSurface, PackageBundle,
    PackageComparisonLimits, PackageInput, PackagingLimits,
};
use serde_json::json;
use std::collections::BTreeMap;

fn build(input: PackageInput) -> PackageBundle {
    build_package(input, PackagingLimits::default()).unwrap()
}
fn changed(options: Options, old: &str, new: &str) -> PackageBundle {
    let mut input = capsule(options);
    let source = input
        .layers
        .iter_mut()
        .find(|layer| layer.path == "wit/service.wit")
        .unwrap();
    source.bytes = String::from_utf8(source.bytes.clone())
        .unwrap()
        .replace(old, new)
        .into_bytes();
    let digest = artifact_blob_digest(&source.bytes);
    mutate_json(&mut input, "wit-lock.json", |lock| {
        lock["packages"][1]["digest"] = json!(digest.as_str());
    });
    build(input)
}
#[test]
fn sealed_packages_compare_full_nested_shapes_and_bind_exact_identifiers() {
    let old = build(capsule(Options::default()));
    for candidate in [
        changed(
            Options {
                signed_record_field: true,
                ..Default::default()
            },
            "value: u32",
            "value: s32",
        ),
        changed(
            Options {
                changed_variant_case: true,
                ..Default::default()
            },
            "payload(payload)",
            "changed(payload)",
        ),
        changed(
            Options {
                signed_result_error: true,
                ..Default::default()
            },
            "result<choice, u32>",
            "result<choice, s32>",
        ),
    ] {
        let report =
            compare_packages(&old, &candidate, PackageComparisonLimits::default()).unwrap();
        assert_eq!(report.structural().level, Level::Breaking);
        assert_eq!(report.previous().package(), old.layout().digest());
        assert_eq!(
            report.candidate().component(),
            candidate.surface().map(CheckedSurface::component_digest)
        );
        assert!(!report.allows_replacement(None));
        let allowance = BreakingChangeAllowance::for_pair(&old, &candidate).unwrap();
        assert!(report.allows_replacement(Some(&allowance)));
        let reversed = BreakingChangeAllowance::for_pair(&candidate, &old).unwrap();
        assert!(!report.allows_replacement(Some(&reversed)));
        let unrelated = BreakingChangeAllowance::for_pair(&old, &old).unwrap();
        assert!(!report.allows_replacement(Some(&unrelated)));
    }
}
#[test]
fn different_package_and_wit_source_bytes_can_have_identical_structure() {
    let old = build(capsule(Options::default()));
    let candidate = changed(
        Options::default(),
        "interface api {",
        "// formatting and documentation only\ninterface api {",
    );
    assert_ne!(old.layout().digest(), candidate.layout().digest());
    let report = compare_packages(&old, &candidate, PackageComparisonLimits::default()).unwrap();
    assert_eq!(report.structural().level, Level::Identical);
    assert!(report.allows_replacement(None));
}
#[test]
fn package_only_metadata_change_cannot_reuse_an_unrelated_breaking_allowance() {
    let old = build(capsule(Options::default()));
    let candidate = changed(
        Options {
            signed_record_field: true,
            ..Default::default()
        },
        "value: u32",
        "value: s32",
    );
    let allowance = BreakingChangeAllowance::for_pair(&old, &candidate).unwrap();
    let mut changed_old = capsule(Options::default());
    changed_old
        .annotations
        .insert("test".into(), "separate package identity".into());
    let changed_old = build(changed_old);
    assert_eq!(
        old.surface().unwrap().component_digest(),
        changed_old.surface().unwrap().component_digest()
    );
    let report =
        compare_packages(&changed_old, &candidate, PackageComparisonLimits::default()).unwrap();
    assert!(!report.allows_replacement(Some(&allowance)));
}
#[test]
fn compiler_pruned_declared_import_changes_remain_unknown_even_with_allowance() {
    let old = build(capsule(Options::default()));
    let candidate = build(fixtures::pruned_context_capsule(false));
    let report = compare_packages(&old, &candidate, PackageComparisonLimits::default()).unwrap();
    assert_eq!(report.structural().level, Level::Unknown);
    assert!(!report.structural().analysis_complete);
    let allowance = BreakingChangeAllowance::for_pair(&old, &candidate).unwrap();
    assert!(!report.allows_replacement(Some(&allowance)));
}
#[test]
fn owner_lowered_pair_parse_and_walk_limits_never_authorize_a_sealed_bundle() {
    let old = build(capsule(Options::default()));
    let allowance = BreakingChangeAllowance::for_pair(&old, &old).unwrap();
    for limits in [
        PackageComparisonLimits {
            max_total_wit_bytes: 1,
            ..Default::default()
        },
        PackageComparisonLimits {
            max_total_wit_packages: 1,
            ..Default::default()
        },
        PackageComparisonLimits {
            comparison: ComparisonLimits {
                max_nodes: 1,
                ..Default::default()
            },
            ..Default::default()
        },
        PackageComparisonLimits {
            comparison: ComparisonLimits {
                max_depth: 1,
                ..Default::default()
            },
            ..Default::default()
        },
    ] {
        let report = compare_packages(&old, &old, limits).unwrap();
        assert_eq!(report.structural().level, Level::Unknown);
        assert!(!report.allows_replacement(Some(&allowance)));
    }
}
#[test]
fn asset_packages_are_explicitly_unsupported_by_the_capsule_comparator() {
    let package = build(PackageInput {
        kind: PackageKind::BrowserAssets,
        name: "assets".into(),
        version: "1.0.0".into(),
        entrypoint: "index.html".into(),
        annotations: BTreeMap::default(),
        layers: vec![fixtures::layer(
            "index.html",
            LayerRole::Asset,
            "text/html",
            b"hi".to_vec(),
        )],
    });
    let report = compare_packages(&package, &package, PackageComparisonLimits::default()).unwrap();
    assert_eq!(report.structural().level, Level::Unsupported);
    assert!(!report.allows_replacement(None));
    assert!(BreakingChangeAllowance::for_pair(&package, &package).is_err());
}
