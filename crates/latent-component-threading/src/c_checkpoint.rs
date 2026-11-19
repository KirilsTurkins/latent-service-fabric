//! Narrow, opt-in C root-loop checkpoint source derivation.
//!
//! This is not a host profile or a component authentication. The caller must
//! separately admit the verification work, retain the original linked core,
//! recompute the complete derivation and authenticate canonical routing. V1
//! derivations never call this module. The selected body is deliberately
//! call-free and read-only, so it cannot qualify a pthread worker, mutex loop,
//! non-suspendable SDK state, or the required real-engine sibling progress.
use super::*;
use wasmparser::{ElementItems, ElementKind, WasmFeatures};

// Reserve ample room under the existing 64K derived-operator ceiling for the
// existing stack/TLS/bootstrap wrappers. The new pass itself adds four scalar
// operators per selected loop and does not add locals, stacks, or owners.
const INPUT_OPERATOR_LIMIT: u64 = 48 * 1024;
const TARGET_OPERATOR_LIMIT: u64 = 4096;
const MAX_CHECKPOINTS: u32 = 256;
const SYSTEM_STACK_HIGH: u32 = c_root::SYSTEM_STACK_HIGH;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CCheckpointReceipt {
    pub original_digest: [u8; 32],
    pub checkpoint_core_digest: [u8; 32],
    pub public_wrapper: u32,
    pub application_function: u32,
    pub canonical_yield_import: u32,
    pub inserted_checkpoints: u32,
    /// Loop entries invoke the existing intrinsic even with no runnable child.
    pub lazy_no_concurrency_qualified: bool,
    pub actual_engine_qualified: bool,
}

#[derive(Clone, Copy)]
struct Sig {
    wrapper: bool,
    application: bool,
    yield_import: bool,
}

fn signature(ty: &wasmparser::FuncType) -> Sig {
    use wasmparser::ValType::I32;
    Sig {
        wrapper: ty.params() == [I32, I32] && ty.results() == [I32],
        application: ty.params() == [I32, I32, I32] && ty.results() == [I32],
        yield_import: ty.params().is_empty() && ty.results() == [I32],
    }
}

fn single_i32(expr: wasmparser::ConstExpr<'_>) -> Option<u32> {
    let mut reader = expr.get_operators_reader();
    let value = match reader.read().ok()? {
        Operator::I32Const { value } if value >= 0 => value as u32,
        _ => return None,
    };
    if !matches!(reader.read(), Ok(Operator::End)) || !reader.eof() {
        return None;
    }
    Some(value)
}

// The exact pinned wit-bindgen 0.62 / Zig 0.16 O2 flat wrapper for the
// maintained string -> result<string,string> case. Before its sole call it
// only opens its own 32-byte C stack frame, stores its two input words there,
// and prepares arguments plus an untouched, bounded result area. The complete
// epilogue is checked as well, so a branch or hidden second call cannot reach
// the application while another generated operation is live.
fn wrapper_target(
    body: wasmparser::FunctionBody<'_>,
    stack: u32,
    heap_base: u32,
) -> Result<u32, &'static str> {
    let mut locals = body
        .get_locals_reader()
        .map_err(|_| "c-checkpoint-wrapper-locals")?;
    if locals.get_count() != 1 || !matches!(locals.read(), Ok((1, wasmparser::ValType::I32))) {
        return Err("c-checkpoint-wrapper-locals");
    }
    let mut r = body
        .get_operators_reader()
        .map_err(|_| "c-checkpoint-wrapper-code")?;
    macro_rules! expect {
        ($pat:pat $(if $guard:expr)?) => {
            if !matches!(r.read(), Ok($pat) $(if $guard)?) {
                return Err("c-checkpoint-wrapper-exact-shape");
            }
        };
    }
    expect!(Operator::GlobalGet { global_index } if global_index == stack);
    expect!(Operator::I32Const { value: 32 });
    expect!(Operator::I32Sub);
    expect!(Operator::LocalTee { local_index: 2 });
    expect!(Operator::GlobalSet { global_index } if global_index == stack);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::LocalGet { local_index: 1 });
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 28 && memarg.align == 2);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 24 && memarg.align == 2);
    let result = match r.read() {
        Ok(Operator::I32Const { value }) if value >= 0 => value as u32,
        _ => return Err("c-checkpoint-result-area"),
    };
    if result < SYSTEM_STACK_HIGH || result.checked_add(12).is_none_or(|end| end > heap_base) {
        return Err("c-checkpoint-result-area");
    }
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 24 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 16 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 8 });
    expect!(Operator::I32Add);
    let target = match r.read() {
        Ok(Operator::Call { function_index }) => function_index,
        _ => return Err("c-checkpoint-wrapper-exact-shape"),
    };
    expect!(Operator::LocalTee { local_index: 1 });
    expect!(Operator::I32Const { value: 1 });
    expect!(Operator::I32Xor);
    expect!(Operator::I32Store8 { memarg } if memarg.memory == 0 && memarg.offset == 0 && memarg.align == 0);
    expect!(Operator::I32Const { value } if value as u32 == result);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 16 });
    expect!(Operator::I32Add);
    expect!(Operator::I32Const { value: 4 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 8 });
    expect!(Operator::I32Add);
    expect!(Operator::I32Const { value: 4 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 1 });
    expect!(Operator::Select);
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 0 && memarg.align == 2);
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 8 && memarg.align == 2);
    expect!(Operator::I32Const { value } if value as u32 == result);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 16 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 8 });
    expect!(Operator::I32Add);
    expect!(Operator::LocalGet { local_index: 1 });
    expect!(Operator::Select);
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 0 && memarg.align == 2);
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 4 && memarg.align == 2);
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 32 });
    expect!(Operator::I32Add);
    expect!(Operator::GlobalSet { global_index } if global_index == stack);
    expect!(Operator::I32Const { value } if value as u32 == result);
    expect!(Operator::End);
    if !r.eof() {
        return Err("c-checkpoint-wrapper-trailing-code");
    }
    Ok(target)
}

// The original selected no-stdio root initializer, as emitted by pinned
// Zig/LLVM. It validates the already-installed context, initializes only its
// own root record and calls only the two independently routed, non-yielding
// canonical context/index intrinsics. An unknown initializer could leave an
// SDK critical scope live even when the application body contains no calls.
fn safe_root_initializer(
    body: wasmparser::FunctionBody<'_>,
    context_get: u32,
    thread_index: u32,
) -> Result<(), &'static str> {
    let mut locals = body
        .get_locals_reader()
        .map_err(|_| "c-checkpoint-root-init-locals")?;
    if locals.get_count() != 1 || !matches!(locals.read(), Ok((2, wasmparser::ValType::I32))) {
        return Err("c-checkpoint-root-init-locals");
    }
    let mut r = body
        .get_operators_reader()
        .map_err(|_| "c-checkpoint-root-init-code")?;
    macro_rules! expect {
        ($pat:pat $(if $guard:expr)?) => {
            if !matches!(r.read(), Ok($pat) $(if $guard)?) {
                return Err("c-checkpoint-root-init-exact-shape");
            }
        };
    }
    expect!(Operator::Block {
        blockty: wasmparser::BlockType::Empty
    });
    expect!(Operator::Block {
        blockty: wasmparser::BlockType::Empty
    });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::Call { function_index } if function_index == context_get);
    expect!(Operator::I32Ne);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 20 && memarg.align == 2);
    expect!(Operator::I32Const { value: 2 });
    expect!(Operator::I32Ne);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 4 && memarg.align == 2);
    expect!(Operator::LocalTee { local_index: 2 });
    expect!(Operator::I32Eqz);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32Const { value: 15 });
    expect!(Operator::I32And);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 8 && memarg.align == 2);
    expect!(Operator::LocalTee { local_index: 3 });
    expect!(Operator::LocalGet { local_index: 2 });
    expect!(Operator::I32LeU);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 3 });
    expect!(Operator::I32Const { value: 15 });
    expect!(Operator::I32And);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 1 });
    expect!(Operator::I32Const { value: -1_048_577 });
    expect!(Operator::I32Add);
    expect!(Operator::I32Const { value: -1_048_576 });
    expect!(Operator::I32LtU);
    expect!(Operator::BrIf { relative_depth: 0 });
    expect!(Operator::LocalGet { local_index: 1 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Load { memarg } if memarg.memory == 0 && memarg.offset == 16 && memarg.align == 2);
    expect!(Operator::I32Eq);
    expect!(Operator::BrIf { relative_depth: 1 });
    expect!(Operator::End);
    expect!(Operator::Unreachable);
    expect!(Operator::End);
    for (value, offset) in [(0, 132), (0, 84)] {
        expect!(Operator::LocalGet { local_index: 0 });
        expect!(Operator::I32Const { value: actual } if actual == value);
        expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == offset && memarg.align == 2);
    }
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 112 && memarg.align == 2);
    expect!(Operator::LocalGet { local_index: 0 });
    expect!(Operator::Call { function_index } if function_index == thread_index);
    expect!(Operator::I32Store { memarg } if memarg.memory == 0 && memarg.offset == 28 && memarg.align == 2);
    expect!(Operator::I32Const { value: 0 });
    expect!(Operator::End);
    if !r.eof() {
        return Err("c-checkpoint-root-init-trailing-code");
    }
    Ok(())
}

struct Selection {
    imported: u32,
    wrapper: u32,
    target: u32,
    yield_import: u32,
    loops: u32,
}

fn select(input: &[u8], public: &str) -> Result<Selection, &'static str> {
    if public.is_empty() || public.len() > 256 || public.starts_with("__lsf_") {
        return Err("c-checkpoint-public-name");
    }
    if c_preimage::bounded_core(input, true)? > INPUT_OPERATOR_LIMIT {
        return Err("c-checkpoint-original-work-bound");
    }
    let features = WasmFeatures::default() & !WasmFeatures::THREADS & !WasmFeatures::MEMORY64;
    Validator::new_with_features(features)
        .validate_all(input)
        .map_err(|_| "c-checkpoint-unshared-core-required")?;

    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut globals = Vec::new();
    let mut imported = 0u32;
    let mut yield_import = None;
    let mut context_get = None;
    let mut thread_index = None;
    let mut initializer = None;
    let mut wrapper = None;
    let mut stack = None;
    let mut heap = None;
    let mut tables = 0u32;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-checkpoint-core-parse")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(signature(&ty.map_err(|_| "c-checkpoint-type")?));
                }
            }
            Payload::ImportSection(reader) => {
                for row in reader.into_imports() {
                    let row = row.map_err(|_| "c-checkpoint-import")?;
                    match row.ty {
                        TypeRef::Func(ty) | TypeRef::FuncExact(ty) => {
                            if row.module == "$root" {
                                let slot = match row.name {
                                    "[thread-yield]" => Some(&mut yield_import),
                                    "[context-get-1]" => Some(&mut context_get),
                                    "[thread-index]" => Some(&mut thread_index),
                                    _ => None,
                                };
                                if let Some(slot) = slot {
                                    if slot.replace(imported).is_some()
                                        || !types
                                            .get(ty as usize)
                                            .is_some_and(|sig| sig.yield_import)
                                    {
                                        return Err("c-checkpoint-canonical-intrinsic-signature");
                                    }
                                }
                            }
                            imported += 1;
                        }
                        TypeRef::Table(_) | TypeRef::Global(_) | TypeRef::Memory(_) => {
                            return Err("c-checkpoint-imported-state");
                        }
                        _ => return Err("c-checkpoint-import-type"),
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    functions.push(ty.map_err(|_| "c-checkpoint-function-type")?);
                }
            }
            Payload::GlobalSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-checkpoint-global")?;
                    globals.push((row.ty, single_i32(row.init_expr)));
                }
            }
            Payload::TableSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-checkpoint-table")?;
                    tables += 1;
                    if row.ty.element_type != wasmparser::RefType::FUNCREF
                        || row.ty.table64
                        || row.ty.shared
                        || row.ty.initial > 65_536
                        || row.ty.maximum.is_none_or(|max| max > 65_536)
                    {
                        return Err("c-checkpoint-original-table");
                    }
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-checkpoint-export")?;
                    let selected = if row.name == public {
                        Some((&mut wrapper, ExternalKind::Func))
                    } else if row.name == "__lsf_c_root_initialize" {
                        Some((&mut initializer, ExternalKind::Func))
                    } else if row.name == "__stack_pointer" {
                        Some((&mut stack, ExternalKind::Global))
                    } else if row.name == "__heap_base" {
                        Some((&mut heap, ExternalKind::Global))
                    } else {
                        None
                    };
                    if let Some((slot, kind)) = selected {
                        if row.kind != kind || slot.replace(row.index).is_some() {
                            return Err("c-checkpoint-required-exports");
                        }
                    }
                }
            }
            Payload::StartSection { .. } => return Err("c-checkpoint-start-not-supported"),
            _ => {}
        }
    }
    if tables != 1 {
        return Err("c-checkpoint-one-original-table");
    }
    let yield_import = yield_import.ok_or("c-checkpoint-yield-not-retained")?;
    let context_get = context_get.ok_or("c-checkpoint-context-get-missing")?;
    let thread_index = thread_index.ok_or("c-checkpoint-thread-index-missing")?;
    let initializer = initializer.ok_or("c-checkpoint-root-init-missing")?;
    let wrapper = wrapper.ok_or("c-checkpoint-public-missing")?;
    let stack = stack.ok_or("c-checkpoint-stack-missing")?;
    let heap = heap.ok_or("c-checkpoint-heap-missing")?;
    let (stack_type, stack_value) = globals
        .get(stack as usize)
        .ok_or("c-checkpoint-stack-global")?;
    if stack_type.content_type != wasmparser::ValType::I32
        || !stack_type.mutable
        || stack_type.shared
        || *stack_value != Some(SYSTEM_STACK_HIGH)
    {
        return Err("c-checkpoint-stack-global");
    }
    let (heap_type, heap_value) = globals
        .get(heap as usize)
        .ok_or("c-checkpoint-heap-global")?;
    if heap_type.content_type != wasmparser::ValType::I32 || heap_type.mutable || heap_type.shared {
        return Err("c-checkpoint-heap-global");
    }
    let heap = heap_value.ok_or("c-checkpoint-heap-global")?;
    let wrapper_ty = wrapper
        .checked_sub(imported)
        .and_then(|idx| functions.get(idx as usize))
        .and_then(|ty| types.get(*ty as usize))
        .ok_or("c-checkpoint-wrapper-defined")?;
    if !wrapper_ty.wrapper {
        return Err("c-checkpoint-wrapper-signature");
    }
    let init_ty = initializer
        .checked_sub(imported)
        .and_then(|idx| functions.get(idx as usize))
        .and_then(|ty| types.get(*ty as usize))
        .ok_or("c-checkpoint-root-init-defined")?;
    if initializer == wrapper || !init_ty.wrapper {
        return Err("c-checkpoint-root-init-signature");
    }
    let mut code_index = imported;
    let mut init_verified = false;
    let mut target = None;
    for payload in Parser::new(0).parse_all(input) {
        if let Payload::CodeSectionEntry(body) = payload.map_err(|_| "c-checkpoint-code")? {
            if code_index == wrapper {
                target = Some(wrapper_target(body.clone(), stack, heap)?);
            }
            if code_index == initializer {
                safe_root_initializer(body, context_get, thread_index)?;
                init_verified = true;
            }
            code_index += 1;
        }
    }
    if !init_verified {
        return Err("c-checkpoint-root-init-body");
    }
    let target = target.ok_or("c-checkpoint-wrapper-body")?;
    let target_ty = target
        .checked_sub(imported)
        .and_then(|idx| functions.get(idx as usize))
        .and_then(|ty| types.get(*ty as usize))
        .ok_or("c-checkpoint-target-defined")?;
    if target == wrapper || target == initializer || !target_ty.application {
        return Err("c-checkpoint-target-signature");
    }

    let mut current = imported;
    let mut incoming = 0u32;
    let mut target_ops = 0u64;
    let mut loops = 0u32;
    let mut segments = 0u32;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-checkpoint-proof")? {
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-checkpoint-export")?;
                    if row.kind == ExternalKind::Func
                        && (row.index == target || row.index == wrapper && row.name != public)
                    {
                        return Err("c-checkpoint-target-or-wrapper-exported");
                    }
                }
            }
            Payload::ElementSection(reader) => {
                for segment in reader {
                    let segment = segment.map_err(|_| "c-checkpoint-element")?;
                    segments += 1;
                    if segments > 1 {
                        return Err("c-checkpoint-static-table-only");
                    }
                    let ElementKind::Active {
                        table_index,
                        offset_expr,
                    } = segment.kind
                    else {
                        return Err("c-checkpoint-static-table-only");
                    };
                    if table_index.unwrap_or(0) != 0 || single_i32(offset_expr).is_none() {
                        return Err("c-checkpoint-static-table-only");
                    }
                    let ElementItems::Functions(members) = segment.items else {
                        return Err("c-checkpoint-static-table-only");
                    };
                    if members.count() > 65_536 {
                        return Err("c-checkpoint-table-bound");
                    }
                    for member in members {
                        let member = member.map_err(|_| "c-checkpoint-element-member")?;
                        if member == target || member == wrapper || member == initializer {
                            return Err("c-checkpoint-indirect-target");
                        }
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "c-checkpoint-operators")?;
                while !ops.eof() {
                    let op = ops.read().map_err(|_| "c-checkpoint-operator")?;
                    if current == target {
                        target_ops += 1;
                    }
                    match op {
                        Operator::Call { function_index } if function_index == target => {
                            if current != wrapper {
                                return Err("c-checkpoint-untrusted-target-caller");
                            }
                            incoming += 1;
                        }
                        Operator::Call { function_index } if function_index == wrapper => {
                            return Err("c-checkpoint-internal-wrapper-caller");
                        }
                        Operator::Call { function_index } if function_index == initializer => {
                            return Err("c-checkpoint-internal-initializer-caller");
                        }
                        // No authenticated summary yet proves which ordinary C
                        // call can leave a mutex or other critical scope live
                        // after it returns. Do not guess from a symbol name or
                        // assume that a completed call means preemption is safe.
                        Operator::Call { .. } if current == target => {
                            return Err("c-checkpoint-target-unknown-call");
                        }
                        Operator::CallIndirect { .. } if current == target => {
                            return Err("c-checkpoint-target-indirect-call");
                        }
                        // A raw store or mutable global could manufacture
                        // hidden SDK critical state without making a call.
                        // Until source/linear-memory ownership is proven, a
                        // selected target is read-only as well as call-free.
                        Operator::GlobalSet { .. }
                        | Operator::I32Store { .. }
                        | Operator::I64Store { .. }
                        | Operator::F32Store { .. }
                        | Operator::F64Store { .. }
                        | Operator::I32Store8 { .. }
                        | Operator::I32Store16 { .. }
                        | Operator::I64Store8 { .. }
                        | Operator::I64Store16 { .. }
                        | Operator::I64Store32 { .. }
                        | Operator::MemoryGrow { .. }
                        | Operator::MemoryFill { .. }
                        | Operator::MemoryCopy { .. }
                        | Operator::MemoryInit { .. }
                        | Operator::DataDrop { .. }
                            if current == target =>
                        {
                            return Err("c-checkpoint-target-unproven-mutation");
                        }
                        Operator::ReturnCall { .. }
                        | Operator::ReturnCallIndirect { .. }
                        | Operator::CallRef { .. }
                        | Operator::ReturnCallRef { .. }
                        | Operator::RefFunc { .. } => {
                            return Err("c-checkpoint-reference-or-tail-call");
                        }
                        Operator::TableSet { .. }
                        | Operator::TableGrow { .. }
                        | Operator::TableFill { .. }
                        | Operator::TableInit { .. }
                        | Operator::TableCopy { .. }
                        | Operator::ElemDrop { .. } => {
                            return Err("c-checkpoint-table-mutation");
                        }
                        Operator::Loop { .. } if current == target => {
                            loops = loops.checked_add(1).ok_or("c-checkpoint-loop-bound")?;
                        }
                        _ => {}
                    }
                }
                current += 1;
            }
            _ => {}
        }
    }
    if segments != 1
        || incoming != 1
        || loops == 0
        || loops > MAX_CHECKPOINTS
        || target_ops + u64::from(loops) * 4 > TARGET_OPERATOR_LIMIT
    {
        return Err("c-checkpoint-finite-target-required");
    }
    Ok(Selection {
        imported,
        wrapper,
        target,
        yield_import,
        loops,
    })
}

struct Rewrite {
    current: u32,
    target: u32,
    yield_import: u32,
    inserted: u32,
}

impl Reencode for Rewrite {
    type Error = &'static str;

    fn parse_function_body(
        &mut self,
        section: &mut CodeSection,
        body: wasmparser::FunctionBody<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let mut function = self.new_function_with_parsed_locals(&body)?;
        let mut ops = body.get_operators_reader()?;
        while !ops.eof() {
            let op = ops.read()?;
            let checkpoint = self.current == self.target && matches!(op, Operator::Loop { .. });
            function.instruction(&self.instruction(op)?);
            if checkpoint {
                // Match ordinary thrd_yield's fail-closed handling. No C helper,
                // host-owned work item, linear allocation or new local is used.
                function
                    .instruction(&Instruction::Call(self.yield_import))
                    .instruction(&Instruction::If(BlockType::Empty))
                    .instruction(&Instruction::Unreachable)
                    .instruction(&Instruction::End);
                self.inserted += 1;
            }
        }
        self.current += 1;
        section.function(&function);
        Ok(())
    }
}

/// Derive only the narrow root-only checkpoint core. This is source evidence,
/// not a runtime grant, admission proof, or a replacement for the v1 derivation.
/// The caller must authenticate `input` as the original linked compiler output.
pub fn transform_c_root_checkpoints_v2(
    input: &[u8],
    expected: [u8; 32],
    public: &str,
) -> Result<(Vec<u8>, CCheckpointReceipt), &'static str> {
    if <[u8; 32]>::from(Sha256::digest(input)) != expected {
        return Err("c-checkpoint-original-preimage-mismatch");
    }
    let selected = select(input, public)?;
    let mut rewrite = Rewrite {
        current: selected.imported,
        target: selected.target,
        yield_import: selected.yield_import,
        inserted: 0,
    };
    let mut module = Module::new();
    rewrite
        .parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "c-checkpoint-reencode")?;
    if rewrite.inserted != selected.loops {
        return Err("c-checkpoint-insertion-count");
    }
    let output = module.finish();
    c_preimage::bounded_core(&output, false)?;
    let features = WasmFeatures::default() & !WasmFeatures::THREADS & !WasmFeatures::MEMORY64;
    Validator::new_with_features(features)
        .validate_all(&output)
        .map_err(|_| "c-checkpoint-derived-invalid")?;
    let checkpoint_core_digest = Sha256::digest(&output).into();
    Ok((
        output,
        CCheckpointReceipt {
            original_digest: expected,
            checkpoint_core_digest,
            public_wrapper: selected.wrapper,
            application_function: selected.target,
            canonical_yield_import: selected.yield_import,
            inserted_checkpoints: rewrite.inserted,
            lazy_no_concurrency_qualified: false,
            actual_engine_qualified: false,
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        ConstExpr, ElementSection, Elements, EntityType, ExportKind, ExportSection, GlobalSection,
        GlobalType, ImportSection, MemorySection, MemoryType, RefType, TableSection, TableType,
    };

    #[derive(Clone, Copy, Default)]
    struct Variant {
        target_in_table: bool,
        wrapper_in_table: bool,
        other_caller: bool,
        wrapper_has_hidden_store: bool,
        target_indirect: bool,
        table_mutation: bool,
        missing_yield: bool,
        bad_yield_signature: bool,
        target_export: bool,
        recursive_target: bool,
        target_calls_other: bool,
        target_calls_after_loop: bool,
        target_calls_yield: bool,
        target_writes_memory: bool,
        target_changes_global: bool,
        extra_nops: u32,
        extra_loops: u32,
        no_loop: bool,
        bad_result_area: bool,
        unsafe_initializer: bool,
    }

    fn mem(offset: u64, align: u32) -> MemArg {
        MemArg {
            offset,
            align,
            memory_index: 0,
        }
    }

    fn fixture(v: Variant) -> Vec<u8> {
        let mut m = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]); // canonical yield
        types.ty().function([ValType::I32; 2], [ValType::I32]); // root wrapper
        types.ty().function([ValType::I32; 3], [ValType::I32]); // application
        types.ty().function([], []); // another callback
        m.section(&types);
        let mut imports = ImportSection::new();
        imports.import(
            "$root",
            if v.missing_yield {
                "[missing-yield]"
            } else {
                "[thread-yield]"
            },
            EntityType::Function(if v.bad_yield_signature { 3 } else { 0 }),
        );
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", "[thread-index]", EntityType::Function(0));
        m.section(&imports);
        let mut funcs = FunctionSection::new();
        funcs.function(1).function(2).function(3).function(1);
        m.section(&funcs);
        let mut tables = TableSection::new();
        tables.table(TableType {
            element_type: RefType::FUNCREF,
            minimum: 1,
            maximum: Some(1),
            table64: false,
            shared: false,
        });
        m.section(&tables);
        let mut memories = MemorySection::new();
        memories.memory(MemoryType {
            minimum: 4,
            maximum: Some(4),
            memory64: false,
            shared: false,
            page_size_log2: None,
        });
        m.section(&memories);
        let mut globals = GlobalSection::new();
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(SYSTEM_STACK_HIGH as i32),
        );
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: false,
                shared: false,
            },
            &ConstExpr::i32_const(196_608),
        );
        m.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("example:checkpoint/api#greet", ExportKind::Func, 3);
        exports.export("__lsf_c_root_initialize", ExportKind::Func, 6);
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export("__heap_base", ExportKind::Global, 1);
        if v.target_export {
            exports.export("leaked-application", ExportKind::Func, 4);
        }
        m.section(&exports);
        let mut elements = ElementSection::new();
        let table_entry = if v.target_in_table {
            4
        } else if v.wrapper_in_table {
            3
        } else {
            5
        };
        elements.active(
            Some(0),
            &ConstExpr::i32_const(0),
            Elements::Functions(Cow::Owned(vec![table_entry])),
        );
        m.section(&elements);
        let mut code = CodeSection::new();
        let result = if v.bad_result_area { 8 } else { 140_000 };
        let mut wrapper = Function::new([(1, ValType::I32)]);
        wrapper
            .instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::I32Const(32))
            .instruction(&Instruction::I32Sub)
            .instruction(&Instruction::LocalTee(2))
            .instruction(&Instruction::GlobalSet(0))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Store(mem(28, 2)))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Store(mem(24, 2)));
        if v.wrapper_has_hidden_store {
            wrapper
                .instruction(&Instruction::I32Const(140_000))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Store(mem(0, 2)));
        }
        wrapper
            .instruction(&Instruction::I32Const(result))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(24))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(8))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::Call(4))
            .instruction(&Instruction::LocalTee(1))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Xor)
            .instruction(&Instruction::I32Store8(mem(0, 0)))
            .instruction(&Instruction::I32Const(result))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::I32Const(4))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(8))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::I32Const(4))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Select)
            .instruction(&Instruction::I32Load(mem(0, 2)))
            .instruction(&Instruction::I32Store(mem(8, 2)))
            .instruction(&Instruction::I32Const(result))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(8))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Select)
            .instruction(&Instruction::I32Load(mem(0, 2)))
            .instruction(&Instruction::I32Store(mem(4, 2)))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(32))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::GlobalSet(0))
            .instruction(&Instruction::I32Const(result))
            .instruction(&Instruction::End);
        code.function(&wrapper);
        let mut target = Function::new([]);
        if v.target_calls_other {
            target.instruction(&Instruction::Call(5));
        }
        if v.target_indirect {
            target
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::CallIndirect {
                    type_index: 3,
                    table_index: 0,
                });
        }
        if v.recursive_target {
            target
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::Call(4))
                .instruction(&Instruction::Drop);
        }
        if !v.no_loop {
            target
                .instruction(&Instruction::Block(BlockType::Empty))
                .instruction(&Instruction::Loop(BlockType::Empty))
                .instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::I32Eqz)
                .instruction(&Instruction::BrIf(1))
                .instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Sub)
                .instruction(&Instruction::LocalSet(0))
                .instruction(&Instruction::Br(0))
                .instruction(&Instruction::End)
                .instruction(&Instruction::End);
        }
        if v.target_calls_after_loop {
            target.instruction(&Instruction::Call(5));
        }
        if v.target_calls_yield {
            target
                .instruction(&Instruction::Call(0))
                .instruction(&Instruction::Drop);
        }
        if v.target_writes_memory {
            target
                .instruction(&Instruction::I32Const(16))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Store(mem(0, 2)));
        }
        if v.target_changes_global {
            target
                .instruction(&Instruction::I32Const(42))
                .instruction(&Instruction::GlobalSet(0));
        }
        for _ in 0..v.extra_nops {
            target.instruction(&Instruction::Nop);
        }
        for _ in 0..v.extra_loops {
            target
                .instruction(&Instruction::Loop(BlockType::Empty))
                .instruction(&Instruction::End);
        }
        target
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::End);
        code.function(&target);
        let mut other = Function::new([]);
        if v.other_caller {
            other
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::Call(4))
                .instruction(&Instruction::Drop);
        }
        if v.table_mutation {
            other
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::RefNull(wasm_encoder::HeapType::FUNC))
                .instruction(&Instruction::TableSet(0));
        }
        other.instruction(&Instruction::End);
        code.function(&other);
        let mut init = Function::new([(2, ValType::I32)]);
        init.instruction(&Instruction::Block(BlockType::Empty))
            .instruction(&Instruction::Block(BlockType::Empty))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::Call(1))
            .instruction(&Instruction::I32Ne)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(mem(20, 2)))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::I32Ne)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(mem(4, 2)))
            .instruction(&Instruction::LocalTee(2))
            .instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(mem(8, 2)))
            .instruction(&Instruction::LocalTee(3))
            .instruction(&Instruction::LocalGet(2))
            .instruction(&Instruction::I32LeU)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(3))
            .instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Const(-1_048_577))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::I32Const(-1_048_576))
            .instruction(&Instruction::I32LtU)
            .instruction(&Instruction::BrIf(0))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(mem(16, 2)))
            .instruction(&Instruction::I32Eq)
            .instruction(&Instruction::BrIf(1))
            .instruction(&Instruction::End)
            .instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End);
        for offset in [132, 84] {
            init.instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::I32Const(0))
                .instruction(&Instruction::I32Store(mem(offset, 2)));
        }
        init.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Store(mem(112, 2)))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::Call(2))
            .instruction(&Instruction::I32Store(mem(28, 2)));
        if v.unsafe_initializer {
            init.instruction(&Instruction::I32Const(140_000))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Store(mem(0, 2)));
        }
        init.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::End);
        code.function(&init);
        m.section(&code);
        m.finish()
    }

    fn derive(input: &[u8]) -> Result<(Vec<u8>, CCheckpointReceipt), &'static str> {
        transform_c_root_checkpoints_v2(
            input,
            Sha256::digest(input).into(),
            "example:checkpoint/api#greet",
        )
    }

    // Extend the existing C canonical-ABI fixture with the exact checked
    // wrapper, no-stdio initializer, one private target and two intrinsics.
    // This is only a source-level derivation control, never engine evidence.
    struct FixtureExtension {
        imported: u32,
        original_functions: u32,
        target_type: u32,
        root: u32,
        init: u32,
        post: u32,
    }

    struct SampleRemap {
        target: u32,
        init: bool,
    }
    impl Reencode for SampleRemap {
        type Error = &'static str;
        fn function_index(&mut self, index: u32) -> Result<u32, reencode::Error<Self::Error>> {
            if self.init {
                Ok(match index {
                    1 => 0,
                    2 => 4,
                    _ => index,
                })
            } else {
                Ok(if index == 4 { self.target } else { index })
            }
        }
    }

    impl Reencode for FixtureExtension {
        type Error = &'static str;
        fn function_index(&mut self, index: u32) -> Result<u32, reencode::Error<Self::Error>> {
            Ok(index + u32::from(index >= self.imported) * 2)
        }
        fn parse_type_section(
            &mut self,
            out: &mut TypeSection,
            reader: wasmparser::TypeSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_type_section(self, out, reader)?;
            out.ty().function([ValType::I32; 3], [ValType::I32]);
            Ok(())
        }
        fn parse_import_section(
            &mut self,
            out: &mut ImportSection,
            reader: wasmparser::ImportSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_import_section(self, out, reader)?;
            out.import("$root", "[thread-yield]", EntityType::Function(0));
            out.import("$root", "[thread-index]", EntityType::Function(0));
            Ok(())
        }
        fn parse_function_section(
            &mut self,
            out: &mut FunctionSection,
            reader: wasmparser::FunctionSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            for (ordinal, ty) in reader.into_iter().enumerate() {
                let index = self.imported + ordinal as u32;
                let ty = if index == self.root {
                    1
                } else if index == self.post {
                    2
                } else {
                    ty?
                };
                out.function(ty);
            }
            out.function(self.target_type);
            Ok(())
        }
        fn parse_code_section(
            &mut self,
            out: &mut CodeSection,
            reader: wasmparser::CodeSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            let sample = fixture(Variant::default());
            let mut sample_bodies = Vec::new();
            for payload in Parser::new(0).parse_all(&sample) {
                if let Payload::CodeSectionEntry(body) = payload? {
                    sample_bodies.push(body);
                }
            }
            let target = self.imported + self.original_functions + 2;
            for (ordinal, body) in reader.into_iter().enumerate() {
                let body = body?;
                let index = self.imported + ordinal as u32;
                if index == self.root || index == self.init {
                    let initializer = index == self.init;
                    let mut sample_remap = SampleRemap {
                        target,
                        init: initializer,
                    };
                    let source = sample_bodies[if initializer { 3 } else { 0 }].clone();
                    sample_remap.parse_function_body(out, source)?;
                } else {
                    self.parse_function_body(out, body)?;
                }
            }
            let mut plain = SampleRemap {
                target,
                init: false,
            };
            plain.parse_function_body(out, sample_bodies[1].clone())?;
            Ok(())
        }
    }

    fn canonical_fixture() -> Vec<u8> {
        let original = c_abi::tests::fixture(0);
        let base = plan(&original).unwrap();
        let mut edit = FixtureExtension {
            imported: base.imported_functions,
            original_functions: base.function_count,
            target_type: base.type_count,
            root: 9,
            init: 7,
            post: 13,
        };
        let mut module = Module::new();
        edit.parse_core_module(&mut module, Parser::new(0), &original)
            .unwrap();
        module.finish()
    }

    #[test]
    fn v2_recomputes_original_through_existing_canonical_abi_without_changing_v1() {
        let original = canonical_fixture();
        let digest = Sha256::digest(&original).into();
        let (legacy, old_receipt) =
            c_abi::transform_c_canonical_abi(&original, digest, "run").unwrap();
        let (derived, receipt) =
            c_abi::transform_c_canonical_abi_checkpoint_v2(&original, digest, "run").unwrap();
        assert_ne!(legacy, derived);
        assert_eq!(receipt.original_digest, digest);
        assert_eq!(receipt.checkpoint.original_digest, digest);
        assert_eq!(
            receipt.canonical.original_digest,
            receipt.checkpoint.checkpoint_core_digest
        );
        assert!(!receipt.runtime_profile_qualified && !receipt.canonical.runtime_profile_qualified);
        assert_eq!(
            c_abi::verify_c_canonical_abi(&original, &legacy, "run").unwrap(),
            old_receipt
        );
        assert_eq!(
            c_abi::verify_c_canonical_abi(&original, &derived, "run").unwrap_err(),
            "c-abi-final-core-byte-mismatch"
        );
        assert_eq!(
            c_abi::verify_c_canonical_abi_checkpoint_v2(&original, &derived, "run").unwrap(),
            receipt
        );
        assert_eq!(
            c_abi::verify_c_canonical_abi_checkpoint_v2(&original, &legacy, "run").unwrap_err(),
            "c-checkpoint-canonical-core-byte-mismatch"
        );
    }

    #[test]
    fn private_root_target_gets_only_bounded_canonical_loop_checkpoint() {
        let original = fixture(Variant::default());
        let (derived, proof) = derive(&original).unwrap();
        assert_ne!(original, derived);
        assert_eq!(
            proof.original_digest,
            <[u8; 32]>::from(Sha256::digest(&original))
        );
        assert_eq!(
            (
                proof.public_wrapper,
                proof.application_function,
                proof.canonical_yield_import
            ),
            (3, 4, 0)
        );
        assert_eq!(proof.inserted_checkpoints, 1);
        assert!(!proof.lazy_no_concurrency_qualified && !proof.actual_engine_qualified);
        assert_eq!(derive(&original).unwrap().0, derived);
        let mut bodies = Vec::new();
        for payload in Parser::new(0).parse_all(&derived) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                let mut ops = body.get_operators_reader().unwrap();
                let mut rows = Vec::new();
                while !ops.eof() {
                    rows.push(ops.read().unwrap());
                }
                bodies.push(rows);
            }
        }
        let loop_at = bodies[1]
            .iter()
            .position(|op| matches!(op, Operator::Loop { .. }))
            .unwrap();
        assert!(matches!(
            bodies[1][loop_at + 1],
            Operator::Call { function_index: 0 }
        ));
        assert!(matches!(bodies[1][loop_at + 2], Operator::If { .. }));
        assert!(matches!(bodies[1][loop_at + 3], Operator::Unreachable));
        assert!(matches!(bodies[1][loop_at + 4], Operator::End));
        assert_eq!(
            transform_c_root_checkpoints_v2(&original, [0; 32], "example:checkpoint/api#greet")
                .unwrap_err(),
            "c-checkpoint-original-preimage-mismatch"
        );
    }

    #[test]
    fn wrapper_or_target_reachable_from_untrusted_paths_is_refused() {
        for (variant, expected) in [
            (
                Variant {
                    target_in_table: true,
                    ..Variant::default()
                },
                "c-checkpoint-indirect-target",
            ),
            (
                Variant {
                    wrapper_in_table: true,
                    ..Variant::default()
                },
                "c-checkpoint-indirect-target",
            ),
            (
                Variant {
                    other_caller: true,
                    ..Variant::default()
                },
                "c-checkpoint-untrusted-target-caller",
            ),
            (
                Variant {
                    recursive_target: true,
                    ..Variant::default()
                },
                "c-checkpoint-untrusted-target-caller",
            ),
            (
                Variant {
                    target_calls_other: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-unknown-call",
            ),
            (
                Variant {
                    target_calls_after_loop: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-unknown-call",
            ),
            (
                Variant {
                    target_calls_yield: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-unknown-call",
            ),
            (
                Variant {
                    target_writes_memory: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-unproven-mutation",
            ),
            (
                Variant {
                    target_changes_global: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-unproven-mutation",
            ),
            (
                Variant {
                    target_indirect: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-indirect-call",
            ),
            (
                Variant {
                    table_mutation: true,
                    ..Variant::default()
                },
                "c-checkpoint-table-mutation",
            ),
            (
                Variant {
                    target_export: true,
                    ..Variant::default()
                },
                "c-checkpoint-target-or-wrapper-exported",
            ),
        ] {
            assert_eq!(derive(&fixture(variant)).unwrap_err(), expected);
        }
    }

    #[test]
    fn loop_and_work_bounds_fail_closed_before_instrumentation() {
        for variant in [
            Variant {
                extra_loops: MAX_CHECKPOINTS,
                ..Variant::default()
            },
            Variant {
                extra_nops: TARGET_OPERATOR_LIMIT as u32,
                ..Variant::default()
            },
        ] {
            assert_eq!(
                derive(&fixture(variant)).unwrap_err(),
                "c-checkpoint-finite-target-required"
            );
        }
        let (_, two) = derive(&fixture(Variant {
            extra_loops: 1,
            ..Variant::default()
        }))
        .unwrap();
        assert_eq!(two.inserted_checkpoints, 2);
    }

    #[test]
    fn hidden_wrapper_state_or_missing_original_intrinsic_is_refused() {
        for (variant, expected) in [
            (
                Variant {
                    wrapper_has_hidden_store: true,
                    ..Variant::default()
                },
                "c-checkpoint-wrapper-exact-shape",
            ),
            (
                Variant {
                    unsafe_initializer: true,
                    ..Variant::default()
                },
                "c-checkpoint-root-init-exact-shape",
            ),
            (
                Variant {
                    bad_result_area: true,
                    ..Variant::default()
                },
                "c-checkpoint-result-area",
            ),
            (
                Variant {
                    missing_yield: true,
                    ..Variant::default()
                },
                "c-checkpoint-yield-not-retained",
            ),
            (
                Variant {
                    bad_yield_signature: true,
                    ..Variant::default()
                },
                "c-checkpoint-canonical-intrinsic-signature",
            ),
            (
                Variant {
                    no_loop: true,
                    ..Variant::default()
                },
                "c-checkpoint-finite-target-required",
            ),
        ] {
            assert_eq!(derive(&fixture(variant)).unwrap_err(), expected);
        }
    }
}
