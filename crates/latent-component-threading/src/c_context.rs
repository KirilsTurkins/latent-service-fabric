//! Explicit C/LLVM21 source mechanism. No builder or engine selects this path.
//!
//! The authenticated linked input must retain TLS-base accesses (the ordinary
//! non-threaded target folds them into process data). Stack and TLS accesses
//! use the current canonical context; neither a shared mutable global nor a
//! process-wide current-thread variable is installed. Admission, bootstrap,
//! TLS template materialization and native retirement remain separate gates.
use super::*;

pub const C_CONTEXT_BYTES: u32 = 32;
const TLS_BASE: u64 = 12;
const TLS_BYTES: u64 = 16;
const PHASE: u64 = 20;
const RUNNING: i32 = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CContextReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub original_stack_global: u32,
    pub original_tls_global: u32,
    pub template_start: u32,
    /// The complete linked data tail is retained, including any ordinary data.
    /// This upper bound must be charged, never advertised as exact TLS usage.
    pub template_extent: u32,
    pub stack_gets: u64,
    pub stack_sets: u64,
    pub tls_gets: u64,
    pub canonical_context_import: u32,
    pub runtime_profile_qualified: bool,
    pub bootstrap_installed: bool,
    pub scheduling_checkpoints_installed: bool,
}

struct CPlan {
    base: Plan,
    tls_global: u32,
    template_start: u32,
    template_extent: u32,
}

fn inspect(input: &[u8]) -> Result<CPlan, &'static str> {
    let base = plan(input).map_err(|_| "c-context-linked-core-shape")?;
    // Atomic accesses require a separately reviewed compiler memory-model port.
    // An atomics-enabled target with no actual atomic instructions is valid.
    let features = wasmparser::WasmFeatures::default() & !wasmparser::WasmFeatures::THREADS;
    Validator::new_with_features(features)
        .validate_all(input)
        .map_err(|_| "c-context-atomic-or-shared-memory-not-supported")?;
    let mut globals = Vec::new();
    let mut tls = None;
    let mut end = None;
    let mut memory = None;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-context-malformed-core")? {
            Payload::GlobalSection(reader) => {
                for global in reader {
                    let global = global.map_err(|_| "c-context-global")?;
                    let mut ops = global.init_expr.get_operators_reader();
                    let value = match ops.read().map_err(|_| "c-context-global-initializer")? {
                        Operator::I32Const { value } => Some(value as u32),
                        _ => None,
                    };
                    // This C-only profile requires literal linker addresses.
                    // In particular, the original Rust plan's first operand
                    // must never stand in for an extended-constant SP value.
                    if value.is_some() && (!matches!(ops.read(), Ok(Operator::End)) || !ops.eof()) {
                        return Err("c-context-single-constant-global-initializer");
                    }
                    globals.push((global.ty, value));
                }
            }
            Payload::ExportSection(reader) => {
                for export in reader {
                    let export = export.map_err(|_| "c-context-export")?;
                    let slot = match export.name {
                        "__tls_base" => &mut tls,
                        "__data_end" => &mut end,
                        _ => continue,
                    };
                    if export.kind != ExternalKind::Global || slot.replace(export.index).is_some() {
                        return Err("c-context-layout-export");
                    }
                }
            }
            Payload::MemorySection(reader) => {
                for ty in reader {
                    let ty = ty.map_err(|_| "c-context-memory")?;
                    memory = Some((ty.initial, ty.maximum));
                }
            }
            Payload::StartSection { .. } => return Err("c-context-start-before-bootstrap"),
            _ => {}
        }
    }
    let tls_global = tls.ok_or("c-context-tls-base-export-missing")?;
    if tls_global == base.stack_global {
        return Err("c-context-stack-tls-alias");
    }
    let value = |index: u32| -> Result<u32, &'static str> {
        let (ty, value) = globals
            .get(index as usize)
            .ok_or("c-context-layout-global-index")?;
        if ty.content_type != wasmparser::ValType::I32 || ty.mutable || ty.shared {
            return Err("c-context-layout-global-must-be-immutable-i32");
        }
        value.ok_or("c-context-layout-global-must-be-constant")
    };
    let template_start = value(tls_global)?;
    let template_end = value(end.ok_or("c-context-data-end-export-missing")?)?;
    let template_extent = template_end
        .checked_sub(template_start)
        .filter(|n| *n > 0 && *n <= 1024 * 1024)
        .ok_or("c-context-template-extent")?;
    let (initial, maximum) = memory.ok_or("c-context-memory-missing")?;
    if maximum.is_none_or(|n| n > 1024 || n < initial) || u64::from(template_end) > initial * 65_536
    {
        return Err("c-context-template-or-memory-bound");
    }
    if template_start == 0 || template_start % 16 != 0 {
        return Err("c-context-template-alignment");
    }
    if base.function_count + base.imported_functions > MAX_FUNCTIONS - 1 {
        return Err("c-context-three-helper-function-limit");
    }
    Ok(CPlan {
        base,
        tls_global,
        template_start,
        template_extent,
    })
}

pub(super) fn original_template_layout(input: &[u8]) -> Result<(u32, u32), &'static str> {
    let plan = inspect(input)?;
    Ok((plan.template_start, plan.template_extent))
}

struct CRewrite {
    plan: CPlan,
    stack_gets: u64,
    stack_sets: u64,
    tls_gets: u64,
}

fn address(offset: u64) -> MemArg {
    MemArg {
        offset,
        align: 2,
        memory_index: 0,
    }
}
fn trap_if(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty))
        .instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}
fn checked_context(body: &mut Function, local: u32, get: u32) {
    body.instruction(&Instruction::Call(get))
        .instruction(&Instruction::LocalTee(local))
        .instruction(&Instruction::I32Eqz);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(local))
        .instruction(&Instruction::I32Const(15))
        .instruction(&Instruction::I32And);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(local))
        .instruction(&Instruction::I32Load(address(PHASE)))
        .instruction(&Instruction::I32Const(RUNNING))
        .instruction(&Instruction::I32Ne);
    trap_if(body);
}

fn memory_bytes(body: &mut Function) {
    body.instruction(&Instruction::MemorySize(0))
        .instruction(&Instruction::I64ExtendI32U)
        .instruction(&Instruction::I64Const(16))
        .instruction(&Instruction::I64Shl);
}
fn checked_stack(body: &mut Function, context: u32, pointer: u32) {
    // Bootstrap owns non-overlap and provenance. These checks retain finite
    // in-memory ranges and catch actual committed stack-pointer crossings.
    body.instruction(&Instruction::LocalGet(context))
        .instruction(&Instruction::I32Load(address(4)))
        .instruction(&Instruction::LocalGet(context))
        .instruction(&Instruction::I32Load(address(8)))
        .instruction(&Instruction::I32GeU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(context))
        .instruction(&Instruction::I32Load(address(8)))
        .instruction(&Instruction::I64ExtendI32U);
    memory_bytes(body);
    body.instruction(&Instruction::I64GtU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer))
        .instruction(&Instruction::I32Const(15))
        .instruction(&Instruction::I32And);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer))
        .instruction(&Instruction::LocalGet(context))
        .instruction(&Instruction::I32Load(address(4)))
        .instruction(&Instruction::I32LtU);
    trap_if(body);
    body.instruction(&Instruction::LocalGet(pointer))
        .instruction(&Instruction::LocalGet(context))
        .instruction(&Instruction::I32Load(address(8)))
        .instruction(&Instruction::I32GtU);
    trap_if(body);
}

impl CRewrite {
    fn first(&self) -> u32 {
        self.plan.base.imported_functions + self.plan.base.function_count
    }
    fn helpers(&self, code: &mut CodeSection) {
        // Every helper is stackless: no compiler prologue or external wait can
        // run between context lookup, validation and the actual memory access.
        let mut get = Function::new([(2, ValType::I32)]);
        checked_context(&mut get, 0, self.plan.base.context_get);
        get.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(address(0)))
            .instruction(&Instruction::LocalSet(1));
        checked_stack(&mut get, 0, 1);
        get.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::End);
        code.function(&get);
        let mut set = Function::new([(1, ValType::I32)]);
        checked_context(&mut set, 1, self.plan.base.context_get);
        checked_stack(&mut set, 1, 0);
        set.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Store(address(0)))
            .instruction(&Instruction::End);
        code.function(&set);
        let mut tls = Function::new([(2, ValType::I32)]);
        checked_context(&mut tls, 0, self.plan.base.context_get);
        tls.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(address(TLS_BYTES)))
            .instruction(&Instruction::I32Const(self.plan.template_extent as i32))
            .instruction(&Instruction::I32Ne);
        trap_if(&mut tls);
        tls.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(address(TLS_BASE)))
            .instruction(&Instruction::LocalTee(1))
            .instruction(&Instruction::I32Eqz);
        trap_if(&mut tls);
        tls.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And);
        trap_if(&mut tls);
        tls.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(i64::from(self.plan.template_extent)))
            .instruction(&Instruction::I64Add);
        memory_bytes(&mut tls);
        tls.instruction(&Instruction::I64GtU);
        trap_if(&mut tls);
        tls.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::End);
        code.function(&tls);
    }
}

impl Reencode for CRewrite {
    type Error = &'static str;
    fn parse_type_section(
        &mut self,
        section: &mut TypeSection,
        reader: wasmparser::TypeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_type_section(self, section, reader)?;
        section.ty().function([], [ValType::I32]);
        section.ty().function([ValType::I32], []);
        Ok(())
    }
    fn parse_function_section(
        &mut self,
        section: &mut FunctionSection,
        reader: wasmparser::FunctionSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, section, reader)?;
        section
            .function(self.plan.base.type_count)
            .function(self.plan.base.type_count + 1)
            .function(self.plan.base.type_count);
        Ok(())
    }
    fn parse_function_body(
        &mut self,
        code: &mut CodeSection,
        body: wasmparser::FunctionBody<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let mut function = self.new_function_with_parsed_locals(&body)?;
        let mut reader = body.get_operators_reader()?;
        while !reader.eof() {
            match reader.read()? {
                Operator::GlobalGet { global_index }
                    if global_index == self.plan.base.stack_global =>
                {
                    function.instruction(&Instruction::Call(self.first()));
                    self.stack_gets += 1;
                }
                Operator::GlobalSet { global_index }
                    if global_index == self.plan.base.stack_global =>
                {
                    function.instruction(&Instruction::Call(self.first() + 1));
                    self.stack_sets += 1;
                }
                Operator::GlobalGet { global_index } if global_index == self.plan.tls_global => {
                    function.instruction(&Instruction::Call(self.first() + 2));
                    self.tls_gets += 1;
                }
                Operator::GlobalSet { global_index } if global_index == self.plan.tls_global => {
                    return Err(reencode::Error::UserError("c-context-tls-base-mutation"));
                }
                op => {
                    function.instruction(&self.instruction(op)?);
                }
            }
        }
        code.function(&function);
        Ok(())
    }
    fn parse_code_section(
        &mut self,
        code: &mut CodeSection,
        reader: wasmparser::CodeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, code, reader)?;
        self.helpers(code);
        Ok(())
    }
}

/// Retain every original index and instruction except actual stack/TLS global
/// accesses. This source transform is never proof of a pthread/runtime port.
/// The caller must separately authenticate compiler lowering, TLS alignment,
/// pre-initializer bootstrap, allocation/ownership and the final component.
pub fn transform_c_context(
    input: &[u8],
    expected: [u8; 32],
) -> Result<(Vec<u8>, CContextReceipt), &'static str> {
    let original_digest: [u8; 32] = Sha256::digest(input).into();
    if original_digest != expected {
        return Err("c-context-preimage-mismatch");
    }
    let mut rewrite = CRewrite {
        plan: inspect(input)?,
        stack_gets: 0,
        stack_sets: 0,
        tls_gets: 0,
    };
    let mut module = Module::new();
    rewrite
        .parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "c-context-reencode")?;
    if rewrite.stack_gets == 0 || rewrite.tls_gets == 0 {
        return Err("c-context-compiler-lowering-missing");
    }
    let output = module.finish();
    if output.len() > MAX_BYTES {
        return Err("c-context-derived-byte-limit");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "c-context-derived-invalid")?;
    let receipt = CContextReceipt {
        original_digest,
        derived_digest: Sha256::digest(&output).into(),
        original_stack_global: rewrite.plan.base.stack_global,
        original_tls_global: rewrite.plan.tls_global,
        template_start: rewrite.plan.template_start,
        template_extent: rewrite.plan.template_extent,
        stack_gets: rewrite.stack_gets,
        stack_sets: rewrite.stack_sets,
        tls_gets: rewrite.tls_gets,
        canonical_context_import: rewrite.plan.base.context_get,
        runtime_profile_qualified: false,
        bootstrap_installed: false,
        scheduling_checkpoints_installed: false,
    };
    Ok((output, receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_encoder::{
        ConstExpr, EntityType, ExportKind, ExportSection, GlobalSection, GlobalType, ImportSection,
        MemorySection, MemoryType,
    };

    fn fixture_with_global(
        tls_access: bool,
        tls_export: bool,
        tls_mutable: bool,
        shared: bool,
        extended: Option<usize>,
    ) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32], [ValType::I32]);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        module.section(&imports);
        let mut functions = FunctionSection::new();
        functions.function(1);
        module.section(&functions);
        let mut memory = MemorySection::new();
        memory.memory(MemoryType {
            minimum: 4,
            maximum: Some(4),
            memory64: false,
            shared,
            page_size_log2: None,
        });
        module.section(&memory);
        let mut globals = GlobalSection::new();
        for (index, (value, mutable)) in [(65536, true), (65536, tls_mutable), (65584, false)]
            .into_iter()
            .enumerate()
        {
            let initializer = if extended == Some(index) {
                ConstExpr::extended([
                    Instruction::I32Const(value),
                    Instruction::I32Const(16),
                    Instruction::I32Add,
                ])
            } else {
                ConstExpr::i32_const(value)
            };
            globals.global(
                GlobalType {
                    val_type: ValType::I32,
                    mutable,
                    shared: false,
                },
                &initializer,
            );
        }
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("memory", ExportKind::Memory, 0);
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export(
            if tls_export { "__tls_base" } else { "other" },
            ExportKind::Global,
            1,
        );
        exports.export("__data_end", ExportKind::Global, 2);
        exports.export("probe", ExportKind::Func, 1);
        module.section(&exports);
        let mut code = CodeSection::new();
        let mut body = Function::new([]);
        body.instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Sub)
            .instruction(&Instruction::GlobalSet(0));
        if tls_access {
            body.instruction(&Instruction::GlobalGet(1));
        } else {
            body.instruction(&Instruction::I32Const(65536));
        }
        body.instruction(&Instruction::I32Load(address(0)))
            .instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::GlobalSet(0))
            .instruction(&Instruction::End);
        code.function(&body);
        module.section(&code);
        module.finish()
    }
    fn fixture(tls_access: bool, tls_export: bool, tls_mutable: bool, shared: bool) -> Vec<u8> {
        fixture_with_global(tls_access, tls_export, tls_mutable, shared, None)
    }
    fn run(raw: &[u8]) -> Result<(Vec<u8>, CContextReceipt), &'static str> {
        transform_c_context(raw, Sha256::digest(raw).into())
    }

    #[test]
    fn actual_stack_and_tls_accesses_are_replaced_without_a_runtime_claim() {
        let raw = fixture(true, true, false, false);
        let (output, r) = run(&raw).unwrap();
        assert_ne!(raw, output);
        assert_eq!((r.stack_gets, r.stack_sets, r.tls_gets), (2, 2, 1));
        assert_eq!((r.template_start, r.template_extent), (65536, 48));
        assert!(
            !r.runtime_profile_qualified
                && !r.bootstrap_installed
                && !r.scheduling_checkpoints_installed
        );
        Validator::new().validate_all(&output).unwrap();
        let mut original = true;
        for payload in Parser::new(0).parse_all(&output) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                if original {
                    let mut ops = body.get_operators_reader().unwrap();
                    let mut calls = Vec::new();
                    while !ops.eof() {
                        match ops.read().unwrap() {
                            Operator::Call { function_index } => calls.push(function_index),
                            Operator::GlobalGet { .. } | Operator::GlobalSet { .. } => {
                                panic!("shared context access")
                            }
                            _ => {}
                        }
                    }
                    assert_eq!(calls, [2, 3, 4, 2, 3]);
                    original = false;
                }
            }
        }
        assert!(!original);
    }
    #[test]
    fn ordinary_static_tls_lowering_is_concretely_refused() {
        assert_eq!(
            run(&fixture(false, true, false, false)).unwrap_err(),
            "c-context-compiler-lowering-missing"
        );
    }
    #[test]
    fn missing_or_mutable_tls_layout_is_never_a_global_fallback() {
        assert_eq!(
            run(&fixture(true, false, false, false)).unwrap_err(),
            "c-context-tls-base-export-missing"
        );
        assert_eq!(
            run(&fixture(true, true, true, false)).unwrap_err(),
            "c-context-layout-global-must-be-immutable-i32"
        );
    }
    #[test]
    fn shared_parallel_memory_cannot_select_the_cooperative_mechanism() {
        assert_eq!(
            run(&fixture(true, true, false, true)).unwrap_err(),
            "c-context-linked-core-shape"
        );
    }
    #[test]
    fn stale_preimage_is_rejected_before_shape_or_rewrite() {
        let raw = fixture(true, true, false, false);
        assert_eq!(
            transform_c_context(&raw, [0; 32]).unwrap_err(),
            "c-context-preimage-mismatch"
        );
    }
    #[test]
    fn c_linker_layout_never_trusts_the_first_operand_of_an_extended_global() {
        for index in 0..3 {
            let raw = fixture_with_global(true, true, false, false, Some(index));
            Validator::new().validate_all(&raw).unwrap();
            // Keep the old Rust routing/profile unchanged; strictness belongs
            // to the independently selected C layout inspector.
            assert!(plan(&raw).is_ok());
            assert_eq!(
                run(&raw).unwrap_err(),
                "c-context-single-constant-global-initializer"
            );
        }
    }
    #[test]
    fn helper_calls_are_only_stackless_context_lookup_and_original_imports_stay_exact() {
        let raw = fixture(true, true, false, false);
        let (output, _) = run(&raw).unwrap();
        let mut bodies = 0;
        for payload in Parser::new(0).parse_all(&output) {
            match payload.unwrap() {
                Payload::ImportSection(reader) => {
                    assert_eq!(reader.count(), 1);
                    for import in reader.into_imports() {
                        let import = import.unwrap();
                        assert_eq!((import.module, import.name), ("$root", "[context-get-1]"));
                    }
                }
                Payload::CodeSectionEntry(body) => {
                    bodies += 1;
                    if bodies > 1 {
                        let mut ops = body.get_operators_reader().unwrap();
                        while !ops.eof() {
                            match ops.read().unwrap() {
                                Operator::Call { function_index } => assert_eq!(function_index, 0),
                                Operator::GlobalGet { .. }
                                | Operator::GlobalSet { .. }
                                | Operator::MemoryGrow { .. } => panic!("helper is not stackless"),
                                _ => {}
                            }
                        }
                    }
                }
                _ => {}
            }
        }
        assert_eq!(bodies, 4);
    }
}
