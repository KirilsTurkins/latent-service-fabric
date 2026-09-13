use super::*;
use crate::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, FunctionId, InterfaceId};

fn descriptor(ty: ValueType) -> ContractDescriptor {
    ContractDescriptor {
        id: ContractId("example:test/api@1.0.0".into()),
        package_name: "example:test".into(),
        semantic_version: "1.0.0".into(),
        dependencies: vec![],
        digest: "untrusted-display-digest".into(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId("example:test/api@1.0.0".into()),
            digest: "same".into(),
            documentation: None,
            functions: vec![FunctionDescriptor {
                id: FunctionId("run".into()),
                name: "run".into(),
                asynchronous: false,
                parameters: vec![FieldDescriptor {
                    name: "value".into(),
                    value_type: ty,
                    documentation: None,
                }],
                results: vec![],
                documentation: None,
                attributes: Default::default(),
            }],
        }],
    }
}
fn compare(old: &ContractDescriptor, new: &ContractDescriptor) -> StructuralReport {
    compare_descriptors(old, new, ComparisonLimits::default()).unwrap()
}
#[test]
fn scalar_and_complete_container_shapes_compare_without_trusting_digests() {
    let old = descriptor(ValueType::Tuple(vec![
        ValueType::Option(Box::new(ValueType::U32)),
        ValueType::Result {
            ok: Some(Box::new(ValueType::String)),
            error: None,
        },
    ]));
    let mut new = old.clone();
    new.digest = "different display".into();
    new.interfaces[0].documentation = Some("changed docs".into());
    assert_eq!(
        compare(&old, &new).level,
        StructuralCompatibility::Identical
    );
    new.interfaces[0].functions[0].parameters[0].value_type = ValueType::Bool;
    assert_eq!(compare(&old, &new).level, StructuralCompatibility::Breaking);
    assert_eq!(
        compare(
            &descriptor(ValueType::Bytes),
            &descriptor(ValueType::List(Box::new(ValueType::U8)))
        )
        .level,
        StructuralCompatibility::Identical
    );
}
#[test]
fn additions_removals_and_exact_versioned_identity_are_directional() {
    let old = descriptor(ValueType::U32);
    let mut new = old.clone();
    let mut added = new.interfaces[0].functions[0].clone();
    added.name = "extra".into();
    added.id = FunctionId("extra".into());
    new.interfaces[0].functions.push(added);
    assert_eq!(
        compare(&old, &new).level,
        StructuralCompatibility::BackwardCompatible
    );
    assert_eq!(compare(&new, &old).level, StructuralCompatibility::Breaking);
    new = old.clone();
    new.semantic_version = "2.0.0".into();
    assert_eq!(compare(&old, &new).level, StructuralCompatibility::Breaking);
    new = old.clone();
    new.dependencies
        .push(ContractId("other:types/api@1.0.0".into()));
    assert_eq!(compare(&old, &new).level, StructuralCompatibility::Breaking);
}
#[test]
fn named_definitions_are_unknown_and_resources_async_are_unsupported() {
    for ty in [
        ValueType::Record("item".into()),
        ValueType::Variant("choice".into()),
    ] {
        let descriptor = descriptor(ty);
        let result = compare(&descriptor, &descriptor);
        assert_eq!(result.level, StructuralCompatibility::Unknown);
        assert!(!result.analysis_complete);
    }
    for ty in [
        ValueType::Resource("resource".into()),
        ValueType::Future(Box::new(ValueType::U32)),
        ValueType::Stream(Box::new(ValueType::U32)),
    ] {
        let descriptor = descriptor(ty);
        assert_eq!(
            compare(&descriptor, &descriptor).level,
            StructuralCompatibility::Unsupported
        );
    }
    let mut value = descriptor(ValueType::U32);
    value.interfaces[0].functions[0].asynchronous = true;
    assert_eq!(
        compare(&value, &value).level,
        StructuralCompatibility::Unsupported
    );
}
#[test]
fn duplicate_ids_and_names_fail_before_comparison() {
    let mut value = descriptor(ValueType::U32);
    let duplicate = value.interfaces[0].functions[0].clone();
    value.interfaces[0].functions.push(duplicate);
    assert!(compare_descriptors(&value, &value, ComparisonLimits::default()).is_err());
}
#[test]
fn lowered_depth_work_capacity_and_report_limits_are_non_authorizing() {
    let value = descriptor(ValueType::Option(Box::new(ValueType::Option(Box::new(
        ValueType::U32,
    )))));
    for limits in [
        ComparisonLimits {
            max_depth: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_nodes: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_edges: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_string_bytes: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_name_bytes: 1,
            ..Default::default()
        },
        ComparisonLimits {
            max_retained_bytes: 1,
            ..Default::default()
        },
    ] {
        let report = compare_descriptors(&value, &value, limits).unwrap();
        assert_eq!(report.level, StructuralCompatibility::Unknown);
        assert!(!report.analysis_complete);
    }
    let mut retained = descriptor(ValueType::U32);
    retained.digest.reserve(2048);
    let report = compare_descriptors(
        &retained,
        &retained,
        ComparisonLimits {
            max_retained_bytes: 1024,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(report.level, StructuralCompatibility::Unknown);
    let named = descriptor(ValueType::Record("long-name".into()));
    let report = compare_descriptors(
        &named,
        &named,
        ComparisonLimits {
            max_issues: 1,
            max_path_bytes: 1,
            max_report_bytes: 64,
            ..Default::default()
        },
    )
    .unwrap();
    assert!(report.issues.len() <= 1);
    assert!(report.issues.iter().all(|issue| issue.path.len() <= 1));
    assert!(report.diagnostics_truncated);
    assert_eq!(report.level, StructuralCompatibility::Unknown);
}
