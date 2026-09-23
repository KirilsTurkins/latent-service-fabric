use super::*;
use latent_artifacts::{decode_contract_metadata, ContractMetadataLimits};
use latent_contracts::ValueType;
use latent_core::PlatformErrorCode;

const WIT: &str = "package example:author@1.2.3; interface api { run: func(value: u64) -> result<string, string>; } world service { export api; }";
const WORLD: &str = "example:author/service@1.2.3";

fn derive(source: &str) -> Result<CapsuleContractInputs, PlatformError> {
    derive_capsule_contracts(
        WORLD,
        &[("wit/app.wit".into(), source.as_bytes())].into(),
        SemanticLimits::default(),
    )
}

#[test]
fn complete_full_width_scalar_and_result_contract_is_derived_from_source() {
    let derived = derive(WIT).unwrap();
    assert_eq!(derived.exports(), &["example:author/api@1.2.3"]);
    assert!(derived.imports().is_empty());
    let metadata =
        decode_contract_metadata(derived.contracts(), ContractMetadataLimits::default()).unwrap();
    assert_eq!(metadata[0].package_name, "example:author");
    assert_eq!(metadata[0].semantic_version, "1.2.3");
    assert_eq!(
        metadata[0].interfaces[0].functions[0].parameters[0].value_type,
        ValueType::U64
    );
    assert_eq!(
        metadata[0].interfaces[0].functions[0].results[0].value_type,
        ValueType::Result {
            ok: Some(Box::new(ValueType::String)),
            error: Some(Box::new(ValueType::String))
        }
    );
    assert_eq!(
        derived.wit_lock().contracts_digest,
        artifact_blob_digest(derived.contracts())
    );
    assert_eq!(
        derived.wit_lock().packages[0].digest,
        artifact_blob_digest(WIT.as_bytes())
    );
}

#[test]
fn lists_records_variants_enums_aliases_tuples_and_async_kinds_are_retained() {
    let source = "package example:author@1.2.3; interface api { record row { id: u64, text: string } variant failure { denied, invalid(string) } enum mode { first, last } type identifier = s64; run: async func(id: identifier, rows: list<row>, setting: option<mode>, pair: tuple<u32, bool>) -> result<list<u8>, failure>; } world service { export api; }";
    let derived = derive(source).unwrap();
    let contracts =
        decode_contract_metadata(derived.contracts(), ContractMetadataLimits::default()).unwrap();
    let function = &contracts[0].interfaces[0].functions[0];
    assert!(function.asynchronous);
    assert_eq!(function.parameters[0].value_type, ValueType::S64);
    assert_eq!(
        function.parameters[1].value_type,
        ValueType::List(Box::new(ValueType::Record("row".into())))
    );
    assert_eq!(
        function.parameters[2].value_type,
        ValueType::Option(Box::new(ValueType::Variant("mode".into())))
    );
    assert_eq!(
        function.parameters[3].value_type,
        ValueType::Tuple(vec![ValueType::U32, ValueType::Bool])
    );
    // The legacy descriptor names a record; the lock retains its complete WIT
    // shape and changes when any record field changes.
    let modified = derive(&source.replace("id: u64", "id: u32")).unwrap();
    assert_ne!(
        derived.wit_lock().packages[0].digest,
        modified.wit_lock().packages[0].digest
    );
}

#[test]
fn exact_host_sources_and_direct_dependencies_are_required() {
    let clock = include_bytes!("../../../../../wit/platform/clock/package.wit");
    let source = WIT.replace(
        "world service {",
        "world service { import latent:clock/monotonic@0.1.0;",
    );
    let files: BTreeMap<_, _> = [
        ("wit/clock.wit".into(), clock.as_slice()),
        ("wit/app.wit".into(), source.as_bytes()),
    ]
    .into();
    let derived = derive_capsule_contracts(WORLD, &files, SemanticLimits::default()).unwrap();
    assert_eq!(derived.imports(), &["latent:clock/monotonic@0.1.0"]);
    assert_eq!(
        derived.wit_lock().packages[0].dependencies,
        vec!["latent:clock@0.1.0"]
    );
    assert!(derive(&source).is_err());
    let forged = std::str::from_utf8(clock)
        .unwrap()
        .replace("now-nanos: func() -> u64", "now-nanos: func() -> u32");
    let forged_files = [
        ("wit/clock.wit".into(), forged.as_bytes()),
        ("wit/app.wit".into(), source.as_bytes()),
    ]
    .into();
    assert!(derive_capsule_contracts(WORLD, &forged_files, SemanticLimits::default()).is_err());
}

#[test]
fn unsupported_nested_resource_async_value_flag_and_world_shapes_are_rejected() {
    for source in [
        WIT.replace("value: u64", "value: future<u64>"),
        WIT.replace("value: u64", "value: stream<u8>"),
        WIT.replace(
            "interface api {",
            "interface api { flags options { a, b } record row { o: options }",
        )
        .replace("value: u64", "value: row"),
        WIT.replace("interface api {", "interface api { resource handle;")
            .replace("value: u64", "value: borrow<handle>"),
        "package example:author@1.2.3; world service { export run: func(); }".into(),
        WIT.replace(
            "world service {",
            "world service { import unknown:host/api@1.0.0;",
        ),
    ] {
        assert!(derive(&source).is_err(), "must reject {source}");
    }
}

#[test]
fn malformed_versions_duplicate_packages_paths_and_foreign_sources_fail_closed() {
    assert!(derive(&WIT.replace("@1.2.3", "")).is_err());
    assert!(derive_capsule_contracts(
        "service",
        &[("wit/app.wit".into(), WIT.as_bytes())].into(),
        SemanticLimits::default()
    )
    .is_err());
    for path in ["../app.wit", "/app.wit", "wit/../app.wit"] {
        assert!(derive_capsule_contracts(
            WORLD,
            &[(path.into(), WIT.as_bytes())].into(),
            SemanticLimits::default()
        )
        .is_err());
    }
    assert!(derive_capsule_contracts(
        WORLD,
        &[
            ("wit/a.wit".into(), WIT.as_bytes()),
            ("wit/b.wit".into(), WIT.as_bytes())
        ]
        .into(),
        SemanticLimits::default()
    )
    .is_err());
    assert!(derive_capsule_contracts(
        WORLD,
        &[("wit/a.wit".into(), &[255][..])].into(),
        SemanticLimits::default()
    )
    .is_err());
}

#[test]
fn source_bytes_work_and_output_budgets_apply_before_returning_metadata() {
    for limits in [
        SemanticLimits {
            max_wit_source_bytes: 8,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_total_wit_bytes: 8,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_wit_tokens: 3,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_type_nodes: 3,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_summary_bytes: 8,
            ..SemanticLimits::default()
        },
    ] {
        let error = derive_capsule_contracts(
            WORLD,
            &[("wit/app.wit".into(), WIT.as_bytes())].into(),
            limits,
        )
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    }
}

#[test]
fn source_order_is_irrelevant_and_utf8_documentation_is_digest_bound() {
    let source = WIT.replace("run:", "/// Grüße, 世界.\nrun:");
    let a = derive(&source).unwrap();
    let b = derive(&source).unwrap();
    assert_eq!(a.contracts(), b.contracts());
    let plain = derive(WIT).unwrap();
    assert_ne!(a.contracts(), plain.contracts());
}
