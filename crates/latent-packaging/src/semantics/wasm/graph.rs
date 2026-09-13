//! Limit transitive value graphs before the recursive WIT decoder sees them.
use super::{charge, exhausted, Budget, Result};
use wasmparser::component_types::{
    ComponentAnyTypeId as Any, ComponentDefinedType as Defined, ComponentEntityType as Entity,
    ComponentValType as Value,
};
use wasmparser::types::TypesRef;

pub(super) fn validate(types: TypesRef<'_>, budget: &mut Budget) -> Result<()> {
    for index in 0..types.component_type_count() {
        visit(types.component_any_type_at(index), types, budget, 1)?;
    }
    for index in 0..types.component_function_count() {
        visit(
            Any::Func(types.component_function_at(index)),
            types,
            budget,
            1,
        )?;
    }
    for index in 0..types.component_instance_count() {
        visit(
            Any::Instance(types.component_instance_at(index)),
            types,
            budget,
            1,
        )?;
    }
    for index in 0..types.component_count() {
        visit(Any::Component(types.component_at(index)), types, budget, 1)?;
    }
    for index in 0..types.value_count() {
        value(types.value_at(index), types, budget, 1)?;
    }
    Ok(())
}

fn take(budget: &mut Budget, depth: usize) -> Result<()> {
    if depth > budget.limits.max_type_depth {
        return Err(exhausted("component-value-graph-depth-limit"));
    }
    charge(&mut budget.types, 1, budget.limits.max_type_nodes)
}

fn visit(id: Any, types: TypesRef<'_>, budget: &mut Budget, depth: usize) -> Result<()> {
    take(budget, depth)?;
    match id {
        Any::Resource(_) => (),
        Any::Defined(id) => defined(&types[id], types, budget, depth)?,
        Any::Func(id) => {
            let function = &types[id];
            for (_, parameter) in &function.params {
                value(*parameter, types, budget, depth + 1)?;
            }
            if let Some(result) = function.result {
                value(result, types, budget, depth + 1)?;
            }
        }
        Any::Instance(id) => {
            for item in types[id].exports.values() {
                entity(item.ty, types, budget, depth + 1)?;
            }
        }
        Any::Component(id) => {
            for item in types[id].imports.values().chain(types[id].exports.values()) {
                entity(item.ty, types, budget, depth + 1)?;
            }
        }
    }
    Ok(())
}

fn entity(item: Entity, types: TypesRef<'_>, budget: &mut Budget, depth: usize) -> Result<()> {
    match item {
        Entity::Module(_) => take(budget, depth),
        Entity::Func(id) => visit(Any::Func(id), types, budget, depth),
        Entity::Instance(id) => visit(Any::Instance(id), types, budget, depth),
        Entity::Component(id) => visit(Any::Component(id), types, budget, depth),
        Entity::Type { referenced, .. } => visit(referenced, types, budget, depth),
        Entity::Value(ty) => value(ty, types, budget, depth),
    }
}

fn value(ty: Value, types: TypesRef<'_>, budget: &mut Budget, depth: usize) -> Result<()> {
    match ty {
        Value::Primitive(_) => take(budget, depth),
        Value::Type(id) => visit(Any::Defined(id), types, budget, depth),
    }
}

fn defined(
    definition: &Defined,
    types: TypesRef<'_>,
    budget: &mut Budget,
    depth: usize,
) -> Result<()> {
    match definition {
        Defined::Primitive(_)
        | Defined::Flags(_)
        | Defined::Enum(_)
        | Defined::Own(_)
        | Defined::Borrow(_) => (),
        Defined::List(ty) | Defined::Option(ty) | Defined::FixedLengthList(ty, _) => {
            value(*ty, types, budget, depth + 1)?;
        }
        Defined::Map(key, item) => {
            value(*key, types, budget, depth + 1)?;
            value(*item, types, budget, depth + 1)?;
        }
        Defined::Tuple(tuple) => {
            for ty in &tuple.types {
                value(*ty, types, budget, depth + 1)?;
            }
        }
        Defined::Record(record) => {
            for ty in record.fields.values() {
                value(*ty, types, budget, depth + 1)?;
            }
        }
        Defined::Variant(variant) => {
            for case in variant.cases.values() {
                if let Some(ty) = case.ty {
                    value(ty, types, budget, depth + 1)?;
                }
            }
        }
        Defined::Result { ok, err } => {
            for ty in ok.iter().chain(err) {
                value(*ty, types, budget, depth + 1)?;
            }
        }
        Defined::Future(ty) | Defined::Stream(ty) => {
            if let Some(ty) = ty {
                value(*ty, types, budget, depth + 1)?;
            }
        }
    }
    Ok(())
}
