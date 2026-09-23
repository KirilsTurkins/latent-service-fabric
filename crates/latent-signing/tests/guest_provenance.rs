#[path = "build_provenance/support.rs"]
#[allow(dead_code)]
mod support;
use latent_signing::*;
use support::*;

fn guest(c: bool) -> BuildObservation {
    let mut value = observation();
    value.build_type = if c {
        C_GUEST_BUILD_TYPE
    } else {
        RUST_GUEST_BUILD_TYPE
    }
    .into();
    value.source.capture = "explicit-input-files".into();
    value.source.revision = value.source.snapshot_digest[7..].into();
    value.dependency_completeness = "declared-inputs-incomplete".into();
    value.materials.push(BuildMaterial {
        name: "wit-bindgen".into(),
        digest: value.source.snapshot_digest.clone(),
        size: 1,
    });
    if c {
        value.parameters = BuildRecipe::C(CBuildParameters {
            compiler: "zig-cc".into(),
            fixture: "blob".into(),
            target: "wasm32-wasi".into(),
            optimization: "O2".into(),
        });
        value
            .materials
            .retain(|m| !matches!(m.name.as_str(), "cargo" | "rustc" | "dependency-lock"));
        value.materials.push(BuildMaterial {
            name: "zig".into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    } else if let BuildRecipe::Rust(p) = &mut value.parameters {
        p.cargo_example = "guest-http".into();
    }
    value
}

fn capsule() -> BuildObservation {
    let mut value = guest(false);
    value.build_type = RUST_CAPSULE_BUILD_TYPE.into();
    value.parameters = BuildRecipe::RustCapsule(RustCapsuleBuildParameters {
        cargo_package: "my-capsule".into(),
        crate_type: "cdylib".into(),
        target: "wasm32-unknown-unknown".into(),
        profile: "release".into(),
        locked: true,
        incremental: false,
    });
    for name in ["packager", "binding-lock"] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    value
}

#[test]
fn guest_profiles_require_separate_builder_approval_and_preserve_legacy_echo() {
    let (signer, public, _) = signer(BUILDER);
    for observation in [guest(false), guest(true), capsule()] {
        let evidence = signed(&signer, &observation);
        let mut policy = policy_value(&public);
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
        policy["requirements"][0]["buildType"] = observation.build_type.into();
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap();
        let legacy = signed(&signer, &support::observation());
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), legacy.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
    let evidence = signed(&signer, &capsule());
    for build_type in [RUST_GUEST_BUILD_TYPE, C_GUEST_BUILD_TYPE] {
        let mut policy = policy_value(&public);
        policy["requirements"][0]["buildType"] = build_type.into();
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
    let value = serde_json::to_value(observation()).unwrap();
    assert_eq!(value["parameters"]["cargoExample"], "echo-capsule");
    assert!(value["parameters"].get("Rust").is_none());
}

#[test]
fn mixed_recipes_missing_tools_and_unbounded_claims_are_rejected() {
    for valid in [guest(false), guest(true), capsule()] {
        for case in 0..7 {
            let mut value = serde_json::to_value(&valid).unwrap();
            match case {
                0 => {
                    value["parameters"] =
                        serde_json::to_value(support::observation().parameters).unwrap();
                }
                1 => {
                    value["source"]["capture"] = "git-archive-allowlist".into();
                }
                2 => {
                    value["hermetic"] = true.into();
                }
                3 => {
                    value["dependencyCompleteness"] = "complete".into();
                }
                4 => {
                    value["materials"]
                        .as_array_mut()
                        .unwrap()
                        .retain(|m| m["name"] != "wit-bindgen");
                }
                5 => {
                    value["source"]["revision"] = "0".repeat(64).into();
                }
                _ => {
                    value["parameters"]["unreviewedOption"] = true.into();
                }
            }
            assert!(
                decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                    .is_err(),
                "case {case}"
            );
        }
    }

    for name in ["packager", "binding-lock"] {
        let mut value = capsule();
        value.materials.retain(|m| m.name != name);
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
    for (field, replacement) in [
        ("cargoPackage", serde_json::json!("../other")),
        ("cargoPackage", serde_json::json!("UPPER")),
        ("cargoPackage", serde_json::json!("a".repeat(65))),
        ("crateType", serde_json::json!("bin")),
        ("target", serde_json::json!("wasm32-wasip2")),
        ("locked", serde_json::json!(false)),
        ("incremental", serde_json::json!(true)),
    ] {
        let mut value = serde_json::to_value(capsule()).unwrap();
        value["parameters"][field] = replacement;
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
}
