use super::*;
use latent_artifacts::package::{artifact_blob_digest, PackageKind};
use serde_json::{json, Value};

fn row(name: &str) -> SbomInventoryEntry {
    SbomInventoryEntry {
        kind: SbomEntryKind::GuestDependency,
        name: name.into(),
        version: Some("1.0.0".into()),
        source: Some("https://example.com/project".into()),
        license_expression: Some("MIT OR Apache-2.0".into()),
        digest: Some(artifact_blob_digest(b"archive checksum declared by lock")),
        digest_scope: Some(SbomDigestScope::RegistryArchiveDeclared),
        size: None,
        path: None,
        manifest_digest: Some(artifact_blob_digest(b"observed manifest")),
        manifest_size: Some(17),
        origin: SbomEntryOrigin::ObservedCache,
    }
}
fn inventory() -> SbomInventory {
    SbomInventory {
        format_version: 1,
        package_kind: PackageKind::Capsule,
        package_name: "sample".into(),
        package_version: "1.0.0".into(),
        dependency_completeness: SbomDependencyCompleteness::ObservedUnitsIncomplete,
        source_snapshot_digest: Some(artifact_blob_digest(b"snapshot")),
        entries: vec![row("zeta"), row("alpha")],
    }
}
fn inspect(value: &Value) -> Result<SbomInspection, latent_core::PlatformError> {
    inspect_cyclonedx_sbom(
        CYCLONEDX_JSON_MEDIA_TYPE,
        &serde_json::to_vec(value).unwrap(),
        SbomLimits::default(),
    )
}
fn bom() -> Value {
    serde_json::from_slice(
        generate_cyclonedx_sbom(inventory(), SbomLimits::default())
            .unwrap()
            .bytes(),
    )
    .unwrap()
}

#[test]
fn deterministic_role_separation_and_exact_received_identity() {
    let mut input = inventory();
    let mut host = input.entries[0].clone();
    host.kind = SbomEntryKind::BuildDependency;
    input.entries.push(host);
    let first = generate_cyclonedx_sbom(input.clone(), SbomLimits::default()).unwrap();
    input.entries.reverse();
    let second = generate_cyclonedx_sbom(input, SbomLimits::default()).unwrap();
    assert_eq!(first.bytes(), second.bytes());
    let mut decoded: Value = serde_json::from_slice(first.bytes()).unwrap();
    decoded["components"].as_array_mut().unwrap().reverse();
    decoded["metadata"]["properties"]
        .as_array_mut()
        .unwrap()
        .reverse();
    let reordered = serde_json::to_vec_pretty(&decoded).unwrap();
    let checked =
        inspect_cyclonedx_sbom(CYCLONEDX_JSON_MEDIA_TYPE, &reordered, SbomLimits::default())
            .unwrap();
    assert_eq!(checked.inventory().entries.len(), 3);
    assert_eq!(checked.digest(), &artifact_blob_digest(&reordered));
    assert_ne!(checked.digest(), first.digest());
    assert!(!String::from_utf8_lossy(first.bytes()).contains("lsf.package.digest"));
}

#[test]
fn duplicate_identity_and_conflicting_context_attribution_fail() {
    let mut duplicate = inventory();
    duplicate.entries.push(duplicate.entries[0].clone());
    assert_eq!(
        generate_cyclonedx_sbom(duplicate, SbomLimits::default())
            .unwrap_err()
            .message,
        "duplicate-sbom-entry"
    );
    let mut conflict = inventory();
    let mut host = conflict.entries[0].clone();
    host.kind = SbomEntryKind::ProcMacro;
    host.license_expression = None;
    conflict.entries.push(host);
    assert_eq!(
        generate_cyclonedx_sbom(conflict, SbomLimits::default())
            .unwrap_err()
            .message,
        "conflicting-sbom-dependency-attribution"
    );
}

#[test]
fn source_identity_rejects_paths_credentials_and_hidden_url_fields() {
    for bad in [
        "C:/private/cache",
        "file:///tmp/cache",
        "https://user:secret@example.com/repo",
        "https://example.com/repo?token=secret",
        "https://example.com:443/repo",
        "https://example.com/%2e%2e/private",
        "https://example.com/../private",
        "urn:lsf:workspace:../private",
    ] {
        let mut value = inventory();
        value.entries[0].source = Some(bad.into());
        assert!(
            generate_cyclonedx_sbom(value, SbomLimits::default()).is_err(),
            "{bad}"
        );
    }
}

#[test]
fn spdx_vocabulary_grammar_operators_and_complexity_are_validated() {
    for good in [
        "MIT",
        "Apache-2.0",
        "(MIT OR Apache-2.0) AND BSD-3-Clause",
        "GPL-2.0-only WITH Classpath-exception-2.0",
    ] {
        let mut value = inventory();
        value.entries[0].license_expression = Some(good.into());
        generate_cyclonedx_sbom(value, SbomLimits::default()).unwrap();
    }
    for bad in [
        "MIT oR Apache-2.0",
        "MIT and Apache-2.0",
        "NOT-A-LICENSE",
        "MIT Apache-2.0",
        "MIT OR",
        "LicenseRef-proprietary",
        "MIT WITH AdditionRef-custom",
        "Classpath-exception-2.0",
    ] {
        let mut value = inventory();
        value.entries[0].license_expression = Some(bad.into());
        assert!(
            generate_cyclonedx_sbom(value, SbomLimits::default()).is_err(),
            "{bad}"
        );
    }
    for bad in [
        format!("{}MIT{}", "(".repeat(17), ")".repeat(17)),
        vec!["MIT"; 70].join(" OR "),
    ] {
        let mut value = inventory();
        value.entries[0].license_expression = Some(bad);
        assert!(generate_cyclonedx_sbom(value, SbomLimits::default()).is_err());
    }
}

#[test]
fn component_profile_rejects_wrong_types_hashes_statuses_and_references() {
    let original = bom();
    for (pointer, replacement) in [
        ("/components/0/type", json!("application")),
        ("/components/0/bom-ref", json!("urn:lsf:entry:wrong")),
        ("/components/0/hashes/0/alg", json!("SHA-512")),
        ("/components/0/hashes/0/content", json!("a".repeat(40))),
        ("/components/0/hashes/0/content", json!("A".repeat(64))),
        ("/components/0/licenses", json!([])),
        ("/components/0/version", Value::Null),
        (
            "/metadata/component/bom-ref",
            json!("urn:lsf:package:final-sha"),
        ),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = replacement;
        assert!(inspect(&value).is_err(), "{pointer}");
    }
    let mut status = original.clone();
    for prop in status["components"][0]["properties"]
        .as_array_mut()
        .unwrap()
    {
        if prop["name"] == "lsf:license-status" {
            prop["value"] = json!("unavailable");
        }
    }
    assert_eq!(
        inspect(&status).unwrap_err().message,
        "sbom-attribution-status-mismatch"
    );
    let mut unknown = original.clone();
    unknown["components"][0]["externalReferences"] = json!([]);
    assert!(inspect(&unknown).is_err());
    let mut duplicate = original;
    let properties = duplicate["components"][0]["properties"]
        .as_array_mut()
        .unwrap();
    properties.push(properties[0].clone());
    assert_eq!(
        inspect(&duplicate).unwrap_err().message,
        "duplicate-sbom-property"
    );
}

#[test]
fn normalized_input_and_json_are_bounded_before_typed_materialization() {
    let bytes = serde_json::to_vec(&inventory()).unwrap();
    decode_sbom_inventory(&bytes, SbomLimits::default()).unwrap();
    assert!(decode_sbom_inventory(
        &bytes,
        SbomLimits {
            max_entries: 1,
            ..SbomLimits::default()
        }
    )
    .is_err());
    for limits in [
        SbomLimits {
            max_document_bytes: usize::MAX,
            ..SbomLimits::default()
        },
        SbomLimits {
            max_entries: usize::MAX,
            ..SbomLimits::default()
        },
        SbomLimits {
            max_string_bytes: usize::MAX,
            ..SbomLimits::default()
        },
    ] {
        assert!(decode_sbom_inventory(&bytes, limits).is_err());
    }
    let duplicate = String::from_utf8(bytes.clone()).unwrap().replacen(
        "\"formatVersion\":1",
        "\"formatVersion\":1,\"formatVersion\":1",
        1,
    );
    assert!(decode_sbom_inventory(duplicate.as_bytes(), SbomLimits::default()).is_err());
    let mut value = serde_json::from_slice::<Value>(&bytes).unwrap();
    value["entries"][0]["version"] = Value::Null;
    assert!(
        decode_sbom_inventory(&serde_json::to_vec(&value).unwrap(), SbomLimits::default()).is_err()
    );
    let nested = format!("{}0{}", "[".repeat(14), "]".repeat(14));
    assert!(decode_sbom_inventory(nested.as_bytes(), SbomLimits::default()).is_err());
    let document = generate_cyclonedx_sbom(inventory(), SbomLimits::default()).unwrap();
    assert!(inspect_cyclonedx_sbom(
        CYCLONEDX_JSON_MEDIA_TYPE,
        document.bytes(),
        SbomLimits {
            max_document_bytes: document.bytes().len() - 1,
            ..SbomLimits::default()
        }
    )
    .is_err());
}

#[test]
fn generated_checked_document_retains_no_caller_spare_capacity() {
    let expected = generate_cyclonedx_sbom(inventory(), SbomLimits::default()).unwrap();
    let mut large = inventory();
    large.entries.reserve(50_000);
    large.package_name.reserve(1_000_000);
    for entry in &mut large.entries {
        entry.name.reserve(1_000_000);
    }
    let actual = generate_cyclonedx_sbom(large, SbomLimits::default()).unwrap();
    assert_eq!(actual.bytes(), expected.bytes());
    assert_eq!(actual.bytes.len(), expected.bytes.len());
}

#[test]
fn package_input_bounds_precede_inventory_work() {
    let layer = LayerInput {
        path: "index.html".into(),
        role: LayerRole::Asset,
        media_type: "text/html".into(),
        bytes: Vec::new(),
    };
    let input = PackageInput {
        kind: PackageKind::BrowserAssets,
        name: "sample".into(),
        version: "1".into(),
        entrypoint: "index.html".into(),
        annotations: std::collections::BTreeMap::default(),
        layers: vec![layer; 257],
    };
    let mut malformed = inventory();
    malformed.format_version = 999;
    assert_eq!(
        build_package_with_sbom(input, malformed, PackagingLimits::default())
            .unwrap_err()
            .message,
        "package-input-metadata-limit"
    );
}

#[test]
fn browser_inventory_matches_the_offline_schema_conformance_fixture() {
    let input = decode_sbom_inventory(
        include_bytes!("../../tests/fixtures/sbom/browser-inputs.json"),
        SbomLimits::default(),
    )
    .unwrap();
    let output = generate_cyclonedx_sbom(input, SbomLimits::default()).unwrap();
    assert_eq!(
        output.bytes(),
        include_bytes!("../../tests/fixtures/sbom/browser.cdx.json")
    );
}
