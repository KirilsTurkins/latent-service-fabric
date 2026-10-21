//! C-only guarded root bootstrap. This core source proof never enables a
//! component or claims scheduler, checkpoint, constructor or I/O support.
use super::*;
use wasm_encoder::{ConstExpr, ExportSection, GlobalSection, GlobalType};

const INITIALIZE: &str = "__lsf_c_root_initialize";
const FINISH: &str = "__lsf_c_root_finish";
const CTORS: &str = "__wasm_call_ctors";
const RECORD: i32 = 16;
const RECORD_BYTES: i32 = 144;
const GUARD_BYTES: u32 = 4096;
const STACK_HIGH: u32 = GUARD_BYTES + 65_536;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CRootReceipt {
    pub original_digest: [u8; 32],
    pub template: c_template::CTemplateReceipt,
    pub child: c_lifecycle::CThreadLifecycleReceipt,
    pub derived_digest: [u8; 32],
    pub original_root_function: u32,
    pub root_wrapper_function: u32,
    pub root_record_pointer: u32,
    pub root_record_bytes: u32,
    pub root_stack_low: u32,
    pub root_stack_high: u32,
    pub root_context_installed_before_c_prologue: bool,
    pub original_constructor_body_is_empty: bool,
    pub root_owners_retained_until_store_drop: bool,
    pub component_routing_authenticated: bool,
    pub runtime_profile_qualified: bool,
}

struct Root {
    base: Plan,
    export: String,
    original: u32,
    ty: u32,
    params: Vec<ValType>,
    results: Vec<ValType>,
    initialize: u32,
    finish: u32,
    context_set: u32,
    lifecycle: u32,
    wrapper: u32,
    template_start: u32,
    template_extent: u32,
}

fn numeric(value: wasmparser::ValType) -> Result<ValType, &'static str> {
    Ok(match value {
        wasmparser::ValType::I32 => ValType::I32,
        wasmparser::ValType::I64 => ValType::I64,
        wasmparser::ValType::F32 => ValType::F32,
        wasmparser::ValType::F64 => ValType::F64,
        _ => return Err("c-root-numeric-flat-abi-only"),
    })
}

fn inspect(input: &[u8], export: &str, start: u32, extent: u32) -> Result<Root, &'static str> {
    if export.is_empty() || export.len() > 256 || export.starts_with("__lsf_") {
        return Err("c-root-explicit-public-export-name");
    }
    let base = plan(input)?;
    if base.stack_initial != STACK_HIGH
        || start < STACK_HIGH
        || base.imported_functions + base.function_count >= MAX_FUNCTIONS
    {
        return Err("c-root-exact-guard-and-usable-stack-layout");
    }
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut globals = Vec::new();
    let mut exports = std::collections::BTreeMap::new();
    let mut context_set = None;
    let mut imported = 0;
    let mut code = base.imported_functions;
    let mut empty_ctors = false;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-root-core-parse")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "c-root-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for row in reader.into_imports() {
                    let row = row.map_err(|_| "c-root-import")?;
                    if let TypeRef::Func(ty) | TypeRef::FuncExact(ty) = row.ty {
                        if row.module == "$root" && row.name == "[context-set-1]" {
                            let ty = types.get(ty as usize).ok_or("c-root-context-set-type")?;
                            if context_set.replace(imported).is_some()
                                || ty.params() != [wasmparser::ValType::I32]
                                || !ty.results().is_empty()
                            {
                                return Err("c-root-context-set-signature");
                            }
                        }
                        imported += 1;
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    functions.push(ty.map_err(|_| "c-root-function-type")?);
                }
            }
            Payload::GlobalSection(reader) => {
                for global in reader {
                    let global = global.map_err(|_| "c-root-global")?;
                    let mut ops = global.init_expr.get_operators_reader();
                    let value = match ops.read().map_err(|_| "c-root-global-init")? {
                        Operator::I32Const { value } => Some(value as u32),
                        _ => None,
                    };
                    if value.is_some() && (!matches!(ops.read(), Ok(Operator::End)) || !ops.eof()) {
                        return Err("c-root-single-constant-global-initializer");
                    }
                    globals.push((global.ty, value));
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-root-export")?;
                    if [
                        export,
                        INITIALIZE,
                        FINISH,
                        CTORS,
                        "__heap_base",
                        "__stack_low",
                    ]
                    .contains(&row.name)
                        && exports.insert(row.name, (row.kind, row.index)).is_some()
                    {
                        return Err("c-root-duplicate-reserved-export");
                    }
                    // A separate reactor initializer would otherwise run
                    // ordinary C before this selected public root wrapper.
                    if row.name == "_initialize" {
                        return Err("c-root-separate-reactor-initializer-not-qualified");
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                if exports.get(CTORS) == Some(&(ExternalKind::Func, code)) {
                    let mut ops = body
                        .get_operators_reader()
                        .map_err(|_| "c-root-ctor-code")?;
                    empty_ctors = body
                        .get_locals_reader()
                        .map_err(|_| "c-root-ctor-locals")?
                        .get_count()
                        == 0
                        && matches!(ops.read(), Ok(Operator::End))
                        && ops.eof();
                }
                code += 1;
            }
            Payload::DataSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-root-data")?;
                    if let wasmparser::DataKind::Active {
                        memory_index,
                        offset_expr,
                    } = row.kind
                    {
                        if memory_index != 0 {
                            return Err("c-root-active-memory-index");
                        }
                        let mut ops = offset_expr.get_operators_reader();
                        let begin = match ops.read().map_err(|_| "c-root-data-offset")? {
                            Operator::I32Const { value } => value as u32,
                            _ => return Err("c-root-active-offset-not-constant"),
                        };
                        if !matches!(ops.read(), Ok(Operator::End)) || !ops.eof() {
                            return Err("c-root-single-constant-active-offset");
                        }
                        if !row.data.is_empty() && begin < STACK_HIGH {
                            return Err("c-root-original-active-data-overlaps-guard-or-stack");
                        }
                    }
                }
            }
            Payload::StartSection { .. } => return Err("c-root-start-before-bootstrap"),
            _ => {}
        }
    }
    let function = |name: &str| -> Result<(u32, u32, &wasmparser::FuncType), &'static str> {
        let (kind, index) = *exports.get(name).ok_or("c-root-required-export-missing")?;
        if kind != ExternalKind::Func {
            return Err("c-root-required-function-export");
        }
        let defined = index
            .checked_sub(imported)
            .ok_or("c-root-defined-support-only")?;
        let ty = *functions
            .get(defined as usize)
            .ok_or("c-root-function-index")?;
        Ok((
            index,
            ty,
            types.get(ty as usize).ok_or("c-root-type-index")?,
        ))
    };
    let (original, ty, root) = function(export)?;
    let (initialize, _, init) = function(INITIALIZE)?;
    let (finish, _, done) = function(FINISH)?;
    let (ctors, _, ctor) = function(CTORS)?;
    if init.params() != [wasmparser::ValType::I32; 2]
        || init.results() != [wasmparser::ValType::I32]
        || done.params() != [wasmparser::ValType::I32]
        || !done.results().is_empty()
        || !ctor.params().is_empty()
        || !ctor.results().is_empty()
        || !empty_ctors
        || root.params().len() > 16
        || root.results().len() > 16
        || [original, initialize, finish, ctors]
            .into_iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != 4
    {
        return Err("c-root-support-signature-alias-or-constructor");
    }
    let constant = |name: &str| -> Result<u32, &'static str> {
        let (kind, index) = *exports.get(name).ok_or("c-root-linker-global-missing")?;
        let (ty, value) = globals
            .get(index as usize)
            .ok_or("c-root-linker-global-index")?;
        if kind != ExternalKind::Global
            || ty.mutable
            || ty.shared
            || ty.content_type != wasmparser::ValType::I32
        {
            return Err("c-root-linker-global-constant-type");
        }
        value.ok_or("c-root-linker-global-constant")
    };
    if constant("__stack_low")? != 0
        || constant("__heap_base")?
            < start
                .checked_add(extent)
                .ok_or("c-root-template-overflow")?
        || globals.len() >= MAX_FUNCTIONS as usize
    {
        return Err("c-root-original-stack-tls-heap-overlap");
    }
    Ok(Root {
        wrapper: imported + base.function_count,
        base,
        export: export.to_owned(),
        original,
        ty,
        params: root
            .params()
            .iter()
            .copied()
            .map(numeric)
            .collect::<Result<_, _>>()?,
        results: root
            .results()
            .iter()
            .copied()
            .map(numeric)
            .collect::<Result<_, _>>()?,
        initialize,
        finish,
        context_set: context_set.ok_or("c-root-context-set-missing")?,
        lifecycle: globals.len() as u32,
        template_start: start,
        template_extent: extent,
    })
}

fn address(offset: u64) -> MemArg {
    MemArg {
        offset,
        align: 2,
        memory_index: 0,
    }
}
fn reject(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty))
        .instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}
impl Root {
    fn wrapper(&self) -> Function {
        let mut body = Function::new(self.results.iter().map(|value| (1, *value)));
        body.instruction(&Instruction::GlobalGet(self.lifecycle));
        reject(&mut body);
        body.instruction(&Instruction::Call(self.base.context_get));
        reject(&mut body);
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(STACK_HIGH as i32))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        // All memory and overlap bounds were proved from the final original
        // core. Memory cannot shrink; these constant writes precede all C.
        body.instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::I32Const(RECORD_BYTES))
            .instruction(&Instruction::MemoryFill(0));
        for (offset, value) in [
            (0, STACK_HIGH),
            (4, GUARD_BYTES),
            (8, STACK_HIGH),
            (12, self.template_start),
            (16, self.template_extent),
            (20, 2),
        ] {
            body.instruction(&Instruction::I32Const(RECORD))
                .instruction(&Instruction::I32Const(value as i32))
                .instruction(&Instruction::I32Store(address(offset)));
        }
        body.instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::GlobalSet(self.lifecycle))
            .instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::I32Const(self.template_extent as i32))
            .instruction(&Instruction::Call(self.initialize));
        reject(&mut body);
        for index in 0..self.params.len() as u32 {
            body.instruction(&Instruction::LocalGet(index));
        }
        body.instruction(&Instruction::Call(self.original));
        for index in (0..self.results.len() as u32).rev() {
            body.instruction(&Instruction::LocalSet(self.params.len() as u32 + index));
        }
        body.instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::Call(self.finish))
            .instruction(&Instruction::Call(self.base.context_get))
            .instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        for (offset, value) in [(0, STACK_HIGH), (20, 2)] {
            body.instruction(&Instruction::I32Const(RECORD))
                .instruction(&Instruction::I32Load(address(offset)))
                .instruction(&Instruction::I32Const(value as i32))
                .instruction(&Instruction::I32Ne);
            reject(&mut body);
        }
        body.instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::I32Load8U(MemArg {
                offset: 83,
                align: 0,
                memory_index: 0,
            }))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        body.instruction(&Instruction::I32Const(RECORD))
            .instruction(&Instruction::I32Const(5))
            .instruction(&Instruction::I32Store(address(20)))
            .instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::GlobalSet(self.lifecycle));
        // No C, allocator, destructor or host call can run after detach.
        for index in 0..self.results.len() as u32 {
            body.instruction(&Instruction::LocalGet(self.params.len() as u32 + index));
        }
        body.instruction(&Instruction::End);
        body
    }
}

impl Reencode for Root {
    type Error = &'static str;
    fn parse_function_section(
        &mut self,
        out: &mut FunctionSection,
        reader: wasmparser::FunctionSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, out, reader)?;
        out.function(self.ty);
        Ok(())
    }
    fn parse_global_section(
        &mut self,
        out: &mut GlobalSection,
        reader: wasmparser::GlobalSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_global_section(self, out, reader)?;
        out.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(0),
        );
        Ok(())
    }
    fn parse_export_section(
        &mut self,
        out: &mut ExportSection,
        reader: wasmparser::ExportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        for row in reader {
            let row = row.map_err(|_| reencode::Error::UserError("c-root-export-reencode"))?;
            out.export(
                row.name,
                self.export_kind(row.kind)?,
                if row.name == self.export {
                    self.wrapper
                } else {
                    row.index
                },
            );
        }
        Ok(())
    }
    fn parse_code_section(
        &mut self,
        out: &mut CodeSection,
        reader: wasmparser::CodeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, out, reader)?;
        out.function(&self.wrapper());
        Ok(())
    }
}

#[derive(PartialEq, Eq)]
struct Bytes {
    sections: Vec<(u8, Vec<u8>)>,
    bodies: Vec<Vec<u8>>,
    functions: Vec<u32>,
    globals: Vec<(wasmparser::GlobalType, Vec<u8>)>,
    exports: Vec<(String, ExternalKind, u32)>,
}

fn checked_bytes(input: &[u8], range: std::ops::Range<u64>) -> Result<Vec<u8>, &'static str> {
    let begin = usize::try_from(range.start).map_err(|_| "c-root-byte-range-start")?;
    let end = usize::try_from(range.end).map_err(|_| "c-root-byte-range-end")?;
    Ok(input.get(begin..end).ok_or("c-root-byte-range")?.to_vec())
}

fn snapshot(input: &[u8]) -> Result<Bytes, &'static str> {
    let mut bytes = Bytes {
        sections: Vec::new(),
        bodies: Vec::new(),
        functions: Vec::new(),
        globals: Vec::new(),
        exports: Vec::new(),
    };
    for payload in Parser::new(0).parse_all(input) {
        let payload = payload.map_err(|_| "c-root-snapshot-parse")?;
        if let Some((id, range)) = payload.as_section()
            && ![3, 6, 7, 10].contains(&id)
        {
            bytes.sections.push((id, checked_bytes(input, range)?));
        }
        match payload {
            Payload::CodeSectionEntry(body) => {
                bytes.bodies.push(checked_bytes(input, body.range())?)
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    bytes
                        .functions
                        .push(ty.map_err(|_| "c-root-snapshot-function")?);
                }
            }
            Payload::GlobalSection(reader) => {
                for global in reader {
                    let global = global.map_err(|_| "c-root-snapshot-global")?;
                    bytes.globals.push((
                        global.ty,
                        checked_bytes(input, global.init_expr.get_binary_reader().range())?,
                    ));
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-root-snapshot-export")?;
                    bytes
                        .exports
                        .push((row.name.to_owned(), row.kind, row.index));
                }
            }
            _ => {}
        }
    }
    Ok(bytes)
}

fn verify(input: &[u8], output: &[u8], root: &Root) -> Result<(), &'static str> {
    let mut old = snapshot(input)?;
    let new = snapshot(output)?;
    old.bodies.push(root.wrapper().into_raw_body());
    old.functions.push(root.ty);
    old.globals.push((
        wasmparser::GlobalType {
            content_type: wasmparser::ValType::I32,
            mutable: true,
            shared: false,
        },
        vec![0x41, 0, 0x0b],
    ));
    for (name, _, index) in &mut old.exports {
        if name == &root.export {
            *index = root.wrapper;
        }
    }
    if old != new {
        return Err("c-root-original-remainder-or-fixed-wrapper-changed");
    }
    let mut index = root.base.imported_functions;
    let mut wrappers = 0;
    let mut lifecycle_uses = 0;
    for payload in Parser::new(0).parse_all(output) {
        match payload.map_err(|_| "c-root-proof-parse")? {
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-root-proof-export")?;
                    if row.name == root.export
                        && (row.kind != ExternalKind::Func || row.index != root.wrapper)
                    {
                        return Err("c-root-proof-public-route");
                    }
                    if row.kind == ExternalKind::Global && row.index == root.lifecycle {
                        return Err("c-root-proof-lifecycle-exported");
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                if index == root.wrapper {
                    if checked_bytes(output, body.range())? != root.wrapper().into_raw_body() {
                        return Err("c-root-proof-fixed-wrapper");
                    }
                    wrappers += 1;
                }
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "c-root-proof-code")?;
                while !ops.eof() {
                    if matches!(ops.read().map_err(|_| "c-root-proof-operator")?,
                        Operator::GlobalGet { global_index } | Operator::GlobalSet { global_index }
                            if global_index == root.lifecycle)
                    {
                        if index != root.wrapper {
                            return Err("c-root-proof-lifecycle-escaped");
                        }
                        lifecycle_uses += 1;
                    }
                }
                index += 1;
            }
            _ => {}
        }
    }
    if wrappers != 1 || lifecycle_uses != 3 {
        return Err("c-root-proof-fixed-wrapper-count");
    }
    Ok(())
}

/// Compile-source mechanism only. The entire derivation is recomputed from
/// one authenticated original; caller-authored partial receipts cannot select
/// a root. Whole-component routing and an actual runtime remain separate gates.
pub fn transform_c_root_bootstrap(
    input: &[u8],
    expected: [u8; 32],
    export: &str,
) -> Result<(Vec<u8>, CRootReceipt), &'static str> {
    let (template_core, template) = c_template::transform_c_initial_template(input, expected)?;
    let (child_core, child) = c_lifecycle::transform_c_owned_lifecycle(
        &template_core,
        Sha256::digest(&template_core).into(),
    )?;
    let mut root = inspect(
        &child_core,
        export,
        template.original_template_start,
        template.conservative_template_extent,
    )?;
    let mut module = Module::new();
    root.parse_core_module(&mut module, Parser::new(0), &child_core)
        .map_err(|_| "c-root-reencode")?;
    let output = module.finish();
    if output.len() > MAX_BYTES {
        return Err("c-root-derived-byte-bound");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "c-root-derived-invalid")?;
    verify(&child_core, &output, &root)?;
    let derived_digest = Sha256::digest(&output).into();
    Ok((
        output,
        CRootReceipt {
            original_digest: expected,
            template,
            child,
            derived_digest,
            original_root_function: root.original,
            root_wrapper_function: root.wrapper,
            root_record_pointer: RECORD as u32,
            root_record_bytes: RECORD_BYTES as u32,
            root_stack_low: GUARD_BYTES,
            root_stack_high: STACK_HIGH,
            root_context_installed_before_c_prologue: true,
            original_constructor_body_is_empty: true,
            root_owners_retained_until_store_drop: true,
            component_routing_authenticated: false,
            runtime_profile_qualified: false,
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        DataSection, ElementSection, Elements, EntityType, ExportKind, ImportSection,
        MemorySection, MemoryType, RefType, TableSection, TableType,
    };

    fn fixture(stack_high: i32, low_data: bool, constructors: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32; 2], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        types.ty().function([ValType::I32], [ValType::I64]);
        types.ty().function([], []);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", "[thread-new-indirect-v0]", EntityType::Function(1));
        module.section(&imports);
        let mut functions = FunctionSection::new();
        for ty in [2, 2, 1, 2, 1, 2, 3, 4] {
            functions.function(ty);
        }
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType {
            element_type: RefType::FUNCREF,
            minimum: 3,
            maximum: Some(3),
            table64: false,
            shared: false,
        });
        module.section(&tables);
        let mut memories = MemorySection::new();
        memories.memory(MemoryType {
            minimum: 4,
            maximum: Some(4),
            memory64: false,
            shared: false,
            page_size_log2: None,
        });
        module.section(&memories);
        let mut globals = GlobalSection::new();
        for (value, mutable) in [
            (stack_high, true),
            (131072, false),
            (131104, false),
            (0, false),
            (131104, false),
        ] {
            globals.global(
                GlobalType {
                    val_type: ValType::I32,
                    mutable,
                    shared: false,
                },
                &ConstExpr::i32_const(value),
            );
        }
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("memory", ExportKind::Memory, 0);
        for (name, index) in [
            ("__stack_pointer", 0),
            ("__tls_base", 1),
            ("__data_end", 2),
            ("__stack_low", 3),
            ("__heap_base", 4),
        ] {
            exports.export(name, ExportKind::Global, index);
        }
        exports.export("__indirect_function_table", ExportKind::Table, 0);
        for (name, index) in [
            ("__lsf_c_owned_thread_entry", 2),
            ("__lsf_c_thread_body", 3),
            ("__lsf_c_template_copy", 5),
            (INITIALIZE, 6),
            (FINISH, 7),
            ("run", 8),
            (CTORS, 9),
        ] {
            exports.export(name, ExportKind::Func, index);
        }
        module.section(&exports);
        let mut elements = ElementSection::new();
        elements.active(
            Some(0),
            &ConstExpr::i32_const(1),
            Elements::Functions(Cow::Owned(vec![2, 1])),
        );
        module.section(&elements);
        let mut code = CodeSection::new();
        let refusing = || {
            let mut function = Function::new([]);
            function
                .instruction(&Instruction::Unreachable)
                .instruction(&Instruction::End);
            function
        };
        code.function(&refusing());
        let mut body = Function::new([]);
        body.instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::GlobalGet(1))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::End);
        code.function(&body);
        let mut create = Function::new([]);
        create
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Call(1))
            .instruction(&Instruction::End);
        code.function(&create);
        code.function(&refusing());
        let mut init = Function::new([]);
        init.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::End);
        code.function(&init);
        let mut finish = Function::new([]);
        finish
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Store8(MemArg {
                offset: 83,
                align: 0,
                memory_index: 0,
            }))
            .instruction(&Instruction::End);
        code.function(&finish);
        let mut run = Function::new([]);
        run.instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::GlobalGet(1))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::End);
        code.function(&run);
        let mut ctor = Function::new([]);
        if constructors {
            ctor.instruction(&Instruction::Nop);
        }
        ctor.instruction(&Instruction::End);
        code.function(&ctor);
        module.section(&code);
        let mut data = DataSection::new();
        data.active(
            0,
            &ConstExpr::i32_const(if low_data { RECORD } else { 131072 }),
            [7],
        );
        module.section(&data);
        module.finish()
    }

    fn stages(input: &[u8]) -> (Vec<u8>, c_template::CTemplateReceipt) {
        let (template, receipt) =
            c_template::transform_c_initial_template(input, Sha256::digest(input).into()).unwrap();
        let (child, _) =
            c_lifecycle::transform_c_owned_lifecycle(&template, Sha256::digest(&template).into())
                .unwrap();
        (child, receipt)
    }

    #[test]
    fn guarded_root_chain_preserves_original_bodies_and_never_enables_a_component() {
        let input = fixture(STACK_HIGH as i32, false, false);
        let (output, receipt) =
            transform_c_root_bootstrap(&input, Sha256::digest(&input).into(), "run").unwrap();
        assert_eq!(
            (receipt.root_record_pointer, receipt.root_record_bytes),
            (16, 144)
        );
        assert_eq!(receipt.root_stack_high - receipt.root_stack_low, 65_536);
        assert!(
            receipt.root_context_installed_before_c_prologue
                && receipt.original_constructor_body_is_empty
                && receipt.root_owners_retained_until_store_drop
        );
        assert!(!receipt.component_routing_authenticated && !receipt.runtime_profile_qualified);
        let (child, template) = stages(&input);
        let root = inspect(
            &child,
            "run",
            template.original_template_start,
            template.conservative_template_extent,
        )
        .unwrap();
        verify(&child, &output, &root).unwrap();
    }

    #[test]
    fn original_stack_data_and_constructor_conflicts_fail_before_root_selection() {
        for (stack, low_data, constructors, expected) in [
            (
                65536,
                false,
                false,
                "c-root-exact-guard-and-usable-stack-layout",
            ),
            (
                STACK_HIGH as i32,
                true,
                false,
                "c-root-original-active-data-overlaps-guard-or-stack",
            ),
            (
                STACK_HIGH as i32,
                false,
                true,
                "c-root-support-signature-alias-or-constructor",
            ),
        ] {
            let input = fixture(stack, low_data, constructors);
            assert_eq!(
                transform_c_root_bootstrap(&input, Sha256::digest(&input).into(), "run")
                    .unwrap_err(),
                expected
            );
        }
    }

    #[test]
    fn changed_original_body_is_not_covered_by_a_fixed_root_wrapper_proof() {
        let input = fixture(STACK_HIGH as i32, false, false);
        let (mut output, _) =
            transform_c_root_bootstrap(&input, Sha256::digest(&input).into(), "run").unwrap();
        let (child, template) = stages(&input);
        let root = inspect(
            &child,
            "run",
            template.original_template_start,
            template.conservative_template_extent,
        )
        .unwrap();
        let mut index = root.base.imported_functions;
        let mut at = None;
        for payload in Parser::new(0).parse_all(&output) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                if index == root.original {
                    at = Some(body.range().start as usize + 2);
                }
                index += 1;
            }
        }
        output[at.unwrap()] ^= 1;
        assert_eq!(
            verify(&child, &output, &root).unwrap_err(),
            "c-root-original-remainder-or-fixed-wrapper-changed"
        );
    }

    #[test]
    fn root_chain_requires_one_original_preimage_and_an_explicit_public_export() {
        let input = fixture(STACK_HIGH as i32, false, false);
        assert_eq!(
            transform_c_root_bootstrap(&input, [0; 32], "run").unwrap_err(),
            "c-template-original-preimage-mismatch"
        );
        assert_eq!(
            transform_c_root_bootstrap(
                &input,
                Sha256::digest(&input).into(),
                "__lsf_c_thread_body"
            )
            .unwrap_err(),
            "c-root-explicit-public-export-name"
        );
    }
}
