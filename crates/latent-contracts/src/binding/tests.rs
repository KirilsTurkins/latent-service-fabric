use super::*;
use crate::{FunctionDescriptor, InterfaceDescriptor};
use latent_core::{ContractId, FunctionId, InterfaceId, Metadata};

fn contract() -> ContractDescriptor {
    ContractDescriptor {
        id: ContractId("example:test/api@1.0.0".into()),
        package_name: "example:test".into(),
        semantic_version: "1.0.0".into(),
        digest: "untrusted-label".into(),
        dependencies: Vec::new(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId("example:test/api@1.0.0".into()),
            digest: "label".into(),
            documentation: None,
            functions: vec![FunctionDescriptor {
                id: FunctionId("run".into()),
                name: "run".into(),
                asynchronous: false,
                documentation: None,
                attributes: Metadata::new(),
                parameters: vec![FieldDescriptor {
                    name: "input".into(),
                    value_type: ValueType::Bytes,
                    documentation: None,
                }],
                results: Vec::new(),
            }],
        }],
    }
}
#[test]
fn exact_descriptors_use_the_abi_instead_of_digest_labels_or_documentation() {
    let compiler = BoundedBindingCompiler::default();
    let a = contract();
    let mut b = a.clone();
    b.digest = "different".into();
    b.interfaces[0].documentation = Some("changed".into());
    b.interfaces[0].functions[0].parameters[0].value_type =
        ValueType::List(Box::new(ValueType::U8));
    let first = compiler.compile_exact(&a, &b).unwrap();
    assert!(first.required_adapters.is_empty());
    assert_eq!(
        first.plan_digest,
        compiler.compile_exact(&b, &a).unwrap().plan_digest
    );
    b.interfaces[0].functions[0].parameters[0].value_type = ValueType::U32;
    assert!(compiler.compile_exact(&a, &b).is_err());
    assert_ne!(
        first.plan_digest,
        compiler.compile_exact(&b, &b).unwrap().plan_digest
    );
}
#[test]
fn unresolved_types_versions_dependencies_duplicates_and_limits_deny() {
    let a = contract();
    let compiler = BoundedBindingCompiler::default();
    for variant in 0..7 {
        let mut b = a.clone();
        match variant {
            0 => b.semantic_version = "2.0.0".into(),
            1 => b
                .dependencies
                .push(ContractId("other:dep/api@1.0.0".into())),
            2 => {
                b.interfaces[0].functions[0].parameters[0].value_type =
                    ValueType::Record("undefined".into());
            }
            3 => {
                b.interfaces[0].functions[0].parameters[0].value_type =
                    ValueType::Resource("item".into());
            }
            4 => b.interfaces[0].functions[0].asynchronous = true,
            5 => b.interfaces.push(b.interfaces[0].clone()),
            _ => b.id = ContractId("other:contract/api@1.0.0".into()),
        }
        assert!(compiler.compile_exact(&a, &b).is_err(), "variant {variant}");
    }
    let limited = BoundedBindingCompiler {
        limits: ComparisonLimits {
            max_nodes: 1,
            ..Default::default()
        },
    };
    assert!(limited.compile_exact(&a, &a).is_err());
    for name in ["missing-version", "example:test/api@2.0.0"] {
        let mut b = a.clone();
        b.id.0 = name.into();
        assert!(compiler.compile_exact(&b, &b).is_err());
    }
}
