use super::*;
use serde_json::{json, Value};

const PACKET: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json"
));
const PRIOR: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-native-memory-capture-2026-10-14.json"
));
const CODEC: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../examples/java-transaction-schema/AggregateCodec.java"
));

struct Capture {
    profile: Profile,
    name: &'static str,
    declaration: &'static [u8],
    source: &'static [u8],
    codec: Option<&'static [u8]>,
}

const CAPTURES: [Capture; 4] = [
    Capture {
        profile: Profile::CurrentLegacy,
        name: "put-once-legacy-v1",
        declaration: include_bytes!("../fixtures/current-legacy-schema.json"),
        source: include_bytes!("../fixtures/current-legacy.java"),
        codec: None,
    },
    Capture {
        profile: Profile::CurrentCompatible,
        name: "put-once-compatible-v2",
        declaration: include_bytes!("../fixtures/current-compatible-reconstructed-schema.json"),
        source: include_bytes!("../fixtures/current-compatible-reconstructed.java"),
        codec: Some(CODEC),
    },
    Capture {
        profile: Profile::CurrentWriter,
        name: "put-once-writer-v2",
        declaration: include_bytes!("../fixtures/current-writer-reconstructed-schema.json"),
        source: include_bytes!("../fixtures/current-writer-reconstructed.java"),
        codec: Some(CODEC),
    },
    Capture {
        profile: Profile::CurrentDiagnostic,
        name: "put-once-diagnostics",
        declaration: include_bytes!("../fixtures/native-memory-diagnostic-schema.json"),
        source: include_bytes!("../fixtures/native-memory-diagnostic.java"),
        codec: None,
    },
];

fn input(profile: Profile) -> CurrentHttpInput<'static> {
    let writer = profile == Profile::CurrentWriter;
    CurrentHttpInput {
        component: match profile {
            Profile::CurrentLegacy => {
                "sha256:eae8efb880744d60ba7163590fb0fd825d45cb2018760b7c1cd00272e4cefecd"
            }
            Profile::CurrentCompatible => {
                "sha256:ecd7d566a6403468a1166ad0c9042a51cce47e12f92e63907bce680daa08f813"
            }
            Profile::CurrentWriter => {
                "sha256:05e8bbaa90168aa250d779431a317fcde8f785d93e511054e0d5facaaad5787d"
            }
            Profile::CurrentDiagnostic => {
                "sha256:b46606299b77eeb9efb12abb2bdb793d5bba78bb1f8dc42d1be4bc92f5463115"
            }
            _ => panic!("a captured current profile is required"),
        },
        companion: if writer {
            "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49"
        } else {
            "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d"
        },
        marker: include_bytes!("../fixtures/http-marker-reconstructed.json"),
        requirements_digest: if writer {
            "sha256:aee137a27e70d85bee5d81aea605e662bbbaaee56b3b51140bd0d5d51c14a88f"
        } else {
            "sha256:d6190b8331152fabb6e030c476883445d97793923cf6bb37ec61bd2df5a88dd6"
        },
        requirements: if writer {
            include_bytes!("../fixtures/http-writer-requirements-reconstructed.json")
        } else {
            include_bytes!("../fixtures/http-requirements-reconstructed.json")
        },
    }
}

#[test]
fn authentic_reconstructed_tuple_keeps_all_four_compiler_source_and_codec_associations() {
    let packet: Value = serde_json::from_slice(PACKET).unwrap();
    let prior: Value = serde_json::from_slice(PRIOR).unwrap();
    for capture in CAPTURES {
        let input = input(capture.profile);
        let pin = &packet["captures"]["variants"][capture.name]["materials"];
        let old = &prior["captures"]["variants"][capture.name]["materials"];
        assert_eq!(
            SelectedHttpCustody::select(capture.profile, &input).unwrap(),
            SelectedHttpCustody::Reconstructed
        );
        for field in [
            "component",
            "companion",
            "capsuleSource",
            "applicationSchemaInputs",
            "compilerInputs",
        ] {
            assert_eq!(pin[field], old[field], "{} {field}", capture.name);
        }
        assert_eq!(pin["component"]["sha256"], input.component);
        assert_eq!(pin["companion"]["sha256"], input.companion);
        for (field, bytes) in [
            ("currentHttpMarker", input.marker),
            ("requirements", input.requirements),
            ("capsuleSource", capture.source),
            ("applicationSchemaInputs", capture.declaration),
        ] {
            assert_eq!(pin[field]["sha256"], format!("sha256:{}", digest(bytes)));
            assert_eq!(pin[field]["bytes"].as_u64(), Some(bytes.len() as u64));
        }
        assert_eq!(pin["requirements"]["sha256"], input.requirements_digest);
        let marker: Value = serde_json::from_slice(input.marker).unwrap();
        assert_eq!(
            marker["idempotencyProfile"],
            packet["captures"]["nativeIdempotencyProfile"]
        );
    }
}

#[test]
fn reconstructed_review_uses_new_marker_proof_and_preserves_original_codec() {
    for capture in CAPTURES {
        let schema = capture
            .profile
            .review(
                [1; 32],
                capture.declaration,
                capture.source,
                capture.codec,
                Some(input(capture.profile)),
            )
            .expect("the authentic reconstructed source supports codec review");
        assert_ne!(schema.proof_digest(), [0; 32]);
        assert_eq!(
            schema.proof_digest(),
            capture.profile.conformance_with_marker(MARKER).unwrap()
        );
        assert_ne!(
            schema.proof_digest(),
            capture.profile.conformance().unwrap()
        );
        assert_ne!(
            schema.proof_digest(),
            capture
                .profile
                .conformance_with_marker(HttpCustody::Fresh.marker())
                .unwrap()
        );
        let value = u64::MAX;
        assert_eq!(
            capture
                .profile
                .decode("application/vnd.lsf.aggregate-v1", &value.to_le_bytes()),
            Some(value)
        );
    }
}

#[test]
fn reconstructed_tuple_refuses_mixed_historical_or_foreign_associations() {
    let legacy = input(Profile::CurrentLegacy);
    let oversized = [0; 8193];
    for changed in [
        CurrentHttpInput {
            component: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            ..legacy
        },
        CurrentHttpInput {
            component: "sha256:322dfed5d9838edfbbd53bf0672c31f849ac7c7309358975bf1bf6c10b0a24bb",
            ..legacy
        },
        CurrentHttpInput {
            companion: "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49",
            ..legacy
        },
        CurrentHttpInput {
            requirements: include_bytes!("../fixtures/http-writer-requirements-reconstructed.json"),
            ..legacy
        },
        CurrentHttpInput {
            requirements_digest:
                "sha256:49c9b8af6be278198d286b776f492e0fda9a6621b9b2fcd36aa788d77a2e5c54",
            ..legacy
        },
        CurrentHttpInput {
            marker: include_bytes!("../fixtures/http-marker-fresh.json"),
            ..legacy
        },
        CurrentHttpInput {
            marker: b"changed",
            ..legacy
        },
        CurrentHttpInput {
            requirements: b"changed",
            ..legacy
        },
        CurrentHttpInput {
            marker: &oversized,
            ..legacy
        },
        CurrentHttpInput {
            requirements: &oversized,
            ..legacy
        },
    ] {
        assert!(SelectedHttpCustody::select(Profile::CurrentLegacy, &changed).is_err());
    }
    assert!(SelectedHttpCustody::select(Profile::CurrentWriter, &legacy).is_err());
    assert!(SelectedHttpCustody::select(Profile::Legacy, &legacy).is_err());
    let old_diagnostic = CurrentHttpInput {
        component: "sha256:322dfed5d9838edfbbd53bf0672c31f849ac7c7309358975bf1bf6c10b0a24bb",
        ..input(Profile::CurrentDiagnostic)
    };
    assert_eq!(
        Profile::installed(old_diagnostic.component).unwrap(),
        Profile::CurrentDiagnostic
    );
    assert!(SelectedHttpCustody::select(Profile::CurrentDiagnostic, &old_diagnostic).is_err());
}

#[test]
fn reconstructed_review_retains_all_original_declaration_and_codec_gates() {
    for capture in CAPTURES {
        let profile = capture.profile;
        for (source, codec, http) in [
            (b"changed".as_slice(), capture.codec, Some(input(profile))),
            (
                capture.source,
                Some(b"changed codec".as_slice()),
                Some(input(profile)),
            ),
            (capture.source, capture.codec, None),
        ] {
            assert!(profile
                .review([1; 32], capture.declaration, source, codec, http)
                .is_err());
        }
        if capture.codec.is_some() {
            assert!(profile
                .review(
                    [1; 32],
                    capture.declaration,
                    capture.source,
                    None,
                    Some(input(profile))
                )
                .is_err());
        }
        let declaration: Value = serde_json::from_slice(capture.declaration).unwrap();
        for (field, value) in [
            ("schemaVersion", json!("unknown")),
            ("variant", json!("unknown")),
            ("effect", json!("put-once")),
            ("readers", json!([])),
            ("writers", json!([])),
            ("sourceDigest", json!("sha256:changed")),
            ("publicationReviewGranted", json!(true)),
            ("componentCompiled", json!(true)),
            ("stateExecutionQualified", json!(true)),
            ("unreviewedField", json!(true)),
        ] {
            let mut changed = declaration.clone();
            changed[field] = value;
            assert!(
                profile
                    .review(
                        [1; 32],
                        &serde_json::to_vec(&changed).unwrap(),
                        capture.source,
                        capture.codec,
                        Some(input(profile))
                    )
                    .is_err(),
                "{field}"
            );
        }
        assert!(profile
            .review(
                [1; 32],
                &[0; 4097],
                capture.source,
                capture.codec,
                Some(input(profile))
            )
            .is_err());
    }
}
