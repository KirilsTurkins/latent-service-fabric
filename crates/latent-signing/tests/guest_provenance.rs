#[path = "build_provenance/support.rs"]
#[allow(dead_code)]
mod support;
use latent_signing::*;
use support::*;

#[test]
fn dotnet_capsules_require_the_closed_native_aot_recipe_and_separate_approval() {
    let mut value = standalone();
    value.build_type = DOTNET_CAPSULE_BUILD_TYPE.into();
    value.parameters = BuildRecipe::DotnetCapsule(DotnetCapsuleBuildParameters {
        compiler: "native-aot-llvm".into(),
        bindings: "wit-bindgen-csharp".into(),
        language: "csharp".into(),
        target: "wasi-wasm".into(),
        runtime: "native-aot".into(),
        locked: true,
        ambient_wasi: false,
    });
    for name in ["dotnet", "closed-runtime", "compiler-inputs"] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &value);
    let mut policy = policy_value(&public);
    assert_eq!(
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::PredicateDisallowed
    );
    policy["requirements"][0]["buildType"] = DOTNET_CAPSULE_BUILD_TYPE.into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let encoded = serde_json::to_value(&value).unwrap();
    assert!(matches!(
        decode_build_observation(&serde_json::to_vec(&encoded).unwrap(), Default::default())
            .unwrap()
            .parameters,
        BuildRecipe::DotnetCapsule(_)
    ));
    for (field, invalid) in [
        ("compiler", serde_json::json!("different")),
        ("bindings", serde_json::json!("different")),
        ("language", serde_json::json!("different")),
        ("target", serde_json::json!("different")),
        ("runtime", serde_json::json!("different")),
        ("locked", serde_json::json!(false)),
        ("ambientWasi", serde_json::json!(true)),
        ("unreviewedOption", serde_json::json!(true)),
    ] {
        let mut wrong = encoded.clone();
        wrong["parameters"][field] = invalid;
        assert!(
            decode_build_observation(&serde_json::to_vec(&wrong).unwrap(), Default::default())
                .is_err()
        );
    }
    for name in [
        "dotnet",
        "wit-bindgen",
        "closed-runtime",
        "compiler-inputs",
        "dependency-lock",
        "contracts-tool",
        "packager",
        "package-inputs",
    ] {
        let mut wrong = encoded.clone();
        wrong["materials"]
            .as_array_mut()
            .unwrap()
            .retain(|row| row["name"] != name);
        assert!(
            decode_build_observation(&serde_json::to_vec(&wrong).unwrap(), Default::default())
                .is_err()
        );
    }
}

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

#[test]
fn guest_profiles_require_separate_builder_approval_and_preserve_legacy_echo() {
    let (signer, public, _) = signer(BUILDER);
    for c in [false, true] {
        let observation = guest(c);
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
    for fixture in [
        "blob",
        "callee",
        "events",
        "http",
        "metrics",
        "random",
        "secrets",
        "service",
        "streaming",
        "application",
    ] {
        let mut observation = guest(true);
        let BuildRecipe::C(parameters) = &mut observation.parameters else {
            unreachable!()
        };
        parameters.fixture = fixture.into();
        let evidence = signed(&signer, &observation);
        let mut policy = policy_value(&public);
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
        policy["requirements"][0]["buildType"] = C_GUEST_BUILD_TYPE.into();
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap();
    }
    let value = serde_json::to_value(observation()).unwrap();
    assert_eq!(value["parameters"]["cargoExample"], "echo-capsule");
    assert!(value["parameters"].get("Rust").is_none());
}

#[test]
fn mixed_recipes_missing_tools_and_unbounded_claims_are_rejected() {
    for invalid in ["arbitrary", "../blob", "", "application;sh"] {
        let mut value = serde_json::to_value(guest(true)).unwrap();
        value["parameters"]["fixture"] = invalid.into();
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
    for c in [false, true] {
        let valid = guest(c);
        for case in 0..7 {
            let mut value = serde_json::to_value(&valid).unwrap();
            match case {
                0 => {
                    value["parameters"] = serde_json::to_value(guest(!c).parameters).unwrap();
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
}

fn java() -> BuildObservation {
    let mut value = observation();
    value.build_type = JAVA_CAPSULE_BUILD_TYPE.into();
    value.source.capture = "explicit-input-files".into();
    value.source.revision = value.source.snapshot_digest[7..].into();
    value.dependency_completeness = "declared-inputs-incomplete".into();
    value
        .materials
        .retain(|item| !matches!(item.name.as_str(), "cargo" | "rustc"));
    for name in [
        "java",
        "gradle",
        "clang",
        "wit-bindgen",
        "compiler-closure",
        "generated-bindings",
        "contracts-tool",
        "packager",
        "package-inputs",
    ] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    value.parameters = BuildRecipe::JavaCapsule(JavaCapsuleBuildParameters {
        compiler: "teavm-c".into(),
        entry_point: "dev.latent.app.Capsule".into(),
        target: "wasm32-wasip1".into(),
        bindings: "lsf-java-wit-v1".into(),
        optimization: "O2".into(),
        java_heap_bytes: 4_194_304,
    });
    value
}

#[test]
fn java_requires_separate_source_bound_builder_approval() {
    let (signer, public, _) = signer(BUILDER);
    let value = java();
    let evidence = signed(&signer, &value);
    let mut policy = policy_value(&public);
    for old in [
        PROVENANCE_BUILD_TYPE,
        C_GUEST_BUILD_TYPE,
        RUST_GUEST_BUILD_TYPE,
        RUST_CAPSULE_BUILD_TYPE,
    ] {
        policy["requirements"][0]["buildType"] = old.into();
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
    policy["requirements"][0]["buildType"] = JAVA_CAPSULE_BUILD_TYPE.into();
    policy["requirements"][0]["sourceSnapshotDigest"] = value.source.snapshot_digest.clone().into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    policy["requirements"][0]["sourceSnapshotDigest"] = format!("sha256:{}", "0".repeat(64)).into();
    assert_eq!(
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::SourceDisallowed
    );
}

#[test]
fn java_recipe_and_every_observed_compiler_input_are_closed() {
    let original = serde_json::to_value(java()).unwrap();
    decode_build_observation(&serde_json::to_vec(&original).unwrap(), Default::default()).unwrap();
    for material in original["materials"].as_array().unwrap() {
        let mut changed = original.clone();
        changed["materials"]
            .as_array_mut()
            .unwrap()
            .retain(|item| item["name"] != material["name"]);
        assert!(decode_build_observation(
            &serde_json::to_vec(&changed).unwrap(),
            Default::default()
        )
        .is_err());
    }
    for key in [
        "compiler",
        "entryPoint",
        "target",
        "bindings",
        "optimization",
        "javaHeapBytes",
        "unreviewedOption",
    ] {
        let mut changed = original.clone();
        changed["parameters"][key] = "unreviewed".into();
        assert!(decode_build_observation(
            &serde_json::to_vec(&changed).unwrap(),
            Default::default()
        )
        .is_err());
    }
    let mut changed = original;
    changed["parameters"]["javaHeapBytes"] = 8_388_608.into();
    assert!(
        decode_build_observation(&serde_json::to_vec(&changed).unwrap(), Default::default())
            .is_err()
    );
}

fn standalone() -> BuildObservation {
    let mut value = guest(false);
    value.build_type = RUST_CAPSULE_BUILD_TYPE.into();
    value.parameters = BuildRecipe::RustCapsule(RustCapsuleBuildParameters {
        cargo_package: "my-shipping-service".into(),
        manifest_path: "Cargo.toml".into(),
        crate_type: "cdylib".into(),
        target: "wasm32-unknown-unknown".into(),
        profile: "release".into(),
        locked: true,
        incremental: false,
    });
    for name in ["contracts-tool", "packager", "package-inputs"] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    value
}

fn standalone_go() -> BuildObservation {
    let mut value = standalone();
    value.build_type = GO_CAPSULE_BUILD_TYPE.into();
    value.parameters = BuildRecipe::GoCapsule(GoCapsuleBuildParameters {
        go_package: "my-greeting".into(),
        compiler: "componentize-go".into(),
        target: "wasm32-wasip1".into(),
        runtime: "go-component-async-v1".into(),
        locked: true,
        ambient_wasi: false,
    });
    value
        .materials
        .retain(|material| !matches!(material.name.as_str(), "cargo" | "rustc" | "wit-bindgen"));
    for name in ["go", "componentize-go"] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    value
}

#[test]
fn go_capsules_require_source_bound_go_builder_approval_and_closed_runtime_claims() {
    let (signer, public, _) = signer(BUILDER);
    let value = standalone_go();
    let evidence = signed(&signer, &value);
    let mut policy = policy_value(&public);
    assert!(verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .is_err());
    policy["requirements"][0]["buildType"] = GO_CAPSULE_BUILD_TYPE.into();
    policy["requirements"][0]["sourceRevision"] = value.source.revision.clone().into();
    policy["requirements"][0]["sourceSnapshotDigest"] = value.source.snapshot_digest.clone().into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let original = serde_json::to_value(&value).unwrap();
    for (field, invalid) in [
        ("goPackage", "../escape"),
        ("compiler", "cargo"),
        ("target", "native"),
        ("runtime", "ambient-wasi"),
    ] {
        let mut changed = original.clone();
        changed["parameters"][field] = invalid.into();
        assert!(decode_build_observation(
            &serde_json::to_vec(&changed).unwrap(),
            Default::default()
        )
        .is_err());
    }
    for field in ["locked", "ambientWasi"] {
        let mut changed = original.clone();
        changed["parameters"][field] = (field != "locked").into();
        assert!(decode_build_observation(
            &serde_json::to_vec(&changed).unwrap(),
            Default::default()
        )
        .is_err());
    }
    for tool in ["go", "componentize-go", "dependency-lock", "package-inputs"] {
        let mut changed = original.clone();
        changed["materials"]
            .as_array_mut()
            .unwrap()
            .retain(|m| m["name"] != tool);
        assert!(decode_build_observation(
            &serde_json::to_vec(&changed).unwrap(),
            Default::default()
        )
        .is_err());
    }
}

#[test]
fn typescript_capsules_have_a_closed_separately_approved_compiler_profile() {
    let mut value = standalone();
    value.build_type = TYPESCRIPT_CAPSULE_BUILD_TYPE.into();
    value.parameters = BuildRecipe::TypeScriptCapsule(TypeScriptCapsuleBuildParameters {
        compiler: "componentize-js".into(),
        bindings: "jco".into(),
        language: "typescript".into(),
        target: "wasm32-component".into(),
        runtime: "spidermonkey".into(),
        ambient_wasi: false,
    });
    for name in ["node", "compiler-inputs"] {
        value.materials.push(BuildMaterial {
            name: name.into(),
            digest: value.source.snapshot_digest.clone(),
            size: 1,
        });
    }
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &value);
    let mut policy = policy_value(&public);
    assert_eq!(
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::PredicateDisallowed
    );
    policy["requirements"][0]["buildType"] = TYPESCRIPT_CAPSULE_BUILD_TYPE.into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let encoded = serde_json::to_value(&value).unwrap();
    for field in [
        "compiler",
        "bindings",
        "language",
        "target",
        "runtime",
        "unreviewedOption",
    ] {
        let mut invalid = encoded.clone();
        invalid["parameters"][field] = "different".into();
        assert!(decode_build_observation(
            &serde_json::to_vec(&invalid).unwrap(),
            Default::default()
        )
        .is_err());
    }
    let mut ambient = encoded.clone();
    ambient["parameters"]["ambientWasi"] = true.into();
    assert!(
        decode_build_observation(&serde_json::to_vec(&ambient).unwrap(), Default::default())
            .is_err()
    );
    for name in [
        "node",
        "compiler-inputs",
        "dependency-lock",
        "contracts-tool",
        "packager",
        "package-inputs",
    ] {
        let mut invalid = encoded.clone();
        invalid["materials"]
            .as_array_mut()
            .unwrap()
            .retain(|row| row["name"] != name);
        assert!(decode_build_observation(
            &serde_json::to_vec(&invalid).unwrap(),
            Default::default()
        )
        .is_err());
    }
}

#[test]
fn standalone_capsules_require_their_own_source_bound_builder_approval() {
    let (signer, public, _) = signer(BUILDER);
    let value = standalone();
    let evidence = signed(&signer, &value);
    let mut policy = policy_value(&public);
    for old_type in [
        PROVENANCE_BUILD_TYPE,
        RUST_GUEST_BUILD_TYPE,
        C_GUEST_BUILD_TYPE,
    ] {
        policy["requirements"][0]["buildType"] = old_type.into();
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
    policy["requirements"][0]["buildType"] = RUST_CAPSULE_BUILD_TYPE.into();
    policy["requirements"][0]["sourceRevision"] = value.source.revision.clone().into();
    policy["requirements"][0]["sourceSnapshotDigest"] = value.source.snapshot_digest.clone().into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    policy["requirements"][0]["sourceSnapshotDigest"] = format!("sha256:{}", "0".repeat(64)).into();
    assert_eq!(
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::SourceDisallowed
    );
}

#[test]
fn standalone_recipes_cannot_lie_about_target_identity_or_observed_tools() {
    let original = serde_json::to_value(standalone()).unwrap();
    for (field, bad) in [
        ("cargoPackage", "../escape"),
        ("cargoPackage", "has--gap"),
        ("cargoPackage", "Uppercase"),
        ("manifestPath", "../Cargo.toml"),
        ("crateType", "bin"),
        ("target", "x86_64-unknown-linux-gnu"),
        ("profile", "debug"),
    ] {
        let mut value = original.clone();
        value["parameters"][field] = bad.into();
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
    for name in [
        "contracts-tool",
        "packager",
        "wit-bindgen",
        "dependency-lock",
    ] {
        let mut value = original.clone();
        value["materials"]
            .as_array_mut()
            .unwrap()
            .retain(|m| m["name"] != name);
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
    for field in ["locked", "incremental"] {
        let mut value = original.clone();
        value["parameters"][field] = (field != "locked").into();
        assert!(
            decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default())
                .is_err()
        );
    }
    let mut value = original.clone();
    value["parameters"]["cargoExample"] = "guest-http".into();
    assert!(
        decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default()).is_err()
    );
}
