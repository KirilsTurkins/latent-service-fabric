use super::{
    invalid, Analysis, ComparisonLimits, StructuralCompatibility as Level,
    StructuralIssueCode as Code, StructuralReport,
};
use crate::{ContractDescriptor, FieldDescriptor, FunctionDescriptor, ValueType};
use latent_core::{PlatformError, PlatformErrorCode};
use std::collections::BTreeSet;

/// Pure previous-to-candidate analysis. Legacy named types have no definitions:
/// matching their names or metadata digests therefore remains Unknown.
pub fn compare_descriptors(
    previous: &ContractDescriptor,
    candidate: &ContractDescriptor,
    limits: ComparisonLimits,
) -> Result<StructuralReport, PlatformError> {
    let mut analysis = Analysis::new(limits)?;
    let result = (|| {
        preflight(previous, &mut analysis)?;
        preflight(candidate, &mut analysis)?;
        compare(previous, candidate, &mut analysis)
    })();
    match result {
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted => analysis.exhausted(),
        Err(error) => return Err(error),
        Ok(()) => (),
    }
    Ok(analysis.finish())
}

fn owned(value: &String, analysis: &mut Analysis, name: bool) -> Result<(), PlatformError> {
    analysis.retained(value.capacity())?;
    if name {
        analysis.name(value)
    } else {
        analysis.text(value)
    }
}
fn optional(value: Option<&String>, analysis: &mut Analysis) -> Result<(), PlatformError> {
    if let Some(value) = value {
        owned(value, analysis, false)?;
    }
    Ok(())
}
fn slots<T>(value: &Vec<T>, analysis: &mut Analysis) -> Result<(), PlatformError> {
    let amount = value
        .capacity()
        .checked_mul(std::mem::size_of::<T>())
        .ok_or_else(invalid)?;
    analysis.retained(amount)?;
    analysis.edge(value.len())
}
fn unique<'a>(
    seen: &mut BTreeSet<&'a str>,
    name: &'a str,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    // Conservative bounded B-tree scratch allowance, with borrowed keys.
    a.retained(96)?;
    if !seen.insert(name) {
        return Err(invalid());
    }
    Ok(())
}
fn preflight(value: &ContractDescriptor, a: &mut Analysis) -> Result<(), PlatformError> {
    a.node(1)?;
    for name in [&value.id.0, &value.package_name, &value.semantic_version] {
        owned(name, a, true)?;
    }
    owned(&value.digest, a, false)?;
    slots(&value.dependencies, a)?;
    let mut dependencies = BTreeSet::new();
    for dependency in &value.dependencies {
        owned(&dependency.0, a, true)?;
        unique(&mut dependencies, &dependency.0, a)?;
    }
    slots(&value.interfaces, a)?;
    if value.interfaces.is_empty() {
        return Err(invalid());
    }
    let mut interfaces = BTreeSet::new();
    for interface in &value.interfaces {
        a.node(1)?;
        owned(&interface.id.0, a, true)?;
        unique(&mut interfaces, &interface.id.0, a)?;
        owned(&interface.digest, a, false)?;
        optional(interface.documentation.as_ref(), a)?;
        slots(&interface.functions, a)?;
        let mut names = BTreeSet::new();
        let mut ids = BTreeSet::new();
        for function in &interface.functions {
            a.node(1)?;
            owned(&function.id.0, a, true)?;
            owned(&function.name, a, true)?;
            unique(&mut names, &function.name, a)?;
            unique(&mut ids, &function.id.0, a)?;
            optional(function.documentation.as_ref(), a)?;
            for (key, value) in &function.attributes {
                a.edge(1)?;
                a.retained(96)?;
                owned(key, a, true)?;
                owned(value, a, false)?;
            }
            if function.asynchronous {
                a.issue(
                    Level::Unsupported,
                    Code::UnsupportedType,
                    &[&interface.id.0, &function.name],
                );
            }
            for fields in [&function.parameters, &function.results] {
                slots(fields, a)?;
                let mut names = BTreeSet::new();
                for field in fields {
                    owned(&field.name, a, true)?;
                    unique(&mut names, &field.name, a)?;
                    optional(field.documentation.as_ref(), a)?;
                    inspect_type(&field.value_type, a, 1)?;
                }
            }
        }
    }
    Ok(())
}
fn inspect_type(value: &ValueType, a: &mut Analysis, depth: usize) -> Result<(), PlatformError> {
    a.node(depth)?;
    match value {
        ValueType::Record(name) | ValueType::Variant(name) => {
            owned(name, a, true)?;
            a.issue(Level::Unknown, Code::MissingTypeDefinition, &[name]);
        }
        ValueType::Resource(name) => {
            owned(name, a, true)?;
            a.issue(Level::Unsupported, Code::UnsupportedType, &[name]);
        }
        ValueType::Future(inner) | ValueType::Stream(inner) => {
            a.issue(Level::Unsupported, Code::UnsupportedType, &[]);
            a.retained(std::mem::size_of::<ValueType>())?;
            a.edge(1)?;
            inspect_type(inner, a, depth + 1)?;
        }
        ValueType::List(inner) | ValueType::Option(inner) => {
            a.retained(std::mem::size_of::<ValueType>())?;
            a.edge(1)?;
            inspect_type(inner, a, depth + 1)?;
        }
        ValueType::Result { ok, error } => {
            for inner in [ok, error].into_iter().flatten() {
                a.retained(std::mem::size_of::<ValueType>())?;
                a.edge(1)?;
                inspect_type(inner, a, depth + 1)?;
            }
        }
        ValueType::Tuple(items) => {
            slots(items, a)?;
            for inner in items {
                inspect_type(inner, a, depth + 1)?;
            }
        }
        _ => (),
    }
    Ok(())
}

fn compare(
    old: &ContractDescriptor,
    new: &ContractDescriptor,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    if !equal(&old.id.0, &new.id.0, a)?
        || !equal(&old.package_name, &new.package_name, a)?
        || !equal(&old.semantic_version, &new.semantic_version, a)?
    {
        a.issue(Level::Breaking, Code::IdentityChanged, &[]);
    }
    a.retained((old.dependencies.len() + new.dependencies.len()).saturating_mul(96))?;
    a.edge(old.dependencies.len() + new.dependencies.len())?;
    let old_deps: BTreeSet<_> = old.dependencies.iter().map(|id| id.0.as_str()).collect();
    let new_deps: BTreeSet<_> = new.dependencies.iter().map(|id| id.0.as_str()).collect();
    if old_deps != new_deps {
        a.issue(Level::Breaking, Code::DependencyChanged, &[]);
    }
    for interface in &old.interfaces {
        let mut candidate = None;
        for item in &new.interfaces {
            a.edge(1)?;
            if equal(&interface.id.0, &item.id.0, a)? {
                candidate = Some(item);
                break;
            }
        }
        let Some(candidate) = candidate else {
            a.issue(Level::Breaking, Code::RemovedInterface, &[&interface.id.0]);
            continue;
        };
        for function in &interface.functions {
            let mut other = None;
            for item in &candidate.functions {
                a.edge(1)?;
                if equal(&function.name, &item.name, a)? {
                    other = Some(item);
                    break;
                }
            }
            let Some(other) = other else {
                a.issue(
                    Level::Breaking,
                    Code::RemovedFunction,
                    &[&interface.id.0, &function.name],
                );
                continue;
            };
            if !function_equal(function, other, a)? {
                a.issue(
                    Level::Breaking,
                    Code::FunctionChanged,
                    &[&interface.id.0, &function.name],
                );
            }
        }
        if candidate.functions.len() > interface.functions.len() {
            a.added();
        }
    }
    if new.interfaces.len() > old.interfaces.len() {
        a.added();
    }
    Ok(())
}
fn equal(left: &str, right: &str, a: &mut Analysis) -> Result<bool, PlatformError> {
    a.text(left)?;
    a.text(right)?;
    Ok(left == right)
}
fn function_equal(
    old: &FunctionDescriptor,
    new: &FunctionDescriptor,
    a: &mut Analysis,
) -> Result<bool, PlatformError> {
    a.node(1)?;
    Ok(equal(&old.id.0, &new.id.0, a)?
        && old.asynchronous == new.asynchronous
        && fields_equal(&old.parameters, &new.parameters, a)?
        && fields_equal(&old.results, &new.results, a)?)
}
fn fields_equal(
    old: &[FieldDescriptor],
    new: &[FieldDescriptor],
    a: &mut Analysis,
) -> Result<bool, PlatformError> {
    if old.len() != new.len() {
        return Ok(false);
    }
    for (old, new) in old.iter().zip(new) {
        a.edge(1)?;
        if !equal(&old.name, &new.name, a)? || !types_equal(&old.value_type, &new.value_type, a, 1)?
        {
            return Ok(false);
        }
    }
    Ok(true)
}
fn types_equal(
    old: &ValueType,
    new: &ValueType,
    a: &mut Analysis,
    depth: usize,
) -> Result<bool, PlatformError> {
    a.node(depth)?;
    a.edge(1)?;
    match (old, new) {
        (ValueType::Bytes, ValueType::List(inner)) | (ValueType::List(inner), ValueType::Bytes) => {
            Ok(matches!(inner.as_ref(), ValueType::U8))
        }
        (ValueType::List(old), ValueType::List(new))
        | (ValueType::Option(old), ValueType::Option(new))
        | (ValueType::Future(old), ValueType::Future(new))
        | (ValueType::Stream(old), ValueType::Stream(new)) => types_equal(old, new, a, depth + 1),
        (ValueType::Result { ok: ao, error: ae }, ValueType::Result { ok: bo, error: be }) => {
            for (old, new) in [(ao, bo), (ae, be)] {
                match (old, new) {
                    (None, None) => (),
                    (Some(old), Some(new)) => {
                        if !types_equal(old, new, a, depth + 1)? {
                            return Ok(false);
                        }
                    }
                    _ => return Ok(false),
                }
            }
            Ok(true)
        }
        (ValueType::Tuple(old), ValueType::Tuple(new)) => {
            if old.len() != new.len() {
                return Ok(false);
            }
            for (old, new) in old.iter().zip(new) {
                if !types_equal(old, new, a, depth + 1)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
        (ValueType::Record(old), ValueType::Record(new))
        | (ValueType::Variant(old), ValueType::Variant(new))
        | (ValueType::Resource(old), ValueType::Resource(new)) => equal(old, new, a),
        _ => Ok(std::mem::discriminant(old) == std::mem::discriminant(new)),
    }
}
