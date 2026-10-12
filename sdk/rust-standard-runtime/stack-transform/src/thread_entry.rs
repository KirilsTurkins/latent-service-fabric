//! Install the pre-admitted actual thread context before a Rust prologue and
//! detach it only after the final Rust/TLS frame returns. Native-fiber proof
//! and owner settlement belong to the parent/reaper, not this memory flag.
use super::*;
use wasmparser::{ElementItems, ElementKind, RefType};

const ENTRY: &str = "__lsf_rust_owned_thread_entry";
const LOW: u64 = 4;
const HIGH: u64 = 8;
const PHASE: u64 = 12;
const PREPARED: i32 = 1;
const RUNNING: i32 = 2;
const TLS_FINISHED: i32 = 4;
const WASM_FRAMES_EXITED: i32 = 5;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThreadEntryReceipt {
    pub stack: Receipt,
    pub entry_function: u32,
    pub original_rust_body_function: u32,
    pub canonical_context_set_import: u32,
    pub canonical_thread_new_import: u32,
    pub original_indirect_table: u32,
    pub context_installed_before_rust_prologue: bool,
    pub context_detached_after_last_rust_frame: bool,
    pub native_fiber_retirement_qualified: bool,
    pub automatically_selected: bool,
}

pub(super) struct ThreadEntryPlan {
    pub function_index: u32,
    pub function_type: u32,
    context_set: u32,
    thread_new: u32,
}

fn inspect(input: &[u8], base: &Plan) -> Result<ThreadEntryPlan, &'static str> {
    if base.imported_functions + base.function_count > 65_533 {
        return Err("rust-thread-three-function-append-limit");
    }
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut imported = 0;
    let mut context_set = None;
    let mut thread_new = None;
    let mut entry = None;
    let mut table_export = None;
    let mut tables = 0;
    let mut active_functions = Vec::new();
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-thread-core-shape")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "rust-thread-core-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for import in reader.into_imports() {
                    let import = import.map_err(|_| "rust-thread-import-shape")?;
                    match import.ty {
                        TypeRef::Func(index) | TypeRef::FuncExact(index) => {
                            let ty = types.get(index as usize).ok_or("rust-thread-import-type")?;
                            if import.module == "$root" && import.name == "[context-set-1]" {
                                if context_set.replace(imported).is_some() || ty.params() != [wasmparser::ValType::I32]
                                    || !ty.results().is_empty() {
                                    return Err("rust-thread-context-set-signature-or-duplicate");
                                }
                            }
                            if import.module == "$root" && import.name == "[thread-new-indirect-v0]" {
                                if thread_new.replace(imported).is_some() || ty.params() != [wasmparser::ValType::I32, wasmparser::ValType::I32]
                                    || ty.results() != [wasmparser::ValType::I32] {
                                    return Err("rust-thread-new-signature-or-duplicate");
                                }
                            }
                            imported += 1;
                        }
                        TypeRef::Table(_) => return Err("rust-thread-imported-table-not-qualified"),
                        _ => {}
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for index in reader { functions.push(index.map_err(|_| "rust-thread-function-type")?); }
            }
            Payload::TableSection(reader) => {
                for table in reader {
                    let table = table.map_err(|_| "rust-thread-table-shape")?;
                    tables += 1;
                    if tables != 1 || table.ty.element_type != RefType::FUNCREF || table.ty.table64
                        || table.ty.shared || table.ty.initial > 65_536
                        || table.ty.maximum.is_none_or(|maximum| maximum > 65_536) {
                        return Err("rust-thread-requires-finite-funcref-table32");
                    }
                }
            }
            Payload::ExportSection(reader) => {
                for export in reader {
                    let export = export.map_err(|_| "rust-thread-export-shape")?;
                    if export.name == ENTRY {
                        if export.kind != ExternalKind::Func || entry.replace(export.index).is_some() {
                            return Err("rust-thread-entry-export-shape");
                        }
                    }
                    if export.name == "__indirect_function_table" {
                        if export.kind != ExternalKind::Table || table_export.replace(export.index).is_some() {
                            return Err("rust-thread-table-export-shape");
                        }
                    }
                }
            }
            Payload::ElementSection(reader) => {
                for element in reader {
                    let element = element.map_err(|_| "rust-thread-element-shape")?;
                    if let ElementKind::Active { table_index, offset_expr } = element.kind {
                        if table_index.unwrap_or(0) != 0 { return Err("rust-thread-element-table-mismatch"); }
                        let mut offset = offset_expr.get_operators_reader();
                        if !matches!(offset.read().map_err(|_| "rust-thread-element-offset")?, Operator::I32Const { value } if value >= 0) {
                            return Err("rust-thread-element-offset-not-constant");
                        }
                        if let ElementItems::Functions(reader) = element.items {
                            for index in reader { active_functions.push(index.map_err(|_| "rust-thread-element-function")?); }
                        }
                    }
                }
            }
            // A normal initializer could enter translated Rust before any
            // root wrapper is installed. Do not manufacture that support.
            Payload::StartSection { .. } => return Err("rust-thread-core-start-not-qualified"),
            _ => {}
        }
    }
    let function_index = entry.ok_or("rust-thread-owned-entry-export-missing")?;
    let defined = function_index.checked_sub(imported).ok_or("rust-thread-entry-must-be-defined")?;
    let function_type = *functions.get(defined as usize).ok_or("rust-thread-entry-index")?;
    let ty = types.get(function_type as usize).ok_or("rust-thread-entry-type")?;
    if ty.params() != [wasmparser::ValType::I32] || !ty.results().is_empty() {
        return Err("rust-thread-entry-requires-i32-to-unit");
    }
    if tables != 1 || table_export != Some(0) || !active_functions.contains(&function_index) {
        return Err("rust-thread-entry-not-in-original-exported-table");
    }
    Ok(ThreadEntryPlan { function_index, function_type,
        context_set: context_set.ok_or("rust-thread-context-set-import-missing")?,
        thread_new: thread_new.ok_or("rust-thread-new-import-missing")? })
}

fn address(offset: u64) -> MemArg { MemArg { offset, align: 2, memory_index: 0 } }
fn trap_if(function: &mut Function) {
    function.instruction(&Instruction::If(BlockType::Empty)).instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}

impl ThreadEntryPlan {
    pub(super) fn wrapper(&self, context_get: u32, original_rust_body: u32) -> Function {
        let mut body = Function::new([]);
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Eqz);
        trap_if(&mut body);
        body.instruction(&Instruction::Call(context_get));
        trap_if(&mut body); // An actual fresh canonical child has no context.
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Load(address(PHASE)))
            .instruction(&Instruction::I32Const(PREPARED)).instruction(&Instruction::I32Ne);
        trap_if(&mut body);
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Const(RUNNING))
            .instruction(&Instruction::I32Store(address(PHASE)))
            .instruction(&Instruction::LocalGet(0)).instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::LocalGet(0)).instruction(&Instruction::Call(original_rust_body));
        body.instruction(&Instruction::Call(context_get)).instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Ne);
        trap_if(&mut body);
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Load(address(PHASE)))
            .instruction(&Instruction::I32Const(TLS_FINISHED)).instruction(&Instruction::I32Ne);
        trap_if(&mut body);
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Load(address(0)))
            .instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Load(address(HIGH)))
            .instruction(&Instruction::I32Ne);
        trap_if(&mut body); // The last real Rust epilogue restored its stack.
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Const(WASM_FRAMES_EXITED))
            .instruction(&Instruction::I32Store(address(PHASE)))
            .instruction(&Instruction::I32Const(0)).instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::End);
        // No Rust cleanup, allocation, owner settlement, parent wake or stack
        // access follows detach. Host/native retirement is deliberately unknown.
        body
    }
}

fn check_prefix(body: &mut Function, context: u32, pointer: u32) {
    body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(PHASE)))
        .instruction(&Instruction::I32Const(RUNNING)).instruction(&Instruction::I32LtU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(PHASE)))
        .instruction(&Instruction::I32Const(TLS_FINISHED)).instruction(&Instruction::I32GtU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer)).instruction(&Instruction::I32Const(15))
        .instruction(&Instruction::I32And);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer))
        .instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(LOW)))
        .instruction(&Instruction::I32LtU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer))
        .instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(HIGH)))
        .instruction(&Instruction::I32GtU);
    trap_if(body);
}

pub(super) fn append_checked_stack_helpers(code: &mut CodeSection, context_get: u32) {
    let mut get = Function::new([(2, ValType::I32)]);
    get.instruction(&Instruction::Call(context_get)).instruction(&Instruction::LocalTee(0))
        .instruction(&Instruction::I32Eqz);
    trap_if(&mut get);
    get.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Load(address(0)))
        .instruction(&Instruction::LocalSet(1));
    check_prefix(&mut get, 0, 1);
    get.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::End);
    code.function(&get);
    let mut set = Function::new([(1, ValType::I32)]);
    set.instruction(&Instruction::Call(context_get)).instruction(&Instruction::LocalTee(1))
        .instruction(&Instruction::I32Eqz);
    trap_if(&mut set);
    check_prefix(&mut set, 1, 0);
    set.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::LocalGet(0))
        .instruction(&Instruction::I32Store(address(0))).instruction(&Instruction::End);
    code.function(&set);
}

/// Preserve the original callback/table index while appending its real Rust
/// body. This wrapper is not a std::thread implementation or public profile.
/// Its context must already own the original Task/Native admissions. Every
/// actual host/native continuation must be gone before a parent reaps it.
pub fn transform_owned_thread_entry(input: &[u8], expected_preimage: [u8; 32])
    -> Result<(Vec<u8>, ThreadEntryReceipt), &'static str>
{
    let original_digest: [u8; 32] = Sha256::digest(input).into();
    if original_digest != expected_preimage { return Err("rust-stack-input-preimage-mismatch"); }
    let base = plan(input)?;
    let entry = inspect(input, &base)?;
    let function_index = entry.function_index;
    let context_set = entry.context_set;
    let thread_new = entry.thread_new;
    let mut rewrite = Rewrite { plan: base, gets: 0, sets: 0, thread_entry: Some(entry),
                                next_body: 0, thread_body: None };
    let original_rust_body = rewrite.set_index() + 1;
    let mut module = Module::new();
    rewrite.parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "rust-thread-entry-reencode-failed")?;
    let output = module.finish();
    if output.len() > MAX_BYTES { return Err("rust-stack-derived-module-byte-limit"); }
    Validator::new().validate_all(&output).map_err(|_| "rust-thread-entry-derived-module-invalid")?;
    let stack = Receipt { original_digest, derived_digest: Sha256::digest(&output).into(),
        original_stack_global: rewrite.plan.stack_global,
        original_initial_stack_pointer: rewrite.plan.stack_initial,
        context_get_import: rewrite.plan.context_get, transformed_gets: rewrite.gets,
        transformed_sets: rewrite.sets, helper_get_function: rewrite.get_index(),
        helper_set_function: rewrite.set_index(), derived_debug_mapping_qualified: false,
        supported_runtime_profile: false };
    Ok((output, ThreadEntryReceipt { stack, entry_function: function_index,
        original_rust_body_function: original_rust_body, canonical_context_set_import: context_set,
        canonical_thread_new_import: thread_new, original_indirect_table: 0,
        context_installed_before_rust_prologue: true, context_detached_after_last_rust_frame: true,
        native_fiber_retirement_qualified: false, automatically_selected: false }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{ConstExpr, ElementSection, Elements, EntityType, ExportKind,
        ExportSection, GlobalSection, GlobalType, ImportSection, MemorySection,
        MemoryType, TableSection, TableType};

    fn fixture(set: bool, set_correct: bool, new: bool, entry_correct: bool, table_entry: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        types.ty().function([ValType::I32, ValType::I32], [ValType::I32]);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        if set { imports.import("$root", "[context-set-1]", EntityType::Function(if set_correct { 1 } else { 0 })); }
        if new { imports.import("$root", "[thread-new-indirect-v0]", EntityType::Function(2)); }
        module.section(&imports);
        let imported = 1 + u32::from(set) + u32::from(new);
        let mut functions = FunctionSection::new();
        functions.function(if entry_correct { 1 } else { 0 }).function(0);
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType { element_type: wasm_encoder::RefType::FUNCREF,
            table64: false, minimum: 1, maximum: Some(1), shared: false });
        module.section(&tables);
        let mut memory = MemorySection::new();
        memory.memory(MemoryType { minimum: 1, maximum: Some(1), memory64: false,
            shared: false, page_size_log2: None });
        module.section(&memory);
        let mut globals = GlobalSection::new();
        globals.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false }, &ConstExpr::i32_const(65_536));
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export(ENTRY, ExportKind::Func, imported);
        exports.export("run", ExportKind::Func, imported + 1);
        exports.export("__indirect_function_table", ExportKind::Table, 0);
        exports.export("memory", ExportKind::Memory, 0);
        module.section(&exports);
        let elements = [if table_entry { imported } else { imported + 1 }];
        let mut table_values = ElementSection::new();
        table_values.active(Some(0), &ConstExpr::i32_const(0), Elements::Functions(Cow::Borrowed(&elements)));
        module.section(&table_values);
        let mut body = Function::new([(1, ValType::I32)]);
        if entry_correct {
            body.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::LocalSet(1))
                .instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::I32Const(32))
                .instruction(&Instruction::I32Sub).instruction(&Instruction::GlobalSet(0));
            // A deliberately small encoded Rust-body stand-in. The native TLS
            // source tests separately execute real destructor/drain code.
            body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Const(TLS_FINISHED))
                .instruction(&Instruction::I32Store(address(PHASE)))
                .instruction(&Instruction::LocalGet(1)).instruction(&Instruction::GlobalSet(0));
        } else { body.instruction(&Instruction::I32Const(0)); }
        body.instruction(&Instruction::End);
        let mut run = Function::new([]);
        run.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::End);
        let mut code = CodeSection::new(); code.function(&body).function(&run);
        module.section(&code);
        module.finish()
    }

    fn digest(input: &[u8]) -> [u8; 32] { Sha256::digest(input).into() }
    fn code<'a>(input: &'a [u8]) -> Vec<wasmparser::FunctionBody<'a>> {
        Parser::new(0).parse_all(input).filter_map(|payload| match payload.unwrap() {
            Payload::CodeSectionEntry(body) => Some(body), _ => None,
        }).collect()
    }

    #[test]
    fn real_table_callback_index_is_preserved_and_context_surrounds_original_rust_body() {
        let input = fixture(true, true, true, true, true);
        let (output, receipt) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        assert_eq!((receipt.entry_function, receipt.original_rust_body_function), (3, 7));
        assert_eq!((receipt.stack.helper_get_function, receipt.stack.helper_set_function), (5, 6));
        assert_eq!((receipt.stack.transformed_gets, receipt.stack.transformed_sets), (3, 2));
        let bodies = code(&output);
        assert_eq!(bodies.len(), 5);
        let mut reader = bodies[0].get_operators_reader().unwrap();
        let mut calls = Vec::new(); let mut original_global_access = false;
        while !reader.eof() {
            match reader.read().unwrap() {
                Operator::Call { function_index } => calls.push(function_index),
                Operator::GlobalGet { .. } | Operator::GlobalSet { .. } => original_global_access = true,
                _ => {}
            }
        }
        // Install before the real cloned body; after it returns, verify current
        // identity and detach. No allocator, Rust cleanup or owner refund call.
        assert_eq!(calls, [0, 1, 7, 0, 1]);
        assert!(!original_global_access);
        let mut table_target = None;
        let mut export = None;
        for payload in Parser::new(0).parse_all(&output) {
            match payload.unwrap() {
                Payload::ElementSection(section) => {
                    if let ElementItems::Functions(reader) = section.into_iter().next().unwrap().unwrap().items {
                        table_target = Some(reader.into_iter().next().unwrap().unwrap());
                    }
                }
                Payload::ExportSection(section) => {
                    for item in section { let item = item.unwrap(); if item.name == ENTRY { export = Some(item.index); } }
                }
                _ => {}
            }
        }
        assert_eq!((export, table_target), (Some(3), Some(3)));
        Validator::new().validate_all(&output).unwrap();
        assert!(receipt.context_installed_before_rust_prologue && receipt.context_detached_after_last_rust_frame);
        assert!(!receipt.native_fiber_retirement_qualified && !receipt.automatically_selected);
        assert!(!receipt.stack.supported_runtime_profile && !receipt.stack.derived_debug_mapping_qualified);
    }

    #[test]
    fn absent_or_wrong_canonical_set_and_thread_new_never_fall_back_to_shared_state() {
        for (set, correct, new, expected) in [
            (false, true, true, "rust-thread-context-set-import-missing"),
            (true, false, true, "rust-thread-context-set-signature-or-duplicate"),
            (true, true, false, "rust-thread-new-import-missing"),
        ] {
            let input = fixture(set, correct, new, true, true);
            assert_eq!(transform_owned_thread_entry(&input, digest(&input)).unwrap_err(), expected);
        }
    }

    #[test]
    fn wrong_entry_or_missing_original_table_target_rejects_without_rebinding_a_function() {
        for (correct, table, expected) in [
            (false, true, "rust-thread-entry-requires-i32-to-unit"),
            (true, false, "rust-thread-entry-not-in-original-exported-table"),
        ] {
            let input = fixture(true, true, true, correct, table);
            let original = input.clone();
            assert_eq!(transform_owned_thread_entry(&input, digest(&input)).unwrap_err(), expected);
            assert_eq!(input, original);
        }
    }

    #[test]
    fn stale_preimage_and_missing_owned_entry_cannot_qualify_a_callback() {
        let input = fixture(true, true, true, true, true);
        assert_eq!(transform_owned_thread_entry(&input, [0; 32]).unwrap_err(), "rust-stack-input-preimage-mismatch");
        let mut root_only = input.clone();
        let position = root_only.windows(ENTRY.len()).position(|part| part == ENTRY.as_bytes()).unwrap();
        root_only[position + ENTRY.len() - 1] = b'x';
        assert_eq!(transform_owned_thread_entry(&root_only, digest(&root_only)).unwrap_err(), "rust-thread-owned-entry-export-missing");
    }
}
