//! Borrowed binary preflight followed by full validation, without compilation.

mod code;
mod graph;
mod heights;
#[cfg(test)]
mod tests;
mod types;

use super::{exhausted, invalid, SemanticLimits};
use latent_core::PlatformError;
use wasmparser::{BinaryReader, FuncValidatorAllocations, Parser, ValidPayload, Validator};

type Result<T> = std::result::Result<T, PlatformError>;

pub(super) fn validate(component: &[u8], limits: SemanticLimits) -> Result<()> {
    limits.validate()?;
    if component.len() > limits.max_component_bytes {
        return Err(exhausted("component-byte-limit"));
    }
    let mut budget = Budget::new(limits);
    envelope(component, true, 1, &mut budget)?;
    heights::validate(component, limits)?;
    // No Validator/type arena exists until every borrowed section and body has
    // passed the input budgets, including unused nested core modules.
    code::preflight(component, &mut budget)?;
    let mut validator = Validator::new();
    let mut allocations = FuncValidatorAllocations::default();
    for payload in Parser::new(0).parse_all(component) {
        match read(validator.payload(&read(payload)?))? {
            ValidPayload::Func(function, body) => {
                let mut function = function.into_validator(allocations);
                read(function.validate(&body))?;
                allocations = function.into_allocations();
            }
            ValidPayload::End(types) => graph::validate(types.as_ref(), &mut budget)?,
            _ => (),
        }
    }
    Ok(())
}

struct Budget {
    limits: SemanticLimits,
    sections: usize,
    items: usize,
    types: usize,
    functions: usize,
    locals: usize,
    operators: usize,
    package_docs_bytes: usize,
}

impl Budget {
    fn new(limits: SemanticLimits) -> Self {
        Self {
            limits,
            sections: 0,
            items: 0,
            types: 0,
            functions: 0,
            locals: 0,
            operators: 0,
            package_docs_bytes: 0,
        }
    }

    fn count(reader: &mut BinaryReader<'_>, maximum: usize) -> Result<usize> {
        let count = read(reader.read_var_u32())? as usize;
        if count > maximum {
            return Err(exhausted("component-vector-limit"));
        }
        Ok(count)
    }

    fn members(&mut self, reader: &mut BinaryReader<'_>) -> Result<usize> {
        let count = Self::count(reader, self.limits.max_type_members)?;
        charge(&mut self.types, count, self.limits.max_type_nodes)?;
        Ok(count)
    }

    fn name(&self, reader: &mut BinaryReader<'_>) -> Result<()> {
        let value = read(reader.read_string())?;
        if value.len() > self.limits.max_name_bytes {
            return Err(exhausted("component-name-limit"));
        }
        Ok(())
    }
}

fn envelope(bytes: &[u8], component: bool, depth: usize, budget: &mut Budget) -> Result<()> {
    if depth > budget.limits.max_component_depth {
        return Err(exhausted("component-nesting-limit"));
    }
    let header = if component {
        b"\0asm\x0d\0\x01\0"
    } else {
        b"\0asm\x01\0\0\0"
    };
    if bytes.get(..8) != Some(header) {
        return Err(invalid("invalid-component-header"));
    }
    let mut reader = BinaryReader::new(&bytes[8..], 8);
    while !reader.eof() {
        charge(&mut budget.sections, 1, budget.limits.max_sections)?;
        let id = read(reader.read_u8())?;
        let mut section = read(reader.read_reader())?;
        if id == 0 {
            let name = read(section.read_string())?;
            bounded_name(name, budget)?;
            if name == "package-docs" {
                let size = section.bytes_remaining();
                if size > budget.limits.max_wit_source_bytes {
                    return Err(exhausted("package-docs-byte-limit"));
                }
                charge(
                    &mut budget.package_docs_bytes,
                    size,
                    budget.limits.max_total_wit_bytes,
                )?;
                let bytes = read(section.read_bytes(size))?;
                super::metadata::validate_package_docs(bytes, budget.limits)?;
            }
            continue;
        }
        if component && matches!(id, 1 | 4) {
            let nested = bytes
                .get(section.range())
                .ok_or_else(|| invalid("invalid-component-extent"))?;
            envelope(nested, id == 4, depth + 1, budget)?;
        } else if component {
            component_section(id, &mut section, budget)?;
        } else {
            core_section(id, &mut section, budget)?;
        }
    }
    Ok(())
}

fn component_section(id: u8, reader: &mut BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    if id == 9 {
        read(reader.read_var_u32())?;
        let count = budget.members(reader)?;
        for _ in 0..count {
            read(reader.read_var_u32())?;
        }
        Budget::count(reader, budget.limits.max_type_members)?;
        return end(reader);
    }
    let count = Budget::count(reader, budget.limits.max_component_items)?;
    charge(&mut budget.items, count, budget.limits.max_component_items)?;
    for _ in 0..count {
        match id {
            2 | 5 => instance(reader, id == 5, budget)?,
            3 => types::core(reader, budget)?,
            6 => {
                alias(reader, budget)?;
            }
            7 => types::component(reader, budget, 1)?,
            // The pinned reader hard-caps canonical options at ten. These small
            // temporary values are discarded before constructing Validator.
            8 => {
                read(reader.read::<wasmparser::CanonicalFunction>())?;
            }
            10 => {
                let item = read(reader.read::<wasmparser::ComponentImport<'_>>())?;
                external_name(item.name, budget)?;
            }
            11 => {
                let item = read(reader.read::<wasmparser::ComponentExport<'_>>())?;
                external_name(item.name, budget)?;
            }
            _ => return Err(invalid("unknown-component-section")),
        }
    }
    end(reader)
}

fn instance(reader: &mut BinaryReader<'_>, component: bool, budget: &mut Budget) -> Result<()> {
    let kind = read(reader.read_u8())?;
    if kind == 0 {
        read(reader.read_var_u32())?;
    }
    if kind > 1 {
        return Err(invalid("invalid-component-instance"));
    }
    let count = Budget::count(reader, budget.limits.max_component_items)?;
    charge(&mut budget.items, count, budget.limits.max_component_items)?;
    for _ in 0..count {
        if component && kind == 1 {
            let name = read(reader.read::<wasmparser::ComponentExternName<'_>>())?;
            external_name(name, budget)?;
        } else {
            budget.name(reader)?;
        }
        if component {
            read(reader.read::<wasmparser::ComponentExternalKind>())?;
        } else {
            read(reader.read_u8())?;
        }
        read(reader.read_var_u32())?;
    }
    Ok(())
}

fn core_section(id: u8, reader: &mut BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    if id == 8 {
        read(reader.read_var_u32())?;
        return end(reader);
    }
    let count = Budget::count(reader, budget.limits.max_core_functions)?;
    if id == 12 {
        return end(reader);
    }
    if id == 3 {
        charge(
            &mut budget.functions,
            count,
            budget.limits.max_core_functions,
        )?;
    }
    if id == 1 {
        for _ in 0..count {
            types::group(reader, budget)?;
        }
        end(reader)?;
    }
    // Core vectors cannot allocate above this aggregate cap, even when a
    // malformed section declares many entries but contains no corresponding data.
    charge(&mut budget.types, count, budget.limits.max_type_nodes)?;
    Ok(())
}

fn bounded_name(value: &str, budget: &Budget) -> Result<()> {
    if value.len() > budget.limits.max_name_bytes {
        Err(exhausted("component-name-limit"))
    } else {
        Ok(())
    }
}

fn external_name(name: wasmparser::ComponentExternName<'_>, budget: &Budget) -> Result<()> {
    bounded_name(name.name, budget)?;
    if let Some(implements) = name.implements {
        bounded_name(implements, budget)?;
    }
    Ok(())
}

fn alias(reader: &mut BinaryReader<'_>, budget: &Budget) -> Result<()> {
    match read(reader.read::<wasmparser::ComponentAlias<'_>>())? {
        wasmparser::ComponentAlias::InstanceExport { name, .. }
        | wasmparser::ComponentAlias::CoreInstanceExport { name, .. } => bounded_name(name, budget),
        wasmparser::ComponentAlias::Outer { .. } => Ok(()),
    }
}

fn charge(total: &mut usize, count: usize, maximum: usize) -> Result<()> {
    *total = total
        .checked_add(count)
        .filter(|value| *value <= maximum)
        .ok_or_else(|| exhausted("component-work-limit"))?;
    Ok(())
}

fn read<T>(value: wasmparser::Result<T>) -> Result<T> {
    value.map_err(|_| invalid("invalid-component-binary"))
}

fn end(reader: &BinaryReader<'_>) -> Result<()> {
    if reader.eof() {
        Ok(())
    } else {
        Err(invalid("trailing-component-section-bytes"))
    }
}
