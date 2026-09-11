//! Allocation-free scans of nested vector lengths before the upstream type reader.
use super::{alias, charge, exhausted, external_name, invalid, read, BinaryReader, Budget, Result};

pub(super) fn component(
    reader: &mut BinaryReader<'_>,
    budget: &mut Budget,
    depth: usize,
) -> Result<()> {
    if depth > budget.limits.max_type_depth {
        return Err(exhausted("component-type-depth-limit"));
    }
    charge(&mut budget.types, 1, budget.limits.max_type_nodes)?;
    match read(reader.read_u8())? {
        0x3f => {
            read(reader.read::<wasmparser::ValType>())?;
            optional_index(reader)?;
        }
        0x40 | 0x43 => {
            let count = Budget::count(reader, budget.limits.max_parameters)?;
            charge(&mut budget.types, count, budget.limits.max_type_nodes)?;
            for _ in 0..count {
                budget.name(reader)?;
                value(reader)?;
            }
            match read(reader.read_u8())? {
                0 => value(reader)?,
                1 if read(reader.read_u8())? == 0 => (),
                _ => return Err(invalid("invalid-component-result")),
            }
        }
        kind @ (0x41 | 0x42) => {
            let count = budget.members(reader)?;
            for _ in 0..count {
                match read(reader.read_u8())? {
                    0 => core(reader, budget)?,
                    1 => component(reader, budget, depth + 1)?,
                    2 => {
                        alias(reader, budget)?;
                    }
                    3 if kind == 0x41 => {
                        let import = read(reader.read::<wasmparser::ComponentImport<'_>>())?;
                        external_name(import.name, budget)?;
                    }
                    4 => {
                        let name = read(reader.read::<wasmparser::ComponentExternName<'_>>())?;
                        external_name(name, budget)?;
                        read(reader.read::<wasmparser::ComponentTypeRef>())?;
                    }
                    _ => return Err(invalid("invalid-component-type-declaration")),
                }
            }
        }
        0x72 => {
            for _ in 0..budget.members(reader)? {
                budget.name(reader)?;
                value(reader)?;
            }
        }
        0x71 => {
            for _ in 0..budget.members(reader)? {
                budget.name(reader)?;
                optional_value(reader)?;
                if read(reader.read_u8())? != 0 {
                    return Err(invalid("invalid-component-variant"));
                }
            }
        }
        0x70 | 0x6b => value(reader)?,
        0x63 => {
            value(reader)?;
            value(reader)?;
        }
        0x6f => {
            for _ in 0..budget.members(reader)? {
                value(reader)?;
            }
        }
        0x6e | 0x6d => {
            for _ in 0..budget.members(reader)? {
                budget.name(reader)?;
            }
        }
        0x6a => {
            optional_value(reader)?;
            optional_value(reader)?;
        }
        0x69 | 0x68 => {
            read(reader.read_var_u32())?;
        }
        0x67 => {
            value(reader)?;
            Budget::count(reader, budget.limits.max_type_members)?;
        }
        0x66 | 0x65 => optional_value(reader)?,
        0x73..=0x7f | 0x64 => (),
        _ => return Err(invalid("invalid-component-type")),
    }
    Ok(())
}

pub(super) fn core(reader: &mut BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    let mut probe = reader.clone();
    match read(probe.read_u8())? {
        0x50 => {
            read(reader.read_u8())?;
            for _ in 0..budget.members(reader)? {
                match read(reader.read_u8())? {
                    0 => {
                        budget.name(reader)?;
                        budget.name(reader)?;
                        read(reader.read::<wasmparser::TypeRef>())?;
                    }
                    1 => group(reader, budget)?,
                    2 => {
                        if read(reader.read_u8())? != 0x10 || read(reader.read_u8())? != 1 {
                            return Err(invalid("invalid-core-type-alias"));
                        }
                        read(reader.read_var_u32())?;
                        read(reader.read_var_u32())?;
                    }
                    3 => {
                        budget.name(reader)?;
                        read(reader.read::<wasmparser::TypeRef>())?;
                    }
                    _ => return Err(invalid("invalid-core-type-declaration")),
                }
            }
        }
        0 => {
            read(reader.read_u8())?;
            group(reader, budget)?;
        }
        _ => group(reader, budget)?,
    }
    Ok(())
}

pub(super) fn group(reader: &mut BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    let mut probe = reader.clone();
    if read(probe.read_u8())? == 0x4e {
        read(reader.read_u8())?;
        for _ in 0..budget.members(reader)? {
            subtype(reader, budget)?;
        }
    } else {
        subtype(reader, budget)?;
    }
    Ok(())
}

fn subtype(reader: &mut BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    charge(&mut budget.types, 1, budget.limits.max_type_nodes)?;
    let mut opcode = read(reader.read_u8())?;
    if matches!(opcode, 0x4f | 0x50) {
        for _ in 0..Budget::count(reader, 1)? {
            read(reader.read_var_u32())?;
        }
        opcode = read(reader.read_u8())?;
    }
    if opcode == 0x65 {
        opcode = read(reader.read_u8())?;
    }
    for prefix in [0x4c, 0x4d] {
        if opcode == prefix {
            read(reader.read_var_u32())?;
            opcode = read(reader.read_u8())?;
        }
    }
    match opcode {
        0x60 => {
            for _ in 0..2 {
                for _ in 0..budget.members(reader)? {
                    read(reader.read::<wasmparser::ValType>())?;
                }
            }
        }
        0x5e => {
            read(reader.read::<wasmparser::FieldType>())?;
        }
        0x5f => {
            for _ in 0..budget.members(reader)? {
                read(reader.read::<wasmparser::FieldType>())?;
            }
        }
        0x5d => {
            read(reader.read_var_s33())?;
        }
        _ => return Err(invalid("invalid-core-type")),
    }
    Ok(())
}

fn value(reader: &mut BinaryReader<'_>) -> Result<()> {
    read(reader.read::<wasmparser::ComponentValType>())?;
    Ok(())
}

fn optional_value(reader: &mut BinaryReader<'_>) -> Result<()> {
    read(reader.read::<Option<wasmparser::ComponentValType>>())?;
    Ok(())
}

fn optional_index(reader: &mut BinaryReader<'_>) -> Result<()> {
    match read(reader.read_u8())? {
        0 => (),
        1 => {
            read(reader.read_var_u32())?;
        }
        _ => return Err(invalid("invalid-component-optional-index")),
    }
    Ok(())
}
