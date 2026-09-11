//! Borrowed code, initializer and element vectors before Validator allocation.
use super::{bounded_name, charge, read, Budget, Result};
use wasmparser::{
    ElementItems, ElementKind, Imports, Operator, OperatorsReader, Parser, Payload, TableInit,
    TypeRef,
};

pub(super) fn preflight(component: &[u8], budget: &mut Budget) -> Result<()> {
    for payload in Parser::new(0).parse_all(component) {
        match read(payload)? {
            Payload::CodeSectionEntry(body) => {
                let locals = read(body.get_locals_reader())?;
                charge(
                    &mut budget.types,
                    locals.get_count() as usize,
                    budget.limits.max_type_nodes,
                )?;
                for local in locals {
                    let (count, _) = read(local)?;
                    charge(
                        &mut budget.locals,
                        count as usize,
                        budget.limits.max_core_locals,
                    )?;
                }
                operators(read(body.get_operators_reader())?, budget)?;
            }
            Payload::ImportSection(imports) => imports_preflight(imports, budget)?,
            Payload::ExportSection(exports) => {
                for export in exports {
                    bounded_name(read(export)?.name, budget)?;
                }
            }
            Payload::GlobalSection(globals) => {
                for global in globals {
                    operators(read(global)?.init_expr.get_operators_reader(), budget)?;
                }
            }
            Payload::TableSection(tables) => {
                for table in tables {
                    if let TableInit::Expr(expression) = read(table)?.init {
                        operators(expression.get_operators_reader(), budget)?;
                    }
                }
            }
            Payload::ElementSection(elements) => {
                for element in elements {
                    let element = read(element)?;
                    if let ElementKind::Active { offset_expr, .. } = element.kind {
                        operators(offset_expr.get_operators_reader(), budget)?;
                    }
                    match element.items {
                        ElementItems::Functions(items) => {
                            charge(
                                &mut budget.types,
                                items.count() as usize,
                                budget.limits.max_type_nodes,
                            )?;
                        }
                        ElementItems::Expressions(_, items) => {
                            charge(
                                &mut budget.types,
                                items.count() as usize,
                                budget.limits.max_type_nodes,
                            )?;
                            for expression in items {
                                operators(read(expression)?.get_operators_reader(), budget)?;
                            }
                        }
                    }
                }
            }
            Payload::DataSection(data) => {
                for data in data {
                    if let wasmparser::DataKind::Active { offset_expr, .. } = read(data)?.kind {
                        operators(offset_expr.get_operators_reader(), budget)?;
                    }
                }
            }
            _ => (),
        }
    }
    Ok(())
}

fn imports_preflight(
    imports: wasmparser::ImportSectionReader<'_>,
    budget: &mut Budget,
) -> Result<()> {
    for imports in imports {
        match read(imports)? {
            Imports::Single(_, import) => {
                bounded_name(import.module, budget)?;
                bounded_name(import.name, budget)?;
                imported(import.ty, 1, budget)?;
            }
            Imports::Compact1 { module, items } => {
                bounded_name(module, budget)?;
                charge(
                    &mut budget.types,
                    items.count() as usize,
                    budget.limits.max_type_nodes,
                )?;
                for item in items {
                    let item = read(item)?;
                    bounded_name(item.name, budget)?;
                    imported(item.ty, 1, budget)?;
                }
            }
            Imports::Compact2 { module, ty, names } => {
                bounded_name(module, budget)?;
                charge(
                    &mut budget.types,
                    names.count() as usize,
                    budget.limits.max_type_nodes,
                )?;
                imported(ty, names.count() as usize, budget)?;
                for name in names {
                    bounded_name(read(name)?, budget)?;
                }
            }
        }
    }
    Ok(())
}

fn imported(ty: TypeRef, count: usize, budget: &mut Budget) -> Result<()> {
    if matches!(ty, TypeRef::Func(_) | TypeRef::FuncExact(_)) {
        charge(
            &mut budget.functions,
            count,
            budget.limits.max_core_functions,
        )?;
    }
    Ok(())
}

fn operators(mut operators: OperatorsReader<'_>, budget: &mut Budget) -> Result<()> {
    while !operators.eof() {
        charge(&mut budget.operators, 1, budget.limits.max_operators)?;
        vector_operands(operators.get_binary_reader(), budget)?;
        if let Operator::BrTable { targets } = read(operators.read())? {
            charge(
                &mut budget.operators,
                targets.len() as usize,
                budget.limits.max_operators,
            )?;
        }
    }
    Ok(())
}

// These instructions allocate owned operand vectors in the pinned reader.
// Read only the scalar prefix and vector count first; other instructions use
// borrowed operands or fixed-size values. Branch-table targets remain borrowed.
fn vector_operands(mut reader: wasmparser::BinaryReader<'_>, budget: &mut Budget) -> Result<()> {
    match read(reader.read_u8())? {
        0x1c => (), // typed select: vector<valtype>
        0x1f => {
            let first = read(reader.clone().read_u8())?;
            if first == 0x40 {
                read(reader.read_u8())?;
            } else if first & 0xc0 == 0x40 {
                read(reader.read::<wasmparser::ValType>())?;
            } else {
                read(reader.read_var_s33())?;
            }
        }
        0xe3 | 0xe5 => {
            read(reader.read_var_u32())?;
        }
        0xe4 => {
            read(reader.read_var_u32())?;
            read(reader.read_var_u32())?;
        }
        _ => return Ok(()),
    }
    let count = Budget::count(&mut reader, budget.limits.max_type_members)?;
    charge(&mut budget.operators, count, budget.limits.max_operators)
}
