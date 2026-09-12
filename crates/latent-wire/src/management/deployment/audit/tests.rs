use super::*;
use latent_core::{Metadata, TenantId};
use latent_manifest::{JsonManifestCodec, ManifestCodec};

fn manifest() -> DeploymentManifest {
    JsonManifestCodec::default()
        .decode_deployment(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../latent-manifest/tests/fixtures/valid-deployment-v1alpha1.json"
        )))
        .unwrap()
}

// Construct only the binding under test; no fabricated durable attempt or ack.
fn binding(manifest: &DeploymentManifest, expected: Option<u64>, delete: bool) -> DeploymentAudit {
    DeploymentAudit {
        expected: Some(Expected {
            id: manifest.id.clone(),
            digest: if delete {
                digest::delete(&manifest.id, expected)
            } else {
                digest::apply(manifest, expected)
            },
            generation: expected,
        }),
        ..DeploymentAudit::disabled(delete)
    }
}

fn versioned(manifest: DeploymentManifest, generation: u64) -> VersionedDeployment {
    VersionedDeployment {
        manifest,
        generation,
    }
}

#[test]
fn normalized_wire_request_binds_the_catalog_codec_result() {
    let codec = JsonManifestCodec::default();
    let mut request = manifest();
    request.release.0 = format!("sha256:{}", "A".repeat(64));
    request.grants.reverse();
    request.grants[0].operations = vec!["write".into(), "read".into()];
    request.placement.architectures.reverse();
    request.placement.regions = vec!["us-east".into(), "eu-west".into()];
    let stored = codec
        .decode_deployment(&codec.encode_deployment(&request).unwrap())
        .unwrap();
    // The normalizer's field-level behavior belongs to latent-manifest's tests.
    // This boundary proves both representations produce the same audit binding.
    request.normalize_storage_fields();
    assert_eq!(
        digest::apply(&request, Some(7)),
        digest::apply(&stored, Some(7))
    );
    assert!(binding(&request, Some(7), false).matches(&versioned(stored, 12), RouteGeneration(12)));
}

#[test]
fn apply_rejects_a_changed_returned_subject_or_request() {
    type Mutation = fn(&mut DeploymentManifest);
    let request = manifest();
    let audit = binding(&request, Some(7), false);
    assert!(audit.matches(&versioned(request.clone(), 12), RouteGeneration(12)));
    let mutations: [Mutation; 9] = [
        |m| m.id.0.push_str("-other"),
        |m| m.service.0.push_str("-other"),
        |m| m.release.0 = format!("sha256:{}", "2".repeat(64)),
        |m| m.metadata.tenant = Some(TenantId("another-tenant".into())),
        |m| m.route_weight -= 1,
        |m| m.resources.wall_time_limit_millis = Some(25),
        |m| m.grants[0].policy.0.push_str("-other"),
        |m| m.availability.minimum_zones += 1,
        |m| m.placement.required_features.push("simd".into()),
    ];
    for mutate in mutations {
        let mut changed = request.clone();
        mutate(&mut changed);
        assert!(!audit.matches(&versioned(changed, 12), RouteGeneration(12)));
    }
}

#[test]
fn apply_requires_consistent_positive_and_advancing_generations() {
    let request = manifest();
    let audit = binding(&request, Some(7), false);
    for (object, catalog) in [(0, 0), (0, 8), (8, 0), (8, 9), (9, 8), (6, 6), (7, 7)] {
        assert!(
            !audit.matches(
                &versioned(request.clone(), object),
                RouteGeneration(catalog)
            ),
            "object={object}, catalog={catalog}"
        );
    }
    // Other deployments can advance the global catalog between two mutations.
    for generation in [8, 12, u64::MAX] {
        assert!(audit.matches(
            &versioned(request.clone(), generation),
            RouteGeneration(generation)
        ));
    }
    for expected in [None, Some(0)] {
        assert!(binding(&request, expected, false)
            .matches(&versioned(request.clone(), 1), RouteGeneration(1)));
    }
    assert!(!binding(&request, Some(u64::MAX), false)
        .matches(&versioned(request, u64::MAX), RouteGeneration(u64::MAX)));
}

#[test]
fn delete_binds_the_id_and_prior_object_generation() {
    let request = manifest();
    let audit = binding(&request, Some(7), true);
    assert!(audit.matches(&versioned(request.clone(), 7), RouteGeneration(12)));
    for (object, catalog) in [(0, 12), (6, 12), (8, 12), (7, 0), (7, 6), (7, 7)] {
        assert!(!audit.matches(
            &versioned(request.clone(), object),
            RouteGeneration(catalog)
        ));
    }
    let mut wrong = request.clone();
    wrong.id.0.push_str("-other");
    assert!(!audit.matches(&versioned(wrong, 7), RouteGeneration(12)));
    let unconditional = binding(&request, None, true);
    assert!(unconditional.matches(&versioned(request.clone(), 3), RouteGeneration(12)));
    for expected in [None, Some(0)] {
        assert!(!binding(&request, expected, true)
            .matches(&versioned(request.clone(), 0), RouteGeneration(12)));
    }
    assert!(!binding(&request, Some(0), true).matches(&versioned(request, 7), RouteGeneration(12)));
}

#[test]
fn optional_preconditions_and_optional_resources_have_distinct_identities() {
    let mut request = manifest();
    let expected = [None, Some(0), Some(7), Some(u64::MAX)];
    for (index, left) in expected.iter().enumerate() {
        for right in &expected[index + 1..] {
            assert_ne!(
                digest::apply(&request, *left),
                digest::apply(&request, *right)
            );
            assert_ne!(
                digest::delete(&request.id, *left),
                digest::delete(&request.id, *right)
            );
        }
        assert_ne!(
            digest::apply(&request, *left),
            digest::delete(&request.id, *left)
        );
    }
    request.resources.wall_time_limit_millis = None;
    let absent = digest::apply(&request, None);
    request.resources.wall_time_limit_millis = Some(0);
    assert_ne!(absent, digest::apply(&request, None));
}

#[test]
fn metadata_insertion_order_is_irrelevant_but_field_boundaries_are_not() {
    fn metadata(entries: &[(&str, &str)]) -> Metadata {
        entries
            .iter()
            .map(|(k, v)| ((*k).into(), (*v).into()))
            .collect()
    }
    let mut left = manifest();
    let mut right = left.clone();
    for values in [
        &mut left.metadata.labels,
        &mut left.metadata.annotations,
        &mut left.grants[0].constraints,
    ] {
        *values = metadata(&[("z", "last"), ("a", "first")]);
    }
    for values in [
        &mut right.metadata.labels,
        &mut right.metadata.annotations,
        &mut right.grants[0].constraints,
    ] {
        *values = metadata(&[("a", "first"), ("z", "last")]);
    }
    assert_eq!(digest::apply(&left, None), digest::apply(&right, None));
    assert_eq!(
        digest::receipt(&versioned(left.clone(), 2), RouteGeneration(3), true),
        digest::receipt(&versioned(right.clone(), 2), RouteGeneration(3), true)
    );
    left.metadata.labels = metadata(&[("ab", "c")]);
    right.metadata.labels = metadata(&[("a", "bc")]);
    assert_ne!(digest::apply(&left, None), digest::apply(&right, None));
    right = left.clone();
    left.grants[0].operations = vec!["ab".into(), "c".into()];
    right.grants[0].operations = vec!["a".into(), "bc".into()];
    assert_ne!(digest::apply(&left, None), digest::apply(&right, None));
    right = left.clone();
    std::mem::swap(&mut right.metadata.labels, &mut right.metadata.annotations);
    assert_ne!(digest::apply(&left, None), digest::apply(&right, None));
}

#[test]
fn receipt_digest_binds_operation_stamps_and_the_returned_manifest() {
    let original = versioned(manifest(), 7);
    let receipt = digest::receipt(&original, RouteGeneration(12), false);
    assert_ne!(
        receipt,
        digest::receipt(&original, RouteGeneration(12), true)
    );
    assert_ne!(
        receipt,
        digest::receipt(&original, RouteGeneration(13), false)
    );
    let mut changed = original.clone();
    changed.generation = 8;
    assert_ne!(
        receipt,
        digest::receipt(&changed, RouteGeneration(12), false)
    );
    changed = original.clone();
    changed
        .manifest
        .metadata
        .annotations
        .insert("receipt".into(), "changed".into());
    assert_ne!(
        receipt,
        digest::receipt(&changed, RouteGeneration(12), false)
    );
}
