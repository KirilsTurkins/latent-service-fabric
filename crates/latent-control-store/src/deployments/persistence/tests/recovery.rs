use std::fs;
use std::sync::Arc;

use latent_core::RouteGeneration;
use latent_routing::RouteResolver;
use latent_routing::RouteSnapshotSource;

use super::super::*;
use super::{assert_oracle_bytes, catalog};
use crate::deployments::tests::fixtures::{deployment, run, Limits, Releases, Store, TempRoot};
use crate::DeploymentStore;

fn version_one(bytes: &[u8]) -> Record {
    let mut record: Record = json::from_slice(bytes).unwrap();
    record.format_version = 1;
    record.payload.object_generations = None;
    record.payload.publication_pins = None;
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    record
}

#[test]
fn obsolete_formats_are_rejected_and_current_format_preserves_file_bytes() {
    let releases = Arc::new(Releases::default());
    let digest = releases.add("serializer-recovery");
    let manifest = deployment("blue", "alice", &digest);
    let state = catalog(&releases, vec![manifest.clone()], 9);
    let bytes = assert_oracle_bytes(&state);
    for format in [1, 2, 3, 4, 5] {
        let root = TempRoot::new();
        let mut record: Record = json::from_slice(&bytes).unwrap();
        record.format_version = format;
        if format < 5 {
            record.payload.publication_pins = None;
        }
        if format == 1 {
            record.payload.object_generations = None;
        }
        record.checksum =
            latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
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
        let opened = run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        ));
        if format < 5 {
            assert_eq!(
                opened.err().unwrap().code,
                PlatformErrorCode::CorruptArtifact
            );
            assert_eq!(fs::read(&path).unwrap(), source);
            continue;
        }
        let store = opened.unwrap();
        assert_eq!(store.generation(), RouteGeneration(9));
        assert_eq!(run(store.list()).unwrap(), vec![manifest.clone()]);
        assert_eq!(run(store.current()).unwrap(), state.snapshot());
        let persisted = fs::read(&path).unwrap();
        assert_eq!(persisted, source);
        drop(store);
        let restarted = run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        ))
        .unwrap();
        assert_eq!(restarted.generation(), RouteGeneration(9));
        assert_eq!(fs::read(&path).unwrap(), persisted);
    }
}

#[test]
fn obsolete_format_is_rejected_before_any_current_envelope_recompilation() {
    let root = TempRoot::new();
    let releases = Releases::default();
    let state = catalog(&releases, Vec::new(), 0);
    let bytes = json::to_vec(&version_one(&assert_oracle_bytes(&state))).unwrap();
    let path = root.0.join(STATE_FILE);
    fs::write(&path, &bytes).unwrap();
    let limits = Limits {
        max_state_bytes: bytes.len(),
        ..Limits::default()
    };
    let failure = load(&root.0, limits, &mut Work::default()).err().unwrap();
    assert_eq!(
        failure.message,
        "unsupported-catalog-format-use-fresh-state"
    );
    assert_eq!(fs::read(&path).unwrap(), bytes);
}

#[test]
fn load_preserves_exact_file_bound_and_rejects_modified_typed_payload() {
    let root = TempRoot::new();
    let releases = Releases::default();
    let state = catalog(&releases, Vec::new(), 0);
    let bytes = assert_oracle_bytes(&state);
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
