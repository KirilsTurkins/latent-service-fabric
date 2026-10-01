use super::*;
use wasm_encoder::{
    Alias, ComponentAliasSection, ComponentExportKind as Kind, ComponentExportSection,
    ComponentImportSection, ComponentInstanceSection, ComponentOuterAliasKind,
    ComponentTypeRef as Ref, ComponentTypeSection, ComponentValType, InstanceType,
    NestedComponentSection, PrimitiveValType, TypeBounds,
};

#[test]
fn named_aliases_charge_the_selected_member_of_a_wide_instance() {
    let mut interface = InstanceType::new();
    let fields: Vec<_> = (0..32).map(|index| format!("field-{index}")).collect();
    interface.ty().defined_type().record(
        fields
            .iter()
            .map(|name| (name.as_str(), PrimitiveValType::U32)),
    );
    interface.export("payload", Ref::Type(TypeBounds::Eq(0)));
    interface
        .ty()
        .function()
        .params([("value", ComponentValType::Type(1))])
        .result(Some(ComponentValType::Type(1)));
    for index in 0..128 {
        interface.export(format!("operation-{index}"), Ref::Func(2));
    }
    let mut types = ComponentTypeSection::new();
    types.instance(&interface);
    let mut imports = ComponentImportSection::new();
    imports.import("wide-interface", Ref::Instance(0));
    let mut aliases = ComponentAliasSection::new();
    for _ in 0..400 {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: Kind::Func,
            name: "operation-0",
        });
    }
    let mut component = Component::new();
    component
        .section(&types)
        .section(&imports)
        .section(&aliases);
    let bytes = component.finish();
    // Whole-instance summaries multiplied by each alias exceed the ordinary
    // reference ceiling. Every selected function's actual graph fits it.
    validate(&bytes, SemanticLimits::default()).unwrap();
    let limits = SemanticLimits {
        max_reference_work: 16_384,
        ..SemanticLimits::default()
    };
    assert_eq!(
        heights::validate(&bytes, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

fn read_function(component: &mut Component) {
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    let mut imports = ComponentImportSection::new();
    imports.import("read", Ref::Func(0));
    component.section(&types).section(&imports);
}

fn linked_alias(via_outer: bool, name: &str, kind: Kind) -> Vec<u8> {
    let mut child = Component::new();
    read_function(&mut child);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("read", Kind::Func, 0)]);
    let mut exports = ComponentExportSection::new();
    exports.export("api", Kind::Instance, 0, None);
    child.section(&instances).section(&exports);
    let mut root = Component::new();
    read_function(&mut root);
    root.section(&NestedComponentSection(&child));
    if via_outer {
        let mut wrapper = Component::new();
        read_function(&mut wrapper);
        let mut aliases = ComponentAliasSection::new();
        aliases.alias(Alias::Outer {
            kind: ComponentOuterAliasKind::Component,
            count: 1,
            index: 0,
        });
        let mut instances = ComponentInstanceSection::new();
        instances.instantiate(0, [("read", Kind::Func, 0)]);
        let mut members = ComponentAliasSection::new();
        members.alias(Alias::InstanceExport {
            instance: 0,
            kind: Kind::Instance,
            name: "api",
        });
        let mut exports = ComponentExportSection::new();
        exports.export("api", Kind::Instance, 1, None);
        wrapper
            .section(&aliases)
            .section(&instances)
            .section(&members)
            .section(&exports);
        root.section(&NestedComponentSection(&wrapper));
    }
    let mut instances = ComponentInstanceSection::new();
    instances.instantiate(u32::from(via_outer), [("read", Kind::Func, 0)]);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: Kind::Instance,
        name: "api",
    });
    aliases.alias(Alias::InstanceExport {
        instance: 1,
        kind,
        name,
    });
    root.section(&instances).section(&aliases);
    root.finish()
}

#[test]
fn export_summaries_survive_instantiation_and_outer_component_aliases() {
    for wrapped in [false, true] {
        let bytes = linked_alias(wrapped, "read", Kind::Func);
        validate(&bytes, SemanticLimits::default()).unwrap();
        assert_eq!(
            heights::validate(
                &bytes,
                SemanticLimits {
                    max_type_nodes: 2,
                    ..SemanticLimits::default()
                }
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(
            validate(
                &bytes,
                SemanticLimits {
                    max_type_depth: 2,
                    ..SemanticLimits::default()
                }
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
    }
}

#[test]
fn named_aliases_reject_missing_members_and_changed_entity_kinds() {
    for wrapped in [false, true] {
        for (name, kind) in [("missing", Kind::Func), ("read", Kind::Type)] {
            let bytes = linked_alias(wrapped, name, kind);
            assert_eq!(
                heights::validate(&bytes, SemanticLimits::default())
                    .unwrap_err()
                    .code,
                PlatformErrorCode::InvalidArgument
            );
            assert!(validate(&bytes, SemanticLimits::default()).is_err());
        }
    }
}
