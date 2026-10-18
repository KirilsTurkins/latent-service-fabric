use super::{decode_build_observation, BuildRecipe, ProvenanceLimits};
use crate::SignatureFailure;
use serde_json::{json, Value};

const OBSERVED: &[u8] = include_bytes!("tests/fixtures/go-activation-v4-observation.json");

fn observed() -> Value {
    serde_json::from_slice(OBSERVED).unwrap()
}

fn decode(value: &Value) -> crate::SignatureResult<super::BuildObservation> {
    decode_build_observation(
        &serde_json::to_vec(value).unwrap(),
        ProvenanceLimits::default(),
    )
}

#[test]
fn observed_v4_recipe_decodes_without_relabelling_or_granting_authority() {
    let value = decode_build_observation(OBSERVED, ProvenanceLimits::default()).unwrap();
    assert_eq!(serde_json::to_value(&value).unwrap(), observed());
    let BuildRecipe::GoCapsule(recipe) = value.parameters else {
        panic!("the observed Go recipe must retain its type");
    };
    assert_eq!(recipe.runtime, "go-component-activation-v4");
    assert_eq!(recipe.compiler, "componentize-go");
    assert_eq!(recipe.target, "wasm32-wasip1");
    assert!(recipe.locked);
    assert!(!recipe.ambient_wasi);
}

#[test]
fn only_the_closed_installed_go_runtime_profiles_decode() {
    for runtime in [
        "go-component-async-v1",
        "go-component-activation-v1",
        "go-component-activation-v2",
        "go-component-activation-v3",
        "go-component-activation-v4",
    ] {
        let mut value = observed();
        value["parameters"]["runtime"] = json!(runtime);
        assert!(decode(&value).is_ok(), "{runtime}");
    }
    for runtime in [
        "go-component-async-v2",
        "go-component-activation-v0",
        "go-component-activation-v5",
        "go-component-activation-v4-extra",
        "native-go",
        "",
    ] {
        let mut value = observed();
        value["parameters"]["runtime"] = json!(runtime);
        assert_eq!(
            decode(&value).unwrap_err().reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
}

#[test]
fn activation_profiles_preserve_locked_target_compiler_package_and_shape_refusals() {
    for (field, replacement) in [
        ("compiler", json!("native-go")),
        ("target", json!("native")),
        ("locked", json!(false)),
        ("ambientWasi", json!(true)),
        ("goPackage", json!("")),
        ("goPackage", json!("Go-package")),
        ("goPackage", json!("outside/package")),
    ] {
        let mut value = observed();
        value["parameters"][field] = replacement;
        assert_eq!(
            decode(&value).unwrap_err().reason(),
            SignatureFailure::PredicateDisallowed
        );
    }
    for replacement in [Value::Null, json!(false), json!(4), json!([]), json!({})] {
        let mut value = observed();
        value["parameters"]["runtime"] = replacement;
        assert_eq!(
            decode(&value).unwrap_err().reason(),
            SignatureFailure::MalformedProvenance
        );
    }
    let mut value = observed();
    value["parameters"]["authority"] = json!("self-approved");
    assert_eq!(
        decode(&value).unwrap_err().reason(),
        SignatureFailure::MalformedProvenance
    );
    let mut value = observed();
    value["buildType"] = json!(super::JAVA_CAPSULE_BUILD_TYPE);
    assert_eq!(
        decode(&value).unwrap_err().reason(),
        SignatureFailure::PredicateDisallowed
    );
}
