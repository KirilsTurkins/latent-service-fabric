#[path = "depths.rs"]
mod depths;

use super::{
    exhausted,
    limits::{add, name},
    SemanticLimits,
};
use latent_core::PlatformError;
use wit_parser::{
    AstItem, Function, Interface, Resolve, TypeDef, TypeDefKind, UnresolvedPackage, World,
    WorldItem,
};

#[derive(Default)]
pub(super) struct Counts {
    pub(super) nodes: usize,
    pub(super) worlds: usize,
    functions: usize,
}

pub(super) fn unresolved(
    value: &UnresolvedPackage,
    counts: &mut Counts,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    scan(
        value.worlds.iter().map(|(id, item)| {
            // The parser creates an unnamed arena placeholder for a foreign
            // world include. Its declared dependency name is the input name;
            // the resolved arena is checked again with the actual world body.
            let declared = if item.name.is_empty() {
                value.foreign_deps.values().find_map(|items| {
                    items.iter().find_map(|(name, (dependency, _))| {
                        matches!(dependency, AstItem::World(world) if *world == id)
                            .then_some(name.as_str())
                    })
                })
            } else {
                None
            };
            (item, declared.unwrap_or(&item.name))
        }),
        value.interfaces.iter().map(|(_, item)| item),
        value.types.iter().map(|(_, item)| item),
        counts,
        limits,
    )?;
    depths::validate(value.types.iter(), limits)
}

pub(super) fn resolved(value: &Resolve, limits: SemanticLimits) -> Result<(), PlatformError> {
    if value.packages.len() > limits.max_wit_packages {
        return Err(exhausted("wit-package-count-limit"));
    }
    let mut counts = Counts::default();
    scan(
        value
            .worlds
            .iter()
            .map(|(_, item)| (item, item.name.as_str())),
        value.interfaces.iter().map(|(_, item)| item),
        value.types.iter().map(|(_, item)| item),
        &mut counts,
        limits,
    )?;
    depths::validate(value.types.iter(), limits)
}

fn scan<'a>(
    worlds: impl Iterator<Item = (&'a World, &'a str)>,
    interfaces: impl Iterator<Item = &'a Interface>,
    types: impl Iterator<Item = &'a TypeDef>,
    counts: &mut Counts,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    for (world, declared_name) in worlds {
        name(declared_name, limits)?;
        add(&mut counts.worlds, 1, limits.max_component_items)?;
        add(
            &mut counts.nodes,
            1 + world.imports.len() + world.exports.len() + world.includes.len(),
            limits.max_type_nodes,
        )?;
        if world.imports.len() > limits.max_imports || world.exports.len() > limits.max_exports {
            return Err(exhausted("wit-world-item-limit"));
        }
        for item in world.imports.values().chain(world.exports.values()) {
            if let WorldItem::Function(function) = item {
                function_shape(function, counts, limits)?;
            }
        }
    }
    for interface in interfaces {
        if let Some(value) = &interface.name {
            name(value, limits)?;
        }
        add(
            &mut counts.nodes,
            1 + interface.types.len(),
            limits.max_type_nodes,
        )?;
        for function in interface.functions.values() {
            function_shape(function, counts, limits)?;
        }
    }
    for ty in types {
        if let Some(value) = &ty.name {
            name(value, limits)?;
        }
        add(&mut counts.nodes, 1, limits.max_type_nodes)?;
        let members = match &ty.kind {
            TypeDefKind::Record(value) => {
                for field in &value.fields {
                    name(&field.name, limits)?;
                }
                value.fields.len()
            }
            TypeDefKind::Variant(value) => {
                for case in &value.cases {
                    name(&case.name, limits)?;
                }
                value.cases.len()
            }
            TypeDefKind::Enum(value) => {
                for case in &value.cases {
                    name(&case.name, limits)?;
                }
                value.cases.len()
            }
            TypeDefKind::Flags(value) => {
                for flag in &value.flags {
                    name(&flag.name, limits)?;
                }
                value.flags.len()
            }
            TypeDefKind::Tuple(value) => value.types.len(),
            _ => 1,
        };
        if members > limits.max_type_members {
            return Err(exhausted("wit-type-member-limit"));
        }
        add(&mut counts.nodes, members, limits.max_type_nodes)?;
    }
    Ok(())
}

fn function_shape(
    function: &Function,
    counts: &mut Counts,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    name(&function.name, limits)?;
    if function.params.len() > limits.max_parameters {
        return Err(exhausted("wit-parameter-limit"));
    }
    add(&mut counts.functions, 1, limits.max_functions)?;
    add(
        &mut counts.nodes,
        1 + function.params.len() + usize::from(function.result.is_some()),
        limits.max_type_nodes,
    )?;
    for parameter in &function.params {
        name(&parameter.name, limits)?;
    }
    Ok(())
}
