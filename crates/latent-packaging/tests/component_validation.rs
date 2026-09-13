mod fixtures;
use fixtures::component::Options;
use latent_artifacts::package::{artifact_blob_digest, LayerRole};
use latent_packaging::{build_package, PackagingLimits};
use serde_json::json;

#[test]
fn real_component_and_pinned_source_graph_pass_without_guest_execution() {
    let bundle = build_package(
        fixtures::capsule(Options::default()),
        PackagingLimits::default(),
    )
    .unwrap();
    assert!(bundle.surface().is_some());
    assert!(bundle.blob("component.wasm").unwrap().len() < 512);
}

#[test]
fn real_component_may_prune_host_members_but_retained_signatures_stay_exact() {
    let bundle = build_package(
        fixtures::pruned_context_capsule(false),
        PackagingLimits::default(),
    )
    .unwrap();
    assert!(bundle.surface().is_some());
    assert!(build_package(
        fixtures::pruned_context_capsule(true),
        PackagingLimits::default(),
    )
    .is_err());
}

#[test]
fn nested_shapes_host_contracts_and_extra_exports_are_checked() {
    for options in [
        Options {
            signed_record_field: true,
            ..Options::default()
        },
        Options {
            changed_variant_case: true,
            ..Options::default()
        },
        Options {
            signed_result_error: true,
            ..Options::default()
        },
        Options {
            unknown_host: true,
            ..Options::default()
        },
        Options {
            wrong_clock_signature: true,
            ..Options::default()
        },
        Options {
            extra_export: true,
            ..Options::default()
        },
        Options {
            invalid_body: true,
            ..Options::default()
        },
        Options {
            invalid_unused_body: true,
            ..Options::default()
        },
    ] {
        assert!(build_package(fixtures::capsule(options), PackagingLimits::default()).is_err());
    }
}

#[test]
fn source_hashes_do_not_substitute_for_source_semantics() {
    let mut input = fixtures::capsule(Options::default());
    let source = input
        .layers
        .iter_mut()
        .find(|layer| layer.path == "wit/service.wit")
        .unwrap();
    source.bytes = String::from_utf8(source.bytes.clone())
        .unwrap()
        .replace("value: u32", "value: s32")
        .into_bytes();
    let digest = artifact_blob_digest(&source.bytes);
    fixtures::mutate_json(&mut input, "wit-lock.json", |lock| {
        lock["packages"][1]["digest"] = json!(digest.as_str());
    });
    assert!(build_package(input, PackagingLimits::default()).is_err());
}

#[test]
fn absent_component_and_conflicting_manifest_or_lock_are_rejected() {
    let valid = fixtures::capsule(Options::default());
    let mut missing = valid.clone();
    missing
        .layers
        .retain(|layer| layer.role != LayerRole::Component);
    assert!(build_package(missing, PackagingLimits::default()).is_err());
    let mut world = valid.clone();
    fixtures::mutate_json(&mut world, "capsule.json", |manifest| {
        manifest["component"]["world"] = json!("tests:packaging/other@1.0.0");
    });
    assert!(build_package(world, PackagingLimits::default()).is_err());
    let mut digest = valid;
    fixtures::mutate_json(&mut digest, "wit-lock.json", |lock| {
        lock["contractsDigest"] = json!(artifact_blob_digest(b"different").as_str());
    });
    assert!(build_package(digest, PackagingLimits::default()).is_err());
}
