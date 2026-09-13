use latent_artifacts::{
    decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use latent_contracts::{ContractDescriptor, ValueType};
use latent_core::{ContractId, PlatformErrorCode};
use serde_json::Value;
use wit_parser::{FunctionKind, Resolve, WorldId, WorldItem};

use super::{digest, validate, SemanticLimits};

const ECHO_METADATA: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../examples/echo-contract/contracts.json"
));
const ECHO_WIT: &str = r"
package examples:echo@0.1.0;
interface api {
    variant echo-error { empty-message, message-too-large }
    echo: func(message: string) -> result<string, echo-error>;
}
world service { export api; }
";

fn resolve(source: &str) -> (Resolve, WorldId) {
    let mut resolve = Resolve::default();
    let package = resolve.push_str("fixture.wit", source).unwrap();
    let world = resolve.select_world(&[package], Some("service")).unwrap();
    (resolve, world)
}

fn echo() -> Vec<ContractDescriptor> {
    decode_contract_metadata(ECHO_METADATA.as_bytes(), ContractMetadataLimits::default()).unwrap()
}

// Mutation tests recalculate digests so semantic failures cannot be hidden by an
// earlier stale-digest rejection. Independent builder known answers below test
// the digest implementation itself.
fn resign(contracts: &mut Vec<ContractDescriptor>) {
    let encoded = encode_contract_metadata(contracts, ContractMetadataLimits::default()).unwrap();
    let mut value: Value = serde_json::from_slice(&encoded).unwrap();
    for contract in value["contracts"].as_array_mut().unwrap() {
        for interface in contract["interfaces"].as_array_mut().unwrap() {
            interface["digest"] = digest::calculate(interface, 1024 * 1024).unwrap().into();
        }
        contract["digest"] = digest::calculate(contract, 1024 * 1024).unwrap().into();
    }
    *contracts = decode_contract_metadata(
        &serde_json::to_vec(&value).unwrap(),
        ContractMetadataLimits::default(),
    )
    .unwrap();
}

fn parameter_fixture(
    declarations: &str,
    ty: &str,
    described: ValueType,
) -> (Resolve, WorldId, Vec<ContractDescriptor>) {
    let source = format!("package examples:echo@0.1.0; interface api {{ {declarations} echo: func(value: {ty}); }} world service {{ export api; }}");
    let (resolve, world) = resolve(&source);
    let mut contracts = echo();
    let function = &mut contracts[0].interfaces[0].functions[0];
    function.parameters[0].name = "value".to_owned();
    function.parameters[0].value_type = described;
    function.results.clear();
    resign(&mut contracts);
    (resolve, world, contracts)
}

#[test]
fn maintained_echo_metadata_has_identical_digests_and_projection() {
    let original: Value = serde_json::from_str(ECHO_METADATA).unwrap();
    let contract = &original["contracts"][0];
    assert_eq!(
        digest::calculate(&contract["interfaces"][0], ECHO_METADATA.len()).unwrap(),
        "sha256:a61ba62d4631002e5e41d7edde86f2983613670c787d474cd9c2e95164deeeaa"
    );
    assert_eq!(
        digest::calculate(contract, ECHO_METADATA.len()).unwrap(),
        "sha256:fe6102311b0d42fc70186988480308210d93cc02b457775ad0223c4854bda8a5"
    );
    let (resolve, world) = resolve(ECHO_WIT);
    validate(&resolve, world, &echo(), SemanticLimits::default()).unwrap();
}

#[test]
fn recursive_sorting_utf8_and_child_digest_match_python_known_answer() {
    // Independently calculated with the exact tools/build_echo_capsule.py
    // metadata_digest algorithm, including a newline, quote and UTF-8 text.
    let value = serde_json::json!({"z":"café\n\"", "digest":"ignored",
        "a":{"z":1,"digest":"child","a":[true,null]}});
    assert_eq!(
        digest::calculate(&value, 1024).unwrap(),
        "sha256:fe19c162de98f99b6037714fc49f1b772a5c86a22f3e8e1721ba7056429dacd7"
    );
    let mut changed = value.clone();
    changed["digest"] = "another ignored root digest".into();
    assert_eq!(
        digest::calculate(&value, 1024).unwrap(),
        digest::calculate(&changed, 1024).unwrap()
    );
    changed["a"]["digest"] = "changed child".into();
    assert_ne!(
        digest::calculate(&value, 1024).unwrap(),
        digest::calculate(&changed, 1024).unwrap()
    );
    assert_eq!(
        digest::calculate(&value, 1).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn stale_digest_is_rejected_without_metadata_repair() {
    let (resolve, world) = resolve(ECHO_WIT);
    for changed_field in 0..3 {
        let mut contracts = echo();
        match changed_field {
            0 => contracts[0].interfaces[0].documentation = Some("new documentation".to_owned()),
            1 => contracts[0].digest.make_ascii_uppercase(),
            _ => contracts[0].interfaces[0].digest.make_ascii_uppercase(),
        }
        let before = contracts.clone();
        assert_eq!(
            validate(&resolve, world, &contracts, SemanticLimits::default())
                .unwrap_err()
                .message,
            "contract-metadata-digest-mismatch"
        );
        assert_eq!(contracts, before);
    }
}

#[test]
fn exact_contract_interface_and_function_sets_are_required() {
    let (resolve, world) = resolve(ECHO_WIT);
    for mutation in 0..11 {
        let mut contracts = echo();
        match mutation {
            0 => contracts.clear(),
            1 => contracts.push(contracts[0].clone()),
            2 => contracts[0].id.0 = "examples:echo/other@0.1.0".to_owned(),
            3 => contracts[0].package_name = "different:package".to_owned(),
            4 => contracts[0].semantic_version = "0.2.0".to_owned(),
            5 => contracts[0].interfaces.clear(),
            6 => {
                let duplicate = contracts[0].interfaces[0].clone();
                contracts[0].interfaces.push(duplicate);
            }
            7 => contracts[0].interfaces[0].id.0 = "other".to_owned(),
            8 => contracts[0].interfaces[0].functions.clear(),
            9 => {
                let duplicate = contracts[0].interfaces[0].functions[0].clone();
                contracts[0].interfaces[0].functions.push(duplicate);
            }
            _ => contracts[0].interfaces[0].functions[0].id.0 = "unrelated".to_owned(),
        }
        resign(&mut contracts);
        assert!(
            validate(&resolve, world, &contracts, SemanticLimits::default()).is_err(),
            "mutation {mutation}"
        );
    }
}

#[test]
fn parameter_result_and_async_metadata_cannot_lie_after_rehashing() {
    let (resolve, world) = resolve(ECHO_WIT);
    for mutation in 0..8 {
        let mut contracts = echo();
        let function = &mut contracts[0].interfaces[0].functions[0];
        match mutation {
            0 => function.parameters[0].name = "different".to_owned(),
            1 => function.parameters[0].value_type = ValueType::U32,
            2 => function.parameters.push(function.parameters[0].clone()),
            3 => function.results.clear(),
            4 => function.results[0].name = "not-result".to_owned(),
            5 => function.results[0].value_type = ValueType::String,
            6 => function.asynchronous = true,
            _ => {
                function.name = "unknown".to_owned();
                function.id.0 = "unknown".to_owned();
            }
        }
        resign(&mut contracts);
        assert!(
            validate(&resolve, world, &contracts, SemanticLimits::default()).is_err(),
            "mutation {mutation}"
        );
    }
    let (mut resolve, world) = self::resolve(ECHO_WIT);
    let WorldItem::Interface { id, .. } = resolve.worlds[world].exports.values().next().unwrap()
    else {
        panic!("interface");
    };
    let id = *id;
    resolve.interfaces[id]
        .functions
        .get_mut("echo")
        .unwrap()
        .kind = FunctionKind::AsyncFreestanding;
    assert_eq!(
        validate(&resolve, world, &echo(), SemanticLimits::default())
            .unwrap_err()
            .message,
        "unsupported-contract-function-kind"
    );
}

#[test]
fn aliases_named_records_variants_enums_and_byte_lists_preserve_legacy_forms() {
    let cases = [
        (
            "record data { value: u32 } type alias = data;",
            "alias",
            ValueType::Record("data".to_owned()),
        ),
        (
            "variant choice { yes(u32), no }",
            "choice",
            ValueType::Variant("choice".to_owned()),
        ),
        (
            "enum mode { fast, slow }",
            "mode",
            ValueType::Variant("mode".to_owned()),
        ),
        ("", "list<u8>", ValueType::Bytes),
        ("", "list<u8>", ValueType::List(Box::new(ValueType::U8))),
        ("type octet = u8;", "list<octet>", ValueType::Bytes),
        (
            "",
            "option<tuple<u32, string>>",
            ValueType::Option(Box::new(ValueType::Tuple(vec![
                ValueType::U32,
                ValueType::String,
            ]))),
        ),
        (
            "",
            "result<_, string>",
            ValueType::Result {
                ok: None,
                error: Some(Box::new(ValueType::String)),
            },
        ),
    ];
    for (declarations, ty, described) in cases {
        let (resolve, world, contracts) = parameter_fixture(declarations, ty, described);
        validate(&resolve, world, &contracts, SemanticLimits::default()).unwrap();
    }
}

#[test]
fn named_projection_mismatches_and_unsupported_flags_are_rejected() {
    let cases = [
        (
            "record data { value: u32 }",
            "data",
            ValueType::Record("other".to_owned()),
        ),
        (
            "variant choice { yes(u32), no }",
            "choice",
            ValueType::Variant("other".to_owned()),
        ),
        (
            "enum mode { fast, slow }",
            "mode",
            ValueType::Variant("other".to_owned()),
        ),
        (
            "flags options { one, two }",
            "options",
            ValueType::Variant("options".to_owned()),
        ),
        ("", "list<u16>", ValueType::Bytes),
        (
            "",
            "tuple<u32, string>",
            ValueType::Tuple(vec![ValueType::U32]),
        ),
        (
            "",
            "result<_, string>",
            ValueType::Result {
                ok: Some(Box::new(ValueType::U32)),
                error: Some(Box::new(ValueType::String)),
            },
        ),
    ];
    for (declarations, ty, described) in cases {
        let (resolve, world, contracts) = parameter_fixture(declarations, ty, described);
        assert!(
            validate(&resolve, world, &contracts, SemanticLimits::default()).is_err(),
            "{ty}"
        );
    }
}

#[test]
fn dependencies_are_exact_direct_interface_ids_not_world_imports() {
    let source = r"package examples:echo@0.1.0;
        interface types { record data { value: u32 } }
        interface api { use types.{data}; echo: func(value: data); }
        world service { export api; }";
    let (resolve, world) = resolve(source);
    let (_, _, mut contracts) = parameter_fixture(
        "record data { value: u32 }",
        "data",
        ValueType::Record("data".to_owned()),
    );
    assert_eq!(
        validate(&resolve, world, &contracts, SemanticLimits::default())
            .unwrap_err()
            .message,
        "contract-dependency-mismatch"
    );
    contracts[0].dependencies = vec![ContractId("examples:echo/types@0.1.0".to_owned())];
    resign(&mut contracts);
    validate(&resolve, world, &contracts, SemanticLimits::default()).unwrap();
    let duplicate = contracts[0].dependencies[0].clone();
    contracts[0].dependencies.push(duplicate);
    resign(&mut contracts);
    assert_eq!(
        validate(&resolve, world, &contracts, SemanticLimits::default())
            .unwrap_err()
            .message,
        "contract-dependency-mismatch"
    );
}

#[test]
fn bounded_metadata_and_projection_depth_fail_before_unbounded_work() {
    let (resolve, world) = resolve(ECHO_WIT);
    let tiny = SemanticLimits {
        max_summary_bytes: 8,
        ..SemanticLimits::default()
    };
    assert_eq!(
        validate(&resolve, world, &echo(), tiny).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let (resolve, world, contracts) = parameter_fixture(
        "type first = u32; type second = first;",
        "second",
        ValueType::U32,
    );
    let shallow = SemanticLimits {
        max_type_depth: 1,
        ..SemanticLimits::default()
    };
    assert_eq!(
        validate(&resolve, world, &contracts, shallow)
            .unwrap_err()
            .message,
        "contract-type-depth-limit"
    );
    let zero = SemanticLimits {
        max_functions: 0,
        ..SemanticLimits::default()
    };
    assert_eq!(
        validate(&resolve, world, &contracts, zero)
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
}

#[test]
fn unsupported_world_function_has_no_fabricated_contract_projection() {
    let (resolve, world) =
        resolve("package examples:echo@0.1.0; world service { export direct: func(); }");
    assert_eq!(
        validate(&resolve, world, &[], SemanticLimits::default())
            .unwrap_err()
            .message,
        "unsupported-contract-world-export"
    );
}
