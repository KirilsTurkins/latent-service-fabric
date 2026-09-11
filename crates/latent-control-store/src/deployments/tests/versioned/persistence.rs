use std::fs;
use std::path::Path;

use latent_artifacts::content_digest;
use latent_manifest::__serde_json as json;

use super::super::super::persistence as stored;
use super::*;

fn rechecksum(mut value: json::Value) -> Vec<u8> {
    // Serialize the typed payload in its actual persistence order. Hashing a
    // Value's alphabetically ordered keys would only test checksum rejection.
    let mut record: stored::Record = json::from_value(value.take()).unwrap();
    record.checksum = content_digest(&json::to_vec(&record.payload).unwrap()).0;
    json::to_vec(&record).unwrap()
}

fn state(root: &Path) -> json::Value {
    json::from_slice(&fs::read(root.join("catalog.json")).unwrap()).unwrap()
}

pub(super) fn assert_committed_error(
    failure: &PlatformError,
    id: &str,
    operation: &str,
    object_generation: u64,
    catalog_generation: u64,
) {
    assert_eq!(failure.code, Code::Unavailable);
    assert_eq!(failure.message, "commit-durability-uncertain");
    let detail = failure
        .details
        .iter()
        .find(|detail| detail.kind == "deployment-mutation")
        .expect("uncertain acknowledgment identifies the exact committed mutation");
    for (key, expected) in [
        ("deployment_id", id.to_owned()),
        ("operation", operation.to_owned()),
        ("object_generation", object_generation.to_string()),
        ("catalog_generation", catalog_generation.to_string()),
        ("committed", "true".to_owned()),
    ] {
        assert_eq!(detail.fields.get(key), Some(&expected));
    }
}

#[test]
fn legacy_state_opens_without_rewrite_then_next_mutation_persists_explicit_object_versions() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    run(store.apply(blue.clone())).unwrap();
    run(store.apply(deployment("green", "alice", &one))).unwrap();
    drop(store);
    let mut legacy = state(&root.0);
    legacy["format_version"] = json::json!(1);
    legacy["payload"]
        .as_object_mut()
        .unwrap()
        .remove("object_generations");
    let legacy_bytes = rechecksum(legacy);
    fs::write(root.0.join("catalog.json"), &legacy_bytes).unwrap();

    let store = open(&root, &releases);
    assert_eq!(store.generation(), RouteGeneration(2));
    assert_eq!(record(&store, "blue").generation, 2);
    assert_eq!(record(&store, "green").generation, 2);
    assert_eq!(fs::read(root.0.join("catalog.json")).unwrap(), legacy_bytes);
    let committed = run(store.apply_versioned(&alice(), blue, Some(2))).unwrap();
    assert_eq!(committed.deployment.generation, 3);
    assert_eq!(record(&store, "green").generation, 2);
    let upgraded = state(&root.0);
    assert_eq!(upgraded["format_version"], 2);
    assert_eq!(
        upgraded["payload"]["object_generations"],
        json::json!([
            {"id":"blue", "generation":3}, {"id":"green", "generation":2}
        ])
    );
    drop(store);
    let restarted = open(&root, &releases);
    assert_eq!(record(&restarted, "blue"), committed.deployment);
    assert_eq!(record(&restarted, "green").generation, 2);
}

#[derive(Clone, Copy)]
enum InvalidVersions {
    MissingField,
    MissingEntry,
    ExtraEntry,
    DuplicateEntry,
    ForeignId,
    Zero,
    Future,
    LegacyWithVersions,
}

fn invalidate_versions(value: &mut json::Value, damage: InvalidVersions) {
    if matches!(damage, InvalidVersions::MissingField) {
        value["payload"]
            .as_object_mut()
            .unwrap()
            .remove("object_generations");
        return;
    }
    if matches!(damage, InvalidVersions::LegacyWithVersions) {
        value["format_version"] = json::json!(1);
        return;
    }
    let versions = value["payload"]["object_generations"]
        .as_array_mut()
        .unwrap();
    match damage {
        InvalidVersions::MissingEntry => {
            versions.pop();
        }
        InvalidVersions::ExtraEntry => versions.push(json::json!({"id":"other", "generation":1})),
        InvalidVersions::DuplicateEntry => versions[1] = versions[0].clone(),
        InvalidVersions::ForeignId => versions[0]["id"] = json::json!("other"),
        InvalidVersions::Zero => versions[0]["generation"] = json::json!(0),
        InvalidVersions::Future => versions[0]["generation"] = json::json!(3),
        InvalidVersions::MissingField | InvalidVersions::LegacyWithVersions => unreachable!(),
    }
}

#[test]
fn persisted_object_versions_require_an_exact_valid_map_even_with_a_valid_checksum() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    run(store.apply(deployment("green", "alice", &one))).unwrap();
    drop(store);
    let original = state(&root.0);
    for damage in [
        InvalidVersions::MissingField,
        InvalidVersions::MissingEntry,
        InvalidVersions::ExtraEntry,
        InvalidVersions::DuplicateEntry,
        InvalidVersions::ForeignId,
        InvalidVersions::Zero,
        InvalidVersions::Future,
        InvalidVersions::LegacyWithVersions,
    ] {
        let mut value = original.clone();
        invalidate_versions(&mut value, damage);
        let corrupted = rechecksum(value);
        fs::write(root.0.join("catalog.json"), &corrupted).unwrap();
        let fetches = releases.fetches.load(Ordering::Relaxed);
        assert_code(
            run(Store::open(
                root.0.clone(),
                releases.clone(),
                Limits::default(),
            )),
            Code::CorruptArtifact,
        );
        assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
        assert_eq!(fs::read(root.0.join("catalog.json")).unwrap(), corrupted);
    }
    fs::write(root.0.join("catalog.json"), rechecksum(original)).unwrap();
    let restored = open(&root, &releases);
    assert_eq!(record(&restored, "blue").generation, 1);
    assert_eq!(record(&restored, "green").generation, 2);
}

#[test]
fn exhausted_generation_cannot_wrap_object_versions_or_commit_a_mutation() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    run(store.apply(blue.clone())).unwrap();
    drop(store);
    let mut exhausted = state(&root.0);
    exhausted["payload"]["generation"] = json::json!(u64::MAX);
    exhausted["payload"]["snapshot"]["generation"] = json::json!(u64::MAX);
    exhausted["payload"]["object_generations"][0]["generation"] = json::json!(u64::MAX);
    let persisted = rechecksum(exhausted);
    fs::write(root.0.join("catalog.json"), &persisted).unwrap();
    let store = open(&root, &releases);
    assert_eq!(record(&store, "blue").generation, u64::MAX);
    assert_code(
        run(store.apply_versioned(&alice(), blue.clone(), Some(u64::MAX))),
        Code::ResourceExhausted,
    );
    assert_code(
        run(store.delete_versioned(&alice(), &blue.id, Some(u64::MAX))),
        Code::ResourceExhausted,
    );
    assert_code(
        run(store.apply_versioned(&alice(), deployment("green", "alice", &one), Some(0))),
        Code::ResourceExhausted,
    );
    assert_eq!(record(&store, "blue").generation, u64::MAX);
    assert_eq!(store.generation(), RouteGeneration(u64::MAX));
    assert_eq!(fs::read(root.0.join("catalog.json")).unwrap(), persisted);
}

#[test]
fn precommit_failures_preserve_versions_and_uncertain_commits_report_exact_stamps() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    let original = deployment("blue", "alice", &one);
    let changed = deployment("blue", "alice", &two);
    let created = run(store.apply_versioned(&alice(), original.clone(), Some(0))).unwrap();
    let before = fs::read(root.0.join("catalog.json")).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    let rejected = run(store.apply_versioned(&alice(), changed.clone(), Some(1))).unwrap_err();
    assert_eq!(rejected.code, Code::Unavailable);
    assert_eq!(rejected.message, "injected-before-rename");
    assert!(!rejected
        .details
        .iter()
        .any(|detail| detail.kind == "deployment-mutation"));
    assert_eq!(record(&store, "blue"), created.deployment);
    assert_eq!(fs::read(root.0.join("catalog.json")).unwrap(), before);
    run(store.apply_versioned(&alice(), changed, Some(1))).unwrap();
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let uncertain = run(store.apply_versioned(&alice(), original.clone(), Some(2))).unwrap_err();
    assert_committed_error(&uncertain, "blue", "apply", 3, 3);
    assert_eq!(record(&store, "blue").manifest, original);
    assert_eq!(record(&store, "blue").generation, 3);
    drop(store);
    let restarted = open(&root, &releases);
    assert_eq!(record(&restarted, "blue").generation, 3);
    restarted.fail_parent_sync.store(true, Ordering::SeqCst);
    let uncertain_delete =
        run(restarted.delete_versioned(&alice(), &original.id, Some(3))).unwrap_err();
    assert_committed_error(&uncertain_delete, "blue", "delete", 3, 4);
    assert!(run(restarted.get_versioned(&alice(), &original.id))
        .unwrap()
        .is_none());
    drop(restarted);
    let restarted = open(&root, &releases);
    assert_eq!(restarted.generation(), RouteGeneration(4));
    assert!(run(restarted.get_versioned(&alice(), &original.id))
        .unwrap()
        .is_none());
    assert_eq!(
        run(restarted.apply_versioned(&alice(), original, Some(0)))
            .unwrap()
            .deployment
            .generation,
        5
    );
}
