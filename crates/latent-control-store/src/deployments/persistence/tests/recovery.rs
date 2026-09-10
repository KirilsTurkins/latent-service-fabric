use std::collections::BTreeMap;
use std::fs;
use std::sync::Arc;

use latent_core::RouteGeneration;
use latent_routing::RouteResolver;
use latent_routing::RouteSnapshotSource;

use super::super::*;
use super::{assert_legacy_bytes, catalog};
use crate::deployments::compiler;
use crate::deployments::tests::fixtures::{deployment, run, Limits, Releases, Store, TempRoot};
use crate::DeploymentStore;

fn version_one(bytes: &[u8]) -> Record {
    let mut record: Record = json::from_slice(bytes).unwrap();
    record.format_version = 1;
    record.payload.object_generations = None;
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    record
}

#[test]
fn reopened_v1_and_v2_keep_original_noncanonical_file_bytes() {
    let releases = Arc::new(Releases::default());
    let digest = releases.add("serializer-recovery");
    let manifest = deployment("blue", "alice", &digest);
    let state = catalog(&releases, vec![manifest.clone()], 9);
    let bytes = assert_legacy_bytes(&state);
    for format in [1, 2] {
        let root = TempRoot::new();
        let record = if format == 1 {
            version_one(&bytes)
        } else {
            json::from_slice(&bytes).unwrap()
        };
        // Change outer/typed-payload key order and whitespace. The checksum still
        // covers the original typed canonical payload, never these source bytes.
        let payload = json::to_value(&record.payload).unwrap();
        let source = format!(
            "{{\n\"payload\":{},\n\"checksum\":{},\n\"format_version\":{format}\n}}",
            json::to_string_pretty(&payload).unwrap(),
            json::to_string(&record.checksum).unwrap()
        )
        .into_bytes();
        let path = root.0.join(STATE_FILE);
        fs::write(&path, &source).unwrap();
        let store = run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        ))
        .unwrap();
        assert_eq!(store.generation(), RouteGeneration(9));
        assert_eq!(run(store.list()).unwrap(), vec![manifest.clone()]);
        assert_eq!(run(store.current()).unwrap(), state.snapshot());
        assert_eq!(fs::read(&path).unwrap(), source);
        drop(store);
        assert_eq!(fs::read(&path).unwrap(), source);
    }
}

#[test]
fn loaded_v1_is_still_recompiled_against_the_final_v2_size_limit() {
    let root = TempRoot::new();
    let releases = Releases::default();
    let state = catalog(&releases, Vec::new(), 0);
    let v2 = assert_legacy_bytes(&state);
    let v1 = json::to_vec(&version_one(&v2)).unwrap();
    assert!(v1.len() < v2.len());
    let path = root.0.join(STATE_FILE);
    fs::write(&path, &v1).unwrap();
    // Exercise the compiler boundary directly below the public config's 1024B
    // minimum, keeping this exact empty-catalog boundary independent of metadata.
    let config = Limits {
        max_state_bytes: v1.len(),
        ..Limits::default()
    };
    let restored = load(&root.0, config, &mut Work::default())
        .unwrap()
        .unwrap();
    assert_eq!(restored.format_version, 1);
    #[cfg(not(feature = "catalog-observation"))]
    let mut work = Work::default();
    #[cfg(feature = "catalog-observation")]
    let observer = crate::deployments::CatalogWorkObserver::new();
    #[cfg(feature = "catalog-observation")]
    let mut work = crate::deployments::observation::Source::observed(observer.clone())
        .begin(crate::deployments::CatalogWorkOperation::Open);
    let compiled = run(compiler::compile_versioned(
        BTreeMap::new(),
        BTreeMap::new(),
        RouteGeneration(restored.payload.generation),
        restored.payload.generated_at_unix_millis,
        &releases,
        config,
        None,
        &mut work,
    ));
    work.finish(&compiled);
    assert_eq!(compiled.err().unwrap(), byte_limit());
    drop(work);
    #[cfg(feature = "catalog-observation")]
    {
        let counts = observer.snapshot().last.unwrap().counts;
        assert_eq!(counts.encoder_calls, 1);
        assert_eq!(counts.encoder_failed, 1);
    }
    assert_eq!(fs::read(&path).unwrap(), v1);
}

#[test]
fn load_preserves_exact_file_bound_and_rejects_modified_typed_payload() {
    let root = TempRoot::new();
    let releases = Releases::default();
    let state = catalog(&releases, Vec::new(), 0);
    let bytes = assert_legacy_bytes(&state);
    let path = root.0.join(STATE_FILE);
    fs::write(&path, &bytes).unwrap();
    let exact = Limits {
        max_state_bytes: bytes.len(),
        ..Limits::default()
    };
    assert!(load(&root.0, exact, &mut Work::default())
        .unwrap()
        .is_some());
    let smaller = Limits {
        max_state_bytes: bytes.len() - 1,
        ..exact
    };
    assert_eq!(
        load(&root.0, smaller, &mut Work::default()).err().unwrap(),
        byte_limit()
    );
    let mut changed: Record = json::from_slice(&bytes).unwrap();
    changed.payload.generated_at_unix_millis -= 1;
    fs::write(&path, json::to_vec(&changed).unwrap()).unwrap();
    assert_eq!(
        load(&root.0, exact, &mut Work::default()).err().unwrap(),
        corrupt()
    );
}
