//! Stackless root attach/finish/detach and a final System-only reaper postlude.
//! This is source infrastructure; no component/profile is enabled by it.
use super::*;
use wasm_encoder::{ConstExpr, GlobalSection, GlobalType};

const ROOT: &str = "__lsf_rust_activation_root";
const BOOT: &str = "__lsf_rust_root_bootstrap";
const FINISH: &str = "__lsf_rust_root_finish";
const REAP: &str = "__lsf_rust_root_reap";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RootReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub root_function: u32,
    pub original_rust_body: u32,
    pub bootstrap_function: u32,
    pub finish_function: u32,
    pub reap_function: u32,
    pub lifecycle_global: u32,
    pub root_stack_low: u32,
    pub root_stack_high: u32,
    pub root_export_bootstrap_qualified: bool,
    pub canonical_creation_enabled: bool,
}

struct Root {
    root: u32,
    ty: u32,
    params: Vec<ValType>,
    results: Vec<ValType>,
    boot: u32,
    finish: u32,
    reap: u32,
    context_set: u32,
    lifecycle: u32,
    cloned: u32,
    base: Plan,
    get: u32,
    set: u32,
    low: u32,
}

fn value(ty: wasmparser::ValType) -> Result<ValType, &'static str> {
    Ok(match ty {
        wasmparser::ValType::I32 => ValType::I32,
        wasmparser::ValType::I64 => ValType::I64,
        wasmparser::ValType::F32 => ValType::F32,
        wasmparser::ValType::F64 => ValType::F64,
        _ => return Err("rust-root-nonnumeric-flat-abi-not-qualified"),
    })
}

fn inspect(input: &[u8], thread: &ThreadEntryReceipt) -> Result<Root, &'static str> {
    let base = plan(input)?;
    let mut types = Vec::new(); let mut functions = Vec::new();
    let mut exports = std::collections::BTreeMap::new();
    let mut imported = 0; let mut context_set = None; let mut globals = 0;
    let mut initial_globals = Vec::new(); let mut low_global = None;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-root-core-shape")? {
            Payload::TypeSection(reader) => for ty in reader.into_iter_err_on_gc_types() {
                types.push(ty.map_err(|_| "rust-root-type")?);
            },
            Payload::ImportSection(reader) => for import in reader.into_imports() {
                let import = import.map_err(|_| "rust-root-import")?;
                if let TypeRef::Func(index) | TypeRef::FuncExact(index) = import.ty {
                    if import.module == "$root" && import.name == "[context-set-1]" {
                        let ty = types.get(index as usize).ok_or("rust-root-context-set-type")?;
                        if context_set.replace(imported).is_some()
                            || ty.params() != [wasmparser::ValType::I32] || !ty.results().is_empty() {
                            return Err("rust-root-context-set-signature-or-duplicate");
                        }
                    }
                    imported += 1;
                }
            },
            Payload::FunctionSection(reader) => for ty in reader { functions.push(ty.map_err(|_| "rust-root-function-type")?); },
            Payload::GlobalSection(reader) => {
                globals = reader.count();
                for global in reader {
                    let global = global.map_err(|_| "rust-root-global")?;
                    let mut reader = global.init_expr.get_operators_reader();
                    let value = match reader.read().map_err(|_| "rust-root-global-init")? {
                        Operator::I32Const { value } if value >= 0 => Some(value as u32),
                        _ => None,
                    };
                    initial_globals.push((global.ty, value));
                }
            },
            Payload::ExportSection(reader) => for export in reader {
                let export = export.map_err(|_| "rust-root-export")?;
                if export.name == "__stack_low" {
                    if export.kind != ExternalKind::Global || low_global.replace(export.index).is_some() {
                        return Err("rust-root-stack-low-export");
                    }
                }
                if [ROOT, BOOT, FINISH, REAP].contains(&export.name) {
                    if export.kind != ExternalKind::Func || exports.insert(export.name, export.index).is_some() {
                        return Err("rust-root-support-export-shape");
                    }
                }
            },
            Payload::StartSection { .. } => return Err("rust-root-start-before-bootstrap-denied"),
            _ => {}
        }
    }
    if exports.len() != 4 || globals >= MAX_FUNCTIONS || functions.len() >= MAX_FUNCTIONS as usize {
        return Err("rust-root-support-exports-or-bounds");
    }
    let function_type = |name: &str| -> Result<(u32, &wasmparser::FuncType), &'static str> {
        let defined = exports[name].checked_sub(imported).ok_or("rust-root-support-must-be-defined")?;
        let index = *functions.get(defined as usize).ok_or("rust-root-support-function-index")?;
        Ok((index, types.get(index as usize).ok_or("rust-root-support-type-index")?))
    };
    let (ty, root) = function_type(ROOT)?;
    let (_, boot) = function_type(BOOT)?;
    let (_, finish) = function_type(FINISH)?;
    let (_, reap) = function_type(REAP)?;
    if boot.params() != [wasmparser::ValType::I32, wasmparser::ValType::I32] || boot.results() != [wasmparser::ValType::I32]
        || finish.params() != [wasmparser::ValType::I32] || !finish.results().is_empty()
        || reap.params() != [wasmparser::ValType::I32] || !reap.results().is_empty()
        || root.params().len() > 16 || root.results().len() > 16
    { return Err("rust-root-support-or-flat-abi-signature"); }
    let distinct = exports.values().copied().collect::<std::collections::BTreeSet<_>>();
    if distinct.len() != 4 || distinct.contains(&thread.entry_function)
        || distinct.contains(&thread.stack.helper_get_function) || distinct.contains(&thread.stack.helper_set_function) {
        return Err("rust-root-support-function-alias-denied");
    }
    let (low_type, low) = initial_globals.get(low_global.ok_or("rust-root-linker-stack-low-missing")? as usize)
        .ok_or("rust-root-stack-low-index")?;
    let low = low.ok_or("rust-root-stack-low-not-constant")?;
    if low_type.content_type != wasmparser::ValType::I32 || low_type.mutable || low_type.shared
        || low == 0 || low % 16 != 0 || low >= base.stack_initial || base.stack_initial - low < 65_536 {
        return Err("rust-root-linker-stack-range");
    }
    if thread.stack.original_stack_global != base.stack_global
        || thread.stack.original_initial_stack_pointer != base.stack_initial
        || thread.stack.context_get_import != base.context_get {
        return Err("rust-root-thread-receipt-layout");
    }
    let helpers = thread_entry::checked_stack_helpers(base.context_get).map(Function::into_raw_body);
    let mut index = imported; let mut found = 0;
    for payload in Parser::new(0).parse_all(input) {
        if let Payload::CodeSectionEntry(body) = payload.map_err(|_| "rust-root-helper-shape")? {
            for (helper, expected) in [(thread.stack.helper_get_function, &helpers[0]),
                (thread.stack.helper_set_function, &helpers[1])] {
                if index == helper {
                    let range = body.range();
                    let start = usize::try_from(range.start).map_err(|_| "rust-root-helper-range")?;
                    let end = usize::try_from(range.end).map_err(|_| "rust-root-helper-range")?;
                    if input.get(start..end) != Some(expected.as_slice()) {
                        return Err("rust-root-thread-helper-body-mismatch");
                    }
                    found += 1;
                }
            }
            index += 1;
        }
    }
    if found != 2 || thread.stack.helper_get_function == thread.stack.helper_set_function {
        return Err("rust-root-thread-helper-indices");
    }
    Ok(Root { root: exports[ROOT], ty,
        params: root.params().iter().copied().map(value).collect::<Result<_,_>>()?,
        results: root.results().iter().copied().map(value).collect::<Result<_,_>>()?,
        boot: exports[BOOT], finish: exports[FINISH], reap: exports[REAP],
        context_set: context_set.ok_or("rust-root-context-set-missing")?, lifecycle: globals,
        cloned: imported + functions.len() as u32, base,
        get: thread.stack.helper_get_function, set: thread.stack.helper_set_function, low })
}

fn address(offset: u64) -> MemArg { MemArg { offset, align: 2, memory_index: 0 } }
fn reject(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty)).instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}
impl Root {
    fn wrapper(&self) -> Function {
        let context = self.params.len() as u32;
        let mut locals = vec![(1, ValType::I32)];
        locals.extend(self.results.iter().map(|ty| (1, *ty)));
        let mut body = Function::new(locals);
        body.instruction(&Instruction::GlobalGet(self.lifecycle)); reject(&mut body);
        body.instruction(&Instruction::Call(self.base.context_get)); reject(&mut body);
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32Ne); reject(&mut body);
        body.instruction(&Instruction::I32Const(self.low as i32));
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::Call(self.boot)).instruction(&Instruction::LocalTee(context))
            .instruction(&Instruction::I32Eqz); reject(&mut body);
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(12)))
            .instruction(&Instruction::I32Const(1)).instruction(&Instruction::I32Ne); reject(&mut body);
        for (offset, expected) in [(0, self.base.stack_initial), (4, self.low), (8, self.base.stack_initial)] {
            body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(offset)))
                .instruction(&Instruction::I32Const(expected as i32)).instruction(&Instruction::I32Ne);
            reject(&mut body);
        }
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32Ne); reject(&mut body);
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::I32Store(address(12)))
            .instruction(&Instruction::LocalGet(context)).instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(1)).instruction(&Instruction::GlobalSet(self.lifecycle));
        for index in 0..self.params.len() as u32 { body.instruction(&Instruction::LocalGet(index)); }
        body.instruction(&Instruction::Call(self.cloned));
        for index in (0..self.results.len() as u32).rev() { body.instruction(&Instruction::LocalSet(context + 1 + index)); }
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::Call(self.finish));
        body.instruction(&Instruction::Call(self.base.context_get)).instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Ne); reject(&mut body);
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(12)))
            .instruction(&Instruction::I32Const(4)).instruction(&Instruction::I32Ne); reject(&mut body);
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(0)))
            .instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Load(address(8)))
            .instruction(&Instruction::I32Ne); reject(&mut body);
        body.instruction(&Instruction::LocalGet(context)).instruction(&Instruction::I32Const(5))
            .instruction(&Instruction::I32Store(address(12)))
            .instruction(&Instruction::I32Const(0)).instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(3)).instruction(&Instruction::GlobalSet(self.lifecycle))
            .instruction(&Instruction::LocalGet(context)).instruction(&Instruction::Call(self.reap))
            .instruction(&Instruction::I32Const(2)).instruction(&Instruction::GlobalSet(self.lifecycle));
        for index in 0..self.results.len() as u32 { body.instruction(&Instruction::LocalGet(context + 1 + index)); }
        body.instruction(&Instruction::End);
        body
    }
    fn bootstrap_stack_access(&self, body: &mut Function, write: bool) {
        // Only pre-root bootstrap and the final System-only postlude may use
        // the original single root stack. No active child gets this fallback.
        body.instruction(&Instruction::GlobalGet(self.lifecycle)).instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::GlobalGet(self.lifecycle)).instruction(&Instruction::I32Const(3))
            .instruction(&Instruction::I32Eq).instruction(&Instruction::I32Or)
            .instruction(&Instruction::Call(self.base.context_get)).instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::I32And)
            .instruction(&Instruction::If(BlockType::Empty));
        let pointer = if write { 0 } else { 1 };
        if !write { body.instruction(&Instruction::GlobalGet(self.base.stack_global)).instruction(&Instruction::LocalSet(pointer)); }
        body.instruction(&Instruction::LocalGet(pointer)).instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And); reject(body);
        body.instruction(&Instruction::LocalGet(pointer)).instruction(&Instruction::I32Const(self.low as i32))
            .instruction(&Instruction::I32LtU); reject(body);
        body.instruction(&Instruction::LocalGet(pointer)).instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32GtU); reject(body);
        if write {
            body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::GlobalSet(self.base.stack_global));
        } else { body.instruction(&Instruction::LocalGet(pointer)); }
        body.instruction(&Instruction::Return).instruction(&Instruction::End);
    }
}

struct RewriteRoot { plan: Root, next: u32, original: Option<Function> }
impl Reencode for RewriteRoot {
    type Error = &'static str;
    fn parse_global_section(&mut self, section: &mut GlobalSection,
            reader: wasmparser::GlobalSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_global_section(self, section, reader)?;
        section.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false }, &ConstExpr::i32_const(0));
        Ok(())
    }
    fn parse_function_section(&mut self, section: &mut FunctionSection,
            reader: wasmparser::FunctionSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, section, reader)?;
        section.function(self.plan.ty); Ok(())
    }
    fn parse_function_body(&mut self, code: &mut CodeSection,
            body: wasmparser::FunctionBody<'_>) -> Result<(), reencode::Error<Self::Error>> {
        let index = self.plan.base.imported_functions + self.next; self.next += 1;
        let mut function = self.new_function_with_parsed_locals(&body)?;
        if index == self.plan.get || index == self.plan.set {
            self.plan.bootstrap_stack_access(&mut function, index == self.plan.set);
        }
        let mut reader = body.get_operators_reader()?;
        while !reader.eof() { function.instruction(&self.instruction(reader.read()?)?); }
        if index == self.plan.root {
            self.original = Some(function); code.function(&self.plan.wrapper());
        } else { code.function(&function); }
        Ok(())
    }
    fn parse_code_section(&mut self, code: &mut CodeSection,
            reader: wasmparser::CodeSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, code, reader)?;
        code.function(self.original.as_ref().ok_or(reencode::Error::UserError("rust-root-body-missing"))?);
        Ok(())
    }
}

/// Wire one source-authenticated root, preserving its actual function index
/// and all numeric flat values. Support hooks and whole-component routing still
/// need their consuming sysroot qualification; receipts cannot enable the host.
pub fn transform_owned_root_bootstrap(input: &[u8], expected_preimage: [u8; 32], thread: &ThreadEntryReceipt)
    -> Result<(Vec<u8>, RootReceipt), &'static str>
{
    let original_digest = Sha256::digest(input).into();
    if original_digest != expected_preimage || original_digest != thread.stack.derived_digest {
        return Err("rust-root-thread-transform-preimage-mismatch");
    }
    let root = inspect(input, thread)?;
    let mut receipt = RootReceipt { original_digest, derived_digest: [0; 32], root_function: root.root,
        original_rust_body: root.cloned, bootstrap_function: root.boot, finish_function: root.finish,
        reap_function: root.reap, lifecycle_global: root.lifecycle,
        root_stack_low: root.low, root_stack_high: root.base.stack_initial,
        root_export_bootstrap_qualified: false, canonical_creation_enabled: false };
    let mut rewrite = RewriteRoot { plan: root, next: 0, original: None };
    let mut module = Module::new();
    rewrite.parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "rust-root-bootstrap-reencode-failed")?;
    let output = module.finish();
    if output.len() > MAX_BYTES { return Err("rust-stack-derived-module-byte-limit"); }
    Validator::new().validate_all(&output).map_err(|_| "rust-root-bootstrap-derived-module-invalid")?;
    receipt.derived_digest = Sha256::digest(&output).into();
    Ok((output, receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{ElementSection, Elements, EntityType, ExportKind, ExportSection,
        ImportSection, MemorySection, MemoryType, TableSection, TableType};

    fn fixture(low: bool, alias: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        types.ty().function([ValType::I32, ValType::I32], [ValType::I32]);
        types.ty().function([ValType::I64, ValType::I64, ValType::I32], []);
        types.ty().function([ValType::I32, ValType::I64], [ValType::I64, ValType::I32]);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", "[context-set-1]", EntityType::Function(1));
        imports.import("$root", "[thread-new-indirect-v0]", EntityType::Function(2));
        imports.import("latent:runtime-native/threads@0.1.0", "start", EntityType::Function(3));
        module.section(&imports);
        let mut functions = FunctionSection::new();
        for ty in [1, 4, 2, 1, 1] { functions.function(ty); }
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType { element_type: wasm_encoder::RefType::FUNCREF,
            table64: false, minimum: 1, maximum: Some(1), shared: false });
        module.section(&tables);
        let mut memory = MemorySection::new();
        memory.memory(MemoryType { minimum: 4, maximum: Some(4), memory64: false,
            shared: false, page_size_log2: None });
        module.section(&memory);
        let mut globals = GlobalSection::new();
        globals.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false },
            &ConstExpr::i32_const(131_072));
        globals.global(GlobalType { val_type: ValType::I32, mutable: false, shared: false },
            &ConstExpr::i32_const(65_536));
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        if low { exports.export("__stack_low", ExportKind::Global, 1); }
        exports.export("__indirect_function_table", ExportKind::Table, 0);
        exports.export("__lsf_rust_owned_thread_entry", ExportKind::Func, 4);
        for (name, index) in [(ROOT, 5), (BOOT, 6), (FINISH, 7), (REAP, if alias { 7 } else { 8 })] {
            exports.export(name, ExportKind::Func, index);
        }
        module.section(&exports);
        let mut elements = ElementSection::new();
        elements.active(Some(0), &ConstExpr::i32_const(0), Elements::Functions(Cow::Borrowed(&[4])));
        module.section(&elements);
        // These are encoded stand-ins for transform/routing checks, not Rust
        // hook execution. The separate native harness executes the TLS source.
        let mut code = CodeSection::new();
        let mut entry = Function::new([]); entry.instruction(&Instruction::End); code.function(&entry);
        let mut root = Function::new([]);
        root.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::Drop)
            .instruction(&Instruction::LocalGet(1)).instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::End); code.function(&root);
        let mut boot = Function::new([]); boot.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::End); code.function(&boot);
        for _ in 0..2 { let mut body = Function::new([]); body.instruction(&Instruction::End); code.function(&body); }
        module.section(&code);
        module.finish()
    }
    fn digest(input: &[u8]) -> [u8; 32] { Sha256::digest(input).into() }
    fn bodies(input: &[u8]) -> Vec<wasmparser::FunctionBody<'_>> {
        Parser::new(0).parse_all(input).filter_map(|payload| match payload.unwrap() {
            Payload::CodeSectionEntry(body) => Some(body), _ => None,
        }).collect()
    }

    #[test]
    fn root_attach_finish_detach_and_reap_preserve_original_index_and_numeric_values() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (output, receipt) = transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        assert_eq!((receipt.root_function, receipt.original_rust_body), (5, 12));
        assert_eq!((receipt.root_stack_low, receipt.root_stack_high), (65_536, 131_072));
        let bodies = bodies(&output);
        let mut reader = bodies[1].get_operators_reader().unwrap();
        let mut calls = Vec::new(); let mut writes = Vec::new();
        let mut results = Vec::new(); let mut loads = Vec::new();
        while !reader.eof() {
            match reader.read().unwrap() {
                Operator::Call { function_index } => calls.push(function_index),
                Operator::GlobalSet { global_index } => writes.push(global_index),
                Operator::LocalSet { local_index } => results.push(local_index),
                Operator::I32Load { memarg } => loads.push(memarg.offset),
                _ => {}
            }
        }
        assert_eq!(calls, [0, 6, 1, 12, 7, 0, 1, 8]);
        assert_eq!(writes, [2, 2, 2]);
        assert_eq!(results, [4, 3]); // reversed multi-result spill, restored in ABI order
        assert_eq!(loads, [12, 0, 4, 8, 12, 0, 8]);
        let root_type = Parser::new(0).parse_all(&output).find_map(|payload| match payload.unwrap() {
            Payload::TypeSection(types) => Some(types.into_iter_err_on_gc_types().nth(4).unwrap().unwrap()), _ => None,
        }).unwrap();
        assert_eq!(root_type.params(), [wasmparser::ValType::I32, wasmparser::ValType::I64]);
        assert_eq!(root_type.results(), [wasmparser::ValType::I64, wasmparser::ValType::I32]);
        Validator::new().validate_all(&output).unwrap();
        assert!(!receipt.root_export_bootstrap_qualified && !receipt.canonical_creation_enabled);
    }

    #[test]
    fn shared_stack_fallback_is_confined_to_pre_root_and_final_system_reaper() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (output, _) = transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        let bodies = bodies(&output);
        for index in [5, 6] { // defined helper indices9 and10, imported functions4
            let mut reader = bodies[index].get_operators_reader().unwrap();
            let mut prefix = Vec::new();
            for _ in 0..6 { prefix.push(format!("{:?}", reader.read().unwrap())); }
            assert_eq!(prefix, ["GlobalGet { global_index: 2 }", "I32Eqz", "GlobalGet { global_index: 2 }",
                "I32Const { value: 3 }", "I32Eq", "I32Or"]);
            let mut calls = Vec::new(); let mut returns = 0;
            while !reader.eof() { match reader.read().unwrap() {
                Operator::Call { function_index } => calls.push(function_index),
                Operator::Return => returns += 1,
                _ => {}
            }}
            assert_eq!(calls, [0, 0]); // fallback also requires a null canonical context
            assert_eq!(returns, 1);
        }
    }

    #[test]
    fn missing_linker_range_or_aliased_support_hooks_never_emit_bootstrap() {
        for (low, alias, expected) in [(false, false, "rust-root-linker-stack-low-missing"),
            (true, true, "rust-root-support-function-alias-denied")] {
            let input = fixture(low, alias);
            let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
            assert_eq!(transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(), expected);
        }
    }

    #[test]
    fn stale_chain_and_forged_stack_layout_receipts_are_rejected() {
        let input = fixture(true, false);
        let (threaded, mut thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        assert_eq!(transform_owned_root_bootstrap(&threaded, digest(&input), &thread).unwrap_err(),
            "rust-root-thread-transform-preimage-mismatch");
        thread.stack.original_initial_stack_pointer -= 16;
        assert_eq!(transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(),
            "rust-root-thread-receipt-layout");
        thread.stack.original_initial_stack_pointer += 16;
        thread.stack.helper_get_function = thread.entry_function;
        assert_eq!(transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(),
            "rust-root-thread-helper-body-mismatch");
    }

    #[test]
    fn root_and_child_admission_transform_chain_validates_without_enabling_component_threads() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (rooted, root) = transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        let (output, admission) = transform_owned_thread_admission(&rooted, digest(&rooted)).unwrap();
        assert_eq!(root.derived_digest, admission.original_digest);
        Validator::new().validate_all(&output).unwrap();
        assert!(!admission.component_routing_authenticated);
        assert!(!admission.canonical_creation_enabled);
        assert!(!root.root_export_bootstrap_qualified);
    }
}
