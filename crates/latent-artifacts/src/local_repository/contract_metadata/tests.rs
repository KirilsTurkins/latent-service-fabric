use latent_contracts::{FieldDescriptor, ValueType};
use latent_core::PlatformErrorCode;
use latent_manifest::__serde_json::{self as serde_json, json};

use super::*;

fn fixture() -> ContractDescriptor {
    crate::local_repository::tests::contract_fixture()
}

#[test]
fn versioned_upload_preserves_every_typed_value_and_metadata_field() {
    let mut contract = fixture();
    let values = vec![
        ValueType::Bool,
        ValueType::U8,
        ValueType::U16,
        ValueType::U32,
        ValueType::U64,
        ValueType::S8,
        ValueType::S16,
        ValueType::S32,
        ValueType::S64,
        ValueType::F32,
        ValueType::F64,
        ValueType::Char,
        ValueType::String,
        ValueType::Bytes,
        ValueType::List(Box::new(ValueType::Bool)),
        ValueType::Option(Box::new(ValueType::String)),
        ValueType::Result {
            ok: None,
            error: Some(Box::new(ValueType::U64)),
        },
        ValueType::Tuple(vec![ValueType::U8, ValueType::String]),
        ValueType::Record("record".to_owned()),
        ValueType::Variant("variant".to_owned()),
        ValueType::Resource("resource".to_owned()),
        ValueType::Future(Box::new(ValueType::Bool)),
        ValueType::Stream(Box::new(ValueType::Bytes)),
    ];
    contract.interfaces[0].functions[0].parameters = values
        .into_iter()
        .enumerate()
        .map(|(n, value_type)| FieldDescriptor {
            name: format!("value-{n}"),
            value_type,
            documentation: Some("quoted \" documentation\nü".to_owned()),
        })
        .collect();
    let limits = ContractMetadataLimits::default();
    let bytes = encode_contract_metadata(&[contract.clone()], limits).expect("encode");
    let value: serde_json::Value = serde_json::from_slice(&bytes).expect("JSON");
    assert_eq!(value["format_version"], 1);
    assert_eq!(
        value["contracts"][0]["interfaces"][0]["functions"][0]["parameters"][22]["value_type"],
        json!({"Stream":"Bytes"})
    );
    assert_eq!(
        decode_contract_metadata(&bytes, limits).expect("decode"),
        vec![contract]
    );
    assert!(bytes.capacity() <= limits.max_document_bytes);
}

#[test]
fn unknown_versions_fields_and_duplicate_keys_are_rejected_without_raw_diagnostics() {
    let limits = ContractMetadataLimits::default();
    for raw in [
        br#"{"contracts":[]}"#.as_slice(),
        br#"{"format_version":2,"contracts":[]}"#,
        br#"{"format_version":1,"contracts":[],"secret":"private"}"#,
        br#"{"format_version":1,"contracts":[],"contracts":[]}"#,
        br#"{"format_version":1,"contracts":[]} trailing"#,
        br#"{"format_version":1,"contracts": ["#,
    ] {
        let failure = decode_contract_metadata(raw, limits).expect_err("invalid document");
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(failure.message, "invalid-contract-metadata");
        assert!(failure.details.is_empty());
    }
    let encoded = encode_contract_metadata(&[fixture()], limits).expect("fixture");
    let mut value: serde_json::Value = serde_json::from_slice(&encoded).expect("JSON");
    value["contracts"][0]["interfaces"][0]["functions"][0]["parameters"][0]["private-extension"] =
        json!(true);
    assert_eq!(
        decode_contract_metadata(&serde_json::to_vec(&value).expect("JSON"), limits)
            .expect_err("nested unknown field")
            .message,
        "invalid-contract-metadata"
    );
    let duplicate_attributes = String::from_utf8(encoded).expect("UTF8").replace(
        "\"latent.dev/test\":\"catalog\"",
        "\"key\":\"one\",\"key\":\"two\"",
    );
    assert_eq!(
        decode_contract_metadata(duplicate_attributes.as_bytes(), limits)
            .expect_err("duplicate metadata key")
            .message,
        "invalid-contract-metadata"
    );
}

#[test]
fn tiny_document_depth_node_string_and_retained_limits_fail_boundedly() {
    let default = ContractMetadataLimits::default();
    let bytes = encode_contract_metadata(&[fixture()], default).expect("fixture");
    let cases = [
        (
            ContractMetadataLimits {
                max_document_bytes: bytes.len() - 1,
                ..default
            },
            "contract-metadata-byte-limit",
        ),
        (
            ContractMetadataLimits {
                max_depth: 2,
                ..default
            },
            "contract-metadata-depth-limit",
        ),
        (
            ContractMetadataLimits {
                max_nodes: 5,
                ..default
            },
            "contract-metadata-node-limit",
        ),
        (
            ContractMetadataLimits {
                max_string_bytes: 16,
                ..default
            },
            "contract-metadata-string-limit",
        ),
        (
            ContractMetadataLimits {
                max_retained_bytes: 128,
                ..default
            },
            "contract-metadata-retained-limit",
        ),
    ];
    for (limits, reason) in cases {
        let failure = decode_contract_metadata(&bytes, limits).expect_err("configured bound");
        assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(failure.message, reason);
        assert!(encode_contract_metadata(&[fixture()], limits).is_err());
    }
    assert_eq!(
        decode_contract_metadata(
            b"{}",
            ContractMetadataLimits {
                max_depth: 113,
                ..default
            }
        )
        .expect_err("retain serde recursion protection")
        .message,
        "invalid-contract-metadata-limits"
    );
}

#[test]
fn empty_contract_containers_and_map_keys_count_toward_limits() {
    let mut contract = fixture();
    contract.interfaces.clear();
    contract.dependencies.clear();
    let bytes = encode_contract_metadata(
        &[contract.clone(), contract.clone()],
        ContractMetadataLimits::default(),
    )
    .expect("empty containers");
    let limits = ContractMetadataLimits {
        max_nodes: 20,
        ..ContractMetadataLimits::default()
    };
    assert_eq!(
        decode_contract_metadata(&bytes, limits)
            .expect_err("all nodes counted")
            .message,
        "contract-metadata-node-limit"
    );
    assert_eq!(
        encode_contract_metadata(&[contract.clone(), contract], limits)
            .expect_err("preflight empty containers")
            .message,
        "contract-metadata-node-limit"
    );
}

#[test]
fn default_json_depth_preserves_the_persisted_value_type_depth_boundary() {
    let mut contract = fixture();
    let mut value = ValueType::Bool;
    for _ in 1..super::super::metadata_codec::MAX_CONTRACT_TYPE_DEPTH {
        value = ValueType::Result {
            ok: Some(Box::new(value)),
            error: None,
        };
    }
    contract.interfaces[0].functions[0].parameters[0].value_type = value;
    let limits = ContractMetadataLimits::default();
    let bytes = encode_contract_metadata(&[contract.clone()], limits)
        .expect("current storage boundary accepted");
    assert_eq!(
        decode_contract_metadata(&bytes, limits).expect("decode boundary"),
        vec![contract]
    );
}

#[test]
fn bounded_writer_checks_capacity_before_copy_and_empty_documents_round_trip() {
    let limits = ContractMetadataLimits::default();
    let empty = encode_contract_metadata(&[], limits).expect("empty descriptor set");
    assert_eq!(empty, br#"{"format_version":1,"contracts":[]}"#);
    assert!(decode_contract_metadata(&empty, limits)
        .expect("decode empty")
        .is_empty());
    let exact = ContractMetadataLimits {
        max_document_bytes: empty.len(),
        ..limits
    };
    let exact_bytes = encode_contract_metadata(&[], exact).expect("exact boundary");
    assert!(exact_bytes.capacity() <= exact.max_document_bytes);
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum: 4,
    };
    writer.write_all(b"abc").expect("fits");
    assert!(writer.write_all(b"de").is_err());
    assert_eq!(writer.bytes, b"abc");
    assert!(writer.bytes.capacity() <= 4);
}
