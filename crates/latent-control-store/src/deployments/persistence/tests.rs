mod recovery;

use std::sync::Arc;

use latent_artifacts::content_digest;
use latent_core::RouteGeneration;
use latent_manifest::{__serde_json as json, DeploymentManifest};

use super::*;
use crate::deployments::compiler;
use crate::deployments::tests::fixtures::{deployment, run, Limits, Releases};

fn catalog(
    releases: &Releases,
    manifests: Vec<DeploymentManifest>,
    generation: u64,
) -> CompiledCatalog {
    run(compiler::compile(
        manifests
            .into_iter()
            .map(|value| (value.id.clone(), value))
            .collect(),
        RouteGeneration(generation),
        u64::MAX,
        releases,
        Limits::default(),
    ))
    .unwrap()
}

fn assert_legacy_bytes(catalog: &CompiledCatalog) -> Vec<u8> {
    let legacy = legacy::encode(catalog, Limits::default()).unwrap();
    let actual = encode_bytes(
        catalog,
        Limits::default().max_state_bytes,
        &mut Work::default(),
    )
    .unwrap();
    assert_eq!(actual, legacy);
    let parsed: Record = json::from_slice(&actual).unwrap();
    assert_eq!(
        parsed.checksum,
        content_digest(&json::to_vec(&parsed.payload).unwrap()).0
    );
    assert_eq!(parsed.payload.snapshot, catalog_snapshot_value(catalog));
    actual
}

#[test]
fn streamed_encoding_matches_original_for_empty_escaped_and_large_number_states() {
    let releases = Releases::default();
    let one = releases.add("serializer-one");
    let two = releases.add("serializer-two");
    assert_legacy_bytes(&catalog(&releases, Vec::new(), 0));
    for generation in [1, 9, 10, u64::MAX] {
        let mut blue = deployment("blue", "alice", &one);
        blue.metadata.namespace = Some("example".into());
        blue.metadata
            .annotations
            .insert("escaped".into(), "caf\u{e9} \u{96ea} \"\\ \t \r\n".into());
        blue.metadata
            .annotations
            .insert("checksum-placeholder".into(), "0".repeat(64));
        let mut green = deployment("green", "alice", &two);
        green.metadata.namespace = blue.metadata.namespace.clone();
        green.route_weight = 10_000;
        let bob = deployment("bob", "bob", &one);
        let state = catalog(&releases, vec![blue, green, bob], generation);
        let bytes = assert_legacy_bytes(&state);
        let parsed: Record = json::from_slice(&bytes).unwrap();
        assert!(parsed.payload.deployments[0].is_object());
        for route in parsed.payload.snapshot["services"].as_array().unwrap() {
            for revision in route["revisions"].as_array().unwrap() {
                let encoded = revision["attributes"]["lsf.deployment"].as_str().unwrap();
                let value: json::Value = json::from_str(encoded).unwrap();
                assert!(parsed.payload.deployments.contains(&value));
            }
        }
    }
}

#[test]
fn exact_final_document_limit_and_structural_boundaries_never_publish_partial_bytes() {
    let releases = Releases::default();
    let digest = releases.add("serializer-boundaries");
    let state = catalog(&releases, vec![deployment("blue", "alice", &digest)], 9);
    let bytes = assert_legacy_bytes(&state);
    let payload_start = bytes
        .windows(b"\"payload\":".len())
        .position(|value| value == b"\"payload\":")
        .unwrap()
        + b"\"payload\":".len();
    for limit in [
        0,
        1,
        37,
        38,
        39,
        101,
        payload_start,
        payload_start + 1,
        bytes.len() - 1,
    ] {
        let actual = encode_bytes(&state, limit, &mut Work::default());
        assert_eq!(actual.unwrap_err(), byte_limit(), "limit {limit}");
    }
    assert_eq!(
        encode_bytes(&state, bytes.len(), &mut Work::default()).unwrap(),
        bytes
    );
    let encoded = encode(
        state,
        Limits {
            max_state_bytes: bytes.len(),
            ..Limits::default()
        },
        &mut Work::default(),
    )
    .unwrap();
    assert_eq!(encoded.bytes(), bytes);
    let (state, owned_bytes) = encoded.into_parts();
    assert_eq!(
        legacy::encode(&state, Limits::default()).unwrap(),
        owned_bytes
    );
}

#[test]
fn nine_to_ten_uses_current_generation_fields_without_rewriting_canonical_deployments() {
    let releases = Releases::default();
    let digest = releases.add("serializer-generation");
    let mut state = catalog(
        &releases,
        vec![
            deployment("blue", "alice", &digest),
            deployment("green", "alice", &digest),
        ],
        9,
    );
    let original = assert_legacy_bytes(&state);
    let old_records = state.records.iter().map(Arc::clone).collect::<Vec<_>>();
    state.generation = RouteGeneration(10);
    *state
        .versions
        .get_mut(&latent_core::DeploymentId("blue".into()))
        .unwrap() = 10;
    let changed = assert_legacy_bytes(&state);
    assert_eq!(changed.len(), original.len() + 3); // payload/snapshot generation plus one object stamp
    assert!(state
        .records
        .iter()
        .zip(&old_records)
        .all(|(left, right)| Arc::ptr_eq(left, right)));
    let decoded: Record = json::from_slice(&changed).unwrap();
    let versions = decoded
        .object_generations(&decoded.deployments(Limits::default()).unwrap())
        .unwrap();
    assert_eq!(versions[&latent_core::DeploymentId("blue".into())], 10);
    assert_eq!(versions[&latent_core::DeploymentId("green".into())], 9);
}

#[test]
fn failed_sealing_releases_the_only_catalog_record_owner() {
    let releases = Releases::default();
    let digest = releases.add("serializer-owner");
    let state = catalog(&releases, vec![deployment("blue", "alice", &digest)], 1);
    let record = Arc::downgrade(&state.records[0]);
    let result = encode(
        state,
        Limits {
            max_state_bytes: 0,
            ..Limits::default()
        },
        &mut Work::default(),
    );
    assert_eq!(result.err().unwrap(), byte_limit());
    assert!(record.upgrade().is_none());
}

#[test]
fn typed_checksum_sink_preserves_v1_omission_and_exact_payload_byte_bound() {
    let releases = Releases::default();
    let state = catalog(&releases, Vec::new(), 0);
    let bytes = assert_legacy_bytes(&state);
    let mut record: Record = json::from_slice(&bytes).unwrap();
    for format in [1, 2] {
        record.format_version = format;
        record.payload.object_generations = (format == 2).then(Vec::new);
        let canonical = json::to_vec(&record.payload).unwrap();
        let digest =
            payload_checksum(&record.payload, canonical.len(), &mut Work::default()).unwrap();
        assert_eq!(
            content_digest(&canonical)
                .0
                .as_bytes()
                .strip_prefix(b"sha256:"),
            Some(digest.as_slice())
        );
        assert_eq!(
            payload_checksum(&record.payload, canonical.len() - 1, &mut Work::default())
                .unwrap_err(),
            byte_limit()
        );
    }
}
