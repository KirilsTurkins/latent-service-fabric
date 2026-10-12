//! Source-only post-link shadow-stack transform for the pinned Rust target.
//!
//! LLVM22's normal wasm target uses a shared mutable __stack_pointer global.
//! Replace its actual code accesses with stackless helpers loading/storing a
//! separately bootstrapped canonical-thread context. All other instructions,
//! original functions, data, imports and original custom sections are retained.
//! This is never selected by a builder until bootstrap/lifecycle/ledger and
//! the rebuilt standard runtime are qualified. It does not create a thread.
#![forbid(unsafe_code)]

use sha2::{Digest, Sha256};
use wasm_encoder::reencode::{self, Reencode};
use wasm_encoder::{BlockType, CodeSection, Function, FunctionSection, Instruction, MemArg,
                   Module, TypeSection, ValType};
use wasmparser::{Encoding, ExternalKind, Operator, Parser, Payload, TypeRef, Validator};

mod thread_entry;
pub use thread_entry::{ThreadEntryReceipt, transform_owned_thread_entry};

pub const MAX_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_FUNCTIONS: u32 = 65_534; // two new helpers stay within65,536
pub const MAX_OPERATORS: u64 = 2_000_000;
pub const CONTEXT_STACK_POINTER_OFFSET: u64 = 0;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Receipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub original_stack_global: u32,
    pub original_initial_stack_pointer: u32,
    pub context_get_import: u32,
    pub transformed_gets: u64,
    pub transformed_sets: u64,
    pub helper_get_function: u32,
    pub helper_set_function: u32,
    /// Original custom debug offsets are retained as originals. They are not
    /// silently advertised as relocated source mappings after code changes.
    pub derived_debug_mapping_qualified: bool,
    pub supported_runtime_profile: bool,
}

#[derive(Debug)]
struct Plan {
    type_count: u32,
    function_count: u32,
    imported_functions: u32,
    context_get: u32,
    stack_global: u32,
    stack_initial: u32,
}

fn plan(input: &[u8]) -> Result<Plan, &'static str> {
    if input.len() > MAX_BYTES { return Err("rust-stack-module-byte-limit"); }
    Validator::new().validate_all(input).map_err(|_| "rust-stack-invalid-core-module")?;
    let mut types = Vec::new();
    let mut function_count = 0;
    let mut imported_functions = 0;
    let mut context_get = None;
    let mut globals = Vec::new();
    let mut stack_global = None;
    let mut memory = None;
    let mut operators = 0_u64;
    let mut saw_code = false;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-stack-malformed-core-module")? {
            Payload::Version { encoding, .. } if encoding != Encoding::Module =>
                return Err("rust-stack-component-input-not-core-module"),
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "rust-stack-gc-types-not-qualified")?);
                    if types.len() > MAX_FUNCTIONS as usize { return Err("rust-stack-type-limit"); }
                }
            }
            Payload::ImportSection(reader) => {
                for import in reader.into_imports() {
                    let import = import.map_err(|_| "rust-stack-import-shape")?;
                    match import.ty {
                        TypeRef::Func(index) | TypeRef::FuncExact(index) => {
                            if import.module == "$root" && import.name == "[context-get-1]" {
                                if context_get.is_some() { return Err("rust-stack-duplicate-context-get"); }
                                let ty = types.get(index as usize).ok_or("rust-stack-context-type")?;
                                if !ty.params().is_empty() || ty.results() != [wasmparser::ValType::I32] {
                                    return Err("rust-stack-context-get-signature");
                                }
                                context_get = Some(imported_functions);
                            }
                            imported_functions += 1;
                        }
                        TypeRef::Global(_) => return Err("rust-stack-imported-globals-not-qualified"),
                        TypeRef::Memory(_) => return Err("rust-stack-imported-memory-not-qualified"),
                        _ => {}
                    }
                }
            }
            Payload::FunctionSection(reader) => function_count = reader.count(),
            Payload::MemorySection(reader) => {
                for entry in reader {
                    let ty = entry.map_err(|_| "rust-stack-memory-type")?;
                    if memory.is_some() || ty.shared || ty.memory64 || ty.page_size_log2.is_some() {
                        return Err("rust-stack-requires-single-unshared-memory32");
                    }
                    memory = Some(ty.initial);
                }
            }
            Payload::GlobalSection(reader) => {
                for global in reader {
                    let global = global.map_err(|_| "rust-stack-global-type")?;
                    let mut init = global.init_expr.get_operators_reader();
                    let initial = match init.read().map_err(|_| "rust-stack-global-initializer")? {
                        Operator::I32Const { value } => Some(value as u32),
                        _ => None,
                    };
                    globals.push((global.ty, initial));
                }
            }
            Payload::ExportSection(reader) => {
                for export in reader {
                    let export = export.map_err(|_| "rust-stack-export-shape")?;
                    if export.name == "__stack_pointer" {
                        if export.kind != ExternalKind::Global || stack_global.replace(export.index).is_some() {
                            return Err("rust-stack-global-export-shape");
                        }
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                saw_code = true;
                let mut reader = body.get_operators_reader().map_err(|_| "rust-stack-code-shape")?;
                while !reader.eof() {
                    reader.read().map_err(|_| "rust-stack-operator-shape")?;
                    operators += 1;
                    if operators > MAX_OPERATORS { return Err("rust-stack-operator-limit"); }
                }
            }
            Payload::CustomSection(section) if section.name() == "linking" || section.name().starts_with("reloc.") =>
                return Err("rust-stack-relocatable-object-not-linked-core"),
            _ => {}
        }
    }
    let stack_global = stack_global.ok_or("rust-stack-global-export-missing")?;
    let (ty, initial) = globals.get(stack_global as usize).ok_or("rust-stack-global-index")?;
    if !ty.mutable || ty.shared || ty.content_type != wasmparser::ValType::I32 {
        return Err("rust-stack-global-must-be-mutable-i32");
    }
    let stack_initial = initial.ok_or("rust-stack-global-initializer-not-constant")?;
    let initial_memory = memory.ok_or("rust-stack-memory-missing")?;
    if stack_initial == 0 || stack_initial % 16 != 0 || u64::from(stack_initial) > initial_memory * 65_536 {
        return Err("rust-stack-initial-pointer-outside-aligned-memory");
    }
    if !saw_code || function_count + imported_functions > MAX_FUNCTIONS {
        return Err("rust-stack-function-limit-or-empty-code");
    }
    Ok(Plan { type_count: types.len() as u32, function_count, imported_functions,
              context_get: context_get.ok_or("rust-stack-context-get-import-missing")?,
              stack_global, stack_initial })
}

struct Rewrite {
    plan: Plan,
    gets: u64,
    sets: u64,
    thread_entry: Option<thread_entry::ThreadEntryPlan>,
    next_body: u32,
    thread_body: Option<Function>,
}

impl Rewrite {
    fn get_index(&self) -> u32 { self.plan.imported_functions + self.plan.function_count }
    fn set_index(&self) -> u32 { self.get_index() + 1 }

    fn append_helpers(&self, code: &mut CodeSection) {
        if self.thread_entry.is_some() {
            thread_entry::append_checked_stack_helpers(code, self.plan.context_get);
            return;
        }
        let address = MemArg { offset: CONTEXT_STACK_POINTER_OFFSET, align: 2, memory_index: 0 };
        let mut get = Function::new([(1, ValType::I32)]);
        get.instruction(&Instruction::Call(self.plan.context_get))
            .instruction(&Instruction::LocalTee(0)).instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::If(BlockType::Empty)).instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End).instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(address)).instruction(&Instruction::End);
        code.function(&get);
        let mut set = Function::new([(1, ValType::I32)]);
        set.instruction(&Instruction::Call(self.plan.context_get))
            .instruction(&Instruction::LocalTee(1)).instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::If(BlockType::Empty)).instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End).instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::LocalGet(0)).instruction(&Instruction::I32Store(address))
            .instruction(&Instruction::End);
        code.function(&set);
    }
}

impl Reencode for Rewrite {
    type Error = &'static str;

    fn parse_type_section(&mut self, section: &mut TypeSection,
                          reader: wasmparser::TypeSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_type_section(self, section, reader)?;
        section.ty().function([], [ValType::I32]);
        section.ty().function([ValType::I32], []);
        Ok(())
    }

    fn parse_function_section(&mut self, section: &mut FunctionSection,
                              reader: wasmparser::FunctionSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, section, reader)?;
        section.function(self.plan.type_count).function(self.plan.type_count + 1);
        if let Some(entry) = &self.thread_entry { section.function(entry.function_type); }
        Ok(())
    }

    fn parse_function_body(&mut self, code: &mut CodeSection,
                           body: wasmparser::FunctionBody<'_>) -> Result<(), reencode::Error<Self::Error>> {
        let mut function = self.new_function_with_parsed_locals(&body)?;
        let mut reader = body.get_operators_reader()?;
        while !reader.eof() {
            match reader.read()? {
                Operator::GlobalGet { global_index } if global_index == self.plan.stack_global => {
                    function.instruction(&Instruction::Call(self.get_index())); self.gets += 1;
                }
                Operator::GlobalSet { global_index } if global_index == self.plan.stack_global => {
                    function.instruction(&Instruction::Call(self.set_index())); self.sets += 1;
                }
                operator => { function.instruction(&self.instruction(operator)?); }
            }
        }
        let index = self.plan.imported_functions + self.next_body;
        self.next_body += 1;
        if let Some(entry) = &self.thread_entry {
            if index == entry.function_index {
                let wrapper = entry.wrapper(self.plan.context_get, self.set_index() + 1);
                self.thread_body = Some(function);
                code.function(&wrapper);
                return Ok(());
            }
        }
        code.function(&function);
        Ok(())
    }

    fn parse_code_section(&mut self, code: &mut CodeSection,
                          reader: wasmparser::CodeSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, code, reader)?;
        self.append_helpers(code);
        if self.thread_entry.is_some() {
            code.function(self.thread_body.as_ref().ok_or(reencode::Error::UserError("rust-thread-entry-body-missing"))?);
        }
        Ok(())
    }
}

/// Transform only an authenticated linked-core preimage. The result is source
/// infrastructure, not an enabled std/runtime profile. The context's first u32
/// must be an owned aligned shadow stack initialized before entering Rust.
/// Missing context traps rather than silently selecting the old shared stack.
pub fn transform(input: &[u8], expected_preimage: [u8; 32]) -> Result<(Vec<u8>, Receipt), &'static str> {
    let original_digest: [u8; 32] = Sha256::digest(input).into();
    if original_digest != expected_preimage { return Err("rust-stack-input-preimage-mismatch"); }
    let plan = plan(input)?;
    let mut rewrite = Rewrite { plan, gets: 0, sets: 0, thread_entry: None,
                                next_body: 0, thread_body: None };
    let mut output = Module::new();
    rewrite.parse_core_module(&mut output, Parser::new(0), input)
        .map_err(|_| "rust-stack-reencode-failed")?;
    let bytes = output.finish();
    if bytes.len() > MAX_BYTES { return Err("rust-stack-derived-module-byte-limit"); }
    Validator::new().validate_all(&bytes).map_err(|_| "rust-stack-derived-module-invalid")?;
    let receipt = Receipt { original_digest, derived_digest: Sha256::digest(&bytes).into(),
        original_stack_global: rewrite.plan.stack_global, original_initial_stack_pointer: rewrite.plan.stack_initial,
        context_get_import: rewrite.plan.context_get, transformed_gets: rewrite.gets, transformed_sets: rewrite.sets,
        helper_get_function: rewrite.get_index(), helper_set_function: rewrite.set_index(),
        derived_debug_mapping_qualified: false, supported_runtime_profile: false };
    Ok((bytes, receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{ConstExpr, CustomSection, DataSection, EntityType, ExportKind,
                       ExportSection, GlobalSection, GlobalType, ImportSection,
                       MemorySection, MemoryType};

    fn fixture(context: bool, context_result: ValType, mutable: bool, shared: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [context_result]);
        types.ty().function([], [ValType::I32]);
        module.section(&types);
        if context {
            let mut imports = ImportSection::new();
            imports.import("$root", "[context-get-1]", EntityType::Function(0));
            module.section(&imports);
        }
        let mut functions = FunctionSection::new(); functions.function(1); module.section(&functions);
        let mut memories = MemorySection::new();
        memories.memory(MemoryType { minimum: 1, maximum: Some(1), memory64: false,
                                     shared, page_size_log2: None });
        module.section(&memories);
        let mut globals = GlobalSection::new();
        globals.global(GlobalType { val_type: ValType::I32, mutable, shared: false }, &ConstExpr::i32_const(1024));
        globals.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false }, &ConstExpr::i32_const(9));
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export("run", ExportKind::Func, u32::from(context));
        exports.export("memory", ExportKind::Memory, 0);
        module.section(&exports);
        let mut body = Function::new([(1, ValType::I32)]);
        body.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::LocalSet(0));
        if mutable {
            body.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::I32Const(16))
                .instruction(&Instruction::I32Sub).instruction(&Instruction::GlobalSet(0));
        }
        body.instruction(&Instruction::GlobalGet(1)).instruction(&Instruction::Drop);
        if mutable { body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::GlobalSet(0)); }
        body.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::End);
        let mut code = CodeSection::new(); code.function(&body); module.section(&code);
        let mut data = DataSection::new();
        data.active(0, &ConstExpr::i32_const(128), [0x23, 0x00, 0x24, 0x00]); module.section(&data);
        module.section(&CustomSection { name: Cow::Borrowed("original-debug-opaque"),
            data: Cow::Borrowed(&[0x23, 0x00, 0x24, 0x00]) });
        module.finish()
    }

    fn digest(bytes: &[u8]) -> [u8; 32] { Sha256::digest(bytes).into() }

    #[test]
    fn every_actual_stack_get_set_is_replaced_and_output_validates() {
        let input = fixture(true, ValType::I32, true, false);
        let (output, receipt) = transform(&input, digest(&input)).unwrap();
        assert_eq!((receipt.transformed_gets, receipt.transformed_sets), (3, 2));
        assert_eq!((receipt.helper_get_function, receipt.helper_set_function), (2, 3));
        let mut old_gets = 0; let mut old_sets = 0; let mut other_gets = 0;
        for payload in Parser::new(0).parse_all(&output) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                let mut reader = body.get_operators_reader().unwrap();
                while !reader.eof() {
                    match reader.read().unwrap() {
                        Operator::GlobalGet { global_index: 0 } => old_gets += 1,
                        Operator::GlobalSet { global_index: 0 } => old_sets += 1,
                        Operator::GlobalGet { global_index: 1 } => other_gets += 1,
                        _ => {}
                    }
                }
            }
        }
        assert_eq!((old_gets, old_sets, other_gets), (0, 0, 1));
        Validator::new().validate_all(&output).unwrap();
    }

    #[test]
    fn data_and_original_custom_bytes_are_not_scanned_as_instructions() {
        let input = fixture(true, ValType::I32, true, false);
        let (output, receipt) = transform(&input, digest(&input)).unwrap();
        let mut custom = None; let mut data = None;
        for payload in Parser::new(0).parse_all(&output) {
            match payload.unwrap() {
                Payload::CustomSection(section) if section.name() == "original-debug-opaque" => custom = Some(section.data().to_vec()),
                Payload::DataSection(section) => data = Some(section.into_iter().next().unwrap().unwrap().data.to_vec()),
                _ => {}
            }
        }
        assert_eq!(custom.unwrap(), [0x23, 0x00, 0x24, 0x00]);
        assert_eq!(data.unwrap(), [0x23, 0x00, 0x24, 0x00]);
        assert!(!receipt.derived_debug_mapping_qualified);
        assert!(!receipt.supported_runtime_profile);
    }

    #[test]
    fn wrong_preimage_rejects_without_touching_input() {
        let input = fixture(true, ValType::I32, true, false); let original = input.clone();
        assert_eq!(transform(&input, [0; 32]).unwrap_err(), "rust-stack-input-preimage-mismatch");
        assert_eq!(input, original);
    }

    #[test]
    fn absent_or_wrong_canonical_context_import_is_not_a_shared_stack_fallback() {
        for (present, result, expected) in [(false, ValType::I32, "rust-stack-context-get-import-missing"),
                                            (true, ValType::I64, "rust-stack-context-get-signature")] {
            let input = fixture(present, result, true, false);
            assert_eq!(transform(&input, digest(&input)).unwrap_err(), expected);
        }
    }

    #[test]
    fn immutable_stack_or_shared_memory_are_named_profile_rejections() {
        let input = fixture(true, ValType::I32, false, false);
        assert_eq!(transform(&input, digest(&input)).unwrap_err(), "rust-stack-global-must-be-mutable-i32");
        let input = fixture(true, ValType::I32, true, true);
        assert_eq!(transform(&input, digest(&input)).unwrap_err(), "rust-stack-requires-single-unshared-memory32");
    }

    #[test]
    fn helpers_have_no_shadow_stack_or_allocator_prologue_and_trap_without_context() {
        let input = fixture(true, ValType::I32, true, false);
        let (output, _) = transform(&input, digest(&input)).unwrap();
        let bodies: Vec<_> = Parser::new(0).parse_all(&output).filter_map(|payload|
            match payload.unwrap() { Payload::CodeSectionEntry(body) => Some(body), _ => None }).collect();
        assert_eq!(bodies.len(), 3);
        for body in &bodies[1..] {
            let mut reader = body.get_operators_reader().unwrap(); let mut calls = Vec::new(); let mut traps = 0;
            while !reader.eof() {
                match reader.read().unwrap() {
                    Operator::Call { function_index } => calls.push(function_index),
                    Operator::Unreachable => traps += 1,
                    Operator::GlobalGet { .. } | Operator::GlobalSet { .. } => panic!("helper must not depend on shared stack globals"),
                    _ => {}
                }
            }
            assert_eq!(calls, [0]); assert_eq!(traps, 1);
        }
    }

    #[test]
    fn malformed_and_over_bound_inputs_fail_before_reencode() {
        assert!(transform(b"not wasm", digest(b"not wasm")).is_err());
        let oversized = vec![0; MAX_BYTES + 1];
        assert_eq!(transform(&oversized, digest(&oversized)).unwrap_err(), "rust-stack-module-byte-limit");
    }
}
