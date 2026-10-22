//! Stackless root attach/finish/detach and legal pre-return logical retirement.
//! Canonical allocation/cleanup use a disjoint import-free System stack; all
//! original guest memory and physical Native permits remain Store-owned.
//! This is source infrastructure; no component/profile is enabled by it.
use super::*;
use std::collections::{BTreeMap, BTreeSet};
use wasm_encoder::{ConstExpr, GlobalSection, GlobalType};

const ROOT: &str = "__lsf_rust_activation_root";
const BOOT: &str = "__lsf_rust_root_bootstrap";
const FINISH: &str = "__lsf_rust_root_finish";
const REAP: &str = "__lsf_rust_root_reap";
const SYSTEM_STACK_BYTES: u32 = 65_536;
const MAX_CANONICAL_EDGES: usize = 65_536;

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
    pub canonical_system_stack_low: Option<u32>,
    pub canonical_system_stack_high: Option<u32>,
    pub canonical_system_scope_global: Option<u32>,
    pub canonical_system_closure_functions: u32,
    pub canonical_result_area: Option<u32>,
    pub canonical_result_guard_installed: bool,
    pub post_return_function: Option<u32>,
    pub original_post_return_body: Option<u32>,
    pub realloc_function: Option<u32>,
    pub original_realloc_body: Option<u32>,
    pub root_export_bootstrap_qualified: bool,
    pub canonical_creation_enabled: bool,
}

/// A source guard for the independently authenticated original
/// result<string,string> layout. These coordinates do not authenticate WIT,
/// original private BSS, the allocator body or the captured compiler event.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CanonicalResultGuard {
    pub static_area: u32,
    pub original_heap_low: u32,
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
    high: u32,
    system_scope: Option<u32>,
    canonical_closure: BTreeSet<u32>,
    post_return: Option<(u32, u32, Vec<ValType>)>,
    realloc: Option<(u32, u32)>,
    result_guard: Option<CanonicalResultGuard>,
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

fn inspect(
    input: &[u8],
    thread: &ThreadEntryReceipt,
    post_return: Option<&str>,
    realloc: Option<&str>,
) -> Result<Root, &'static str> {
    let base = plan(input)?;
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut exports = std::collections::BTreeMap::new();
    let mut imported = 0;
    let mut context_set = None;
    let mut globals = 0;
    let mut initial_globals = Vec::new();
    let mut low_global = None;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-root-core-shape")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "rust-root-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for import in reader.into_imports() {
                    let import = import.map_err(|_| "rust-root-import")?;
                    if let TypeRef::Func(index) | TypeRef::FuncExact(index) = import.ty {
                        if import.module == "$root" && import.name == "[context-set-1]" {
                            let ty = types
                                .get(index as usize)
                                .ok_or("rust-root-context-set-type")?;
                            if context_set.replace(imported).is_some()
                                || ty.params() != [wasmparser::ValType::I32]
                                || !ty.results().is_empty()
                            {
                                return Err("rust-root-context-set-signature-or-duplicate");
                            }
                        }
                        imported += 1;
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    functions.push(ty.map_err(|_| "rust-root-function-type")?);
                }
            }
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
            }
            Payload::ExportSection(reader) => {
                for export in reader {
                    let export = export.map_err(|_| "rust-root-export")?;
                    if export.name == "__stack_low" {
                        if export.kind != ExternalKind::Global
                            || low_global.replace(export.index).is_some()
                        {
                            return Err("rust-root-stack-low-export");
                        }
                    }
                    if [ROOT, BOOT, FINISH, REAP].contains(&export.name)
                        || post_return == Some(export.name)
                        || realloc == Some(export.name)
                    {
                        if export.kind != ExternalKind::Func
                            || exports.insert(export.name, export.index).is_some()
                        {
                            return Err("rust-root-support-export-shape");
                        }
                    }
                }
            }
            Payload::StartSection { .. } => return Err("rust-root-start-before-bootstrap-denied"),
            _ => {}
        }
    }
    if exports.len() != 4 + usize::from(post_return.is_some()) + usize::from(realloc.is_some())
        || globals >= MAX_FUNCTIONS - 1
        || base.imported_functions
            + base.function_count
            + 1
            + u32::from(post_return.is_some())
            + u32::from(realloc.is_some())
            > MAX_FUNCTIONS
    {
        return Err("rust-root-support-exports-or-bounds");
    }
    let function_type = |name: &str| -> Result<(u32, &wasmparser::FuncType), &'static str> {
        let defined = exports[name]
            .checked_sub(imported)
            .ok_or("rust-root-support-must-be-defined")?;
        let index = *functions
            .get(defined as usize)
            .ok_or("rust-root-support-function-index")?;
        Ok((
            index,
            types
                .get(index as usize)
                .ok_or("rust-root-support-type-index")?,
        ))
    };
    let (ty, root) = function_type(ROOT)?;
    let (_, boot) = function_type(BOOT)?;
    let (_, finish) = function_type(FINISH)?;
    let (_, reap) = function_type(REAP)?;
    if boot.params() != [wasmparser::ValType::I32, wasmparser::ValType::I32]
        || boot.results() != [wasmparser::ValType::I32]
        || finish.params() != [wasmparser::ValType::I32]
        || !finish.results().is_empty()
        || reap.params() != [wasmparser::ValType::I32]
        || !reap.results().is_empty()
        || root.params().len() > 16
        || root.results().len() > 16
    {
        return Err("rust-root-support-or-flat-abi-signature");
    }
    let distinct = exports
        .values()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    if distinct.len() != 4 + usize::from(post_return.is_some()) + usize::from(realloc.is_some())
        || distinct.contains(&thread.entry_function)
        || distinct.contains(&thread.stack.helper_get_function)
        || distinct.contains(&thread.stack.helper_set_function)
    {
        return Err("rust-root-support-function-alias-denied");
    }
    let (low_type, low) = initial_globals
        .get(low_global.ok_or("rust-root-linker-stack-low-missing")? as usize)
        .ok_or("rust-root-stack-low-index")?;
    let low = low.ok_or("rust-root-stack-low-not-constant")?;
    if low_type.content_type != wasmparser::ValType::I32
        || low_type.mutable
        || low_type.shared
        || low == 0
        || low % 16 != 0
        || low >= base.stack_initial
        || base.stack_initial - low < 65_536
    {
        return Err("rust-root-linker-stack-range");
    }
    let canonical = post_return.is_some() || realloc.is_some();
    let high = if canonical {
        let high = base
            .stack_initial
            .checked_sub(SYSTEM_STACK_BYTES)
            .ok_or("rust-root-canonical-system-stack-reservation")?;
        if high <= low || high - low < 65_536 {
            return Err("rust-root-canonical-system-stack-reservation");
        }
        high
    } else {
        base.stack_initial
    };
    for payload in Parser::new(0).parse_all(input) {
        if let Payload::DataSection(reader) =
            payload.map_err(|_| "rust-root-original-data-shape")?
        {
            for row in reader {
                let row = row.map_err(|_| "rust-root-original-data-segment")?;
                if let wasmparser::DataKind::Active {
                    memory_index,
                    offset_expr,
                } = row.kind
                {
                    let mut ops = offset_expr.get_operators_reader();
                    let begin = match ops.read().map_err(|_| "rust-root-original-data-offset")? {
                        Operator::I32Const { value } => value as u32,
                        _ => return Err("rust-root-original-data-constant-offset"),
                    };
                    if memory_index != 0 || !matches!(ops.read(), Ok(Operator::End)) || !ops.eof() {
                        return Err("rust-root-original-data-constant-offset");
                    }
                    let end = u64::from(begin) + row.data.len() as u64;
                    if !row.data.is_empty() && begin < base.stack_initial && end > u64::from(low) {
                        return Err("rust-root-original-data-overlaps-reserved-stacks");
                    }
                }
            }
        }
    }
    if thread.stack.original_stack_global != base.stack_global
        || thread.stack.original_initial_stack_pointer != base.stack_initial
        || thread.stack.context_get_import != base.context_get
    {
        return Err("rust-root-thread-receipt-layout");
    }
    let helpers =
        thread_entry::checked_stack_helpers(base.context_get).map(Function::into_raw_body);
    let mut index = imported;
    let mut found = 0;
    for payload in Parser::new(0).parse_all(input) {
        if let Payload::CodeSectionEntry(body) = payload.map_err(|_| "rust-root-helper-shape")? {
            for (helper, expected) in [
                (thread.stack.helper_get_function, &helpers[0]),
                (thread.stack.helper_set_function, &helpers[1]),
            ] {
                if index == helper {
                    let range = body.range();
                    let start =
                        usize::try_from(range.start).map_err(|_| "rust-root-helper-range")?;
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
    let mut root = Root {
        root: exports[ROOT],
        ty,
        params: root
            .params()
            .iter()
            .copied()
            .map(value)
            .collect::<Result<_, _>>()?,
        results: root
            .results()
            .iter()
            .copied()
            .map(value)
            .collect::<Result<_, _>>()?,
        boot: exports[BOOT],
        finish: exports[FINISH],
        reap: exports[REAP],
        context_set: context_set.ok_or("rust-root-context-set-missing")?,
        lifecycle: globals,
        cloned: imported + functions.len() as u32,
        base,
        get: thread.stack.helper_get_function,
        set: thread.stack.helper_set_function,
        low,
        high,
        system_scope: canonical.then_some(globals + 1),
        result_guard: None,
        canonical_closure: BTreeSet::new(),
        realloc: match realloc {
            None => None,
            Some(name) => {
                let (ty, function) = function_type(name)?;
                if function.params() != [wasmparser::ValType::I32; 4]
                    || function.results() != [wasmparser::ValType::I32]
                {
                    return Err("rust-root-realloc-signature");
                }
                Some((exports[name], ty))
            }
        },
        post_return: match post_return {
            None => None,
            Some(name) => {
                let (ty, function) = function_type(name)?;
                if !function.results().is_empty()
                    || function.params() != root.results()
                    || function.params().len() > 16
                {
                    return Err("rust-root-post-return-flat-signature");
                }
                Some((
                    exports[name],
                    ty,
                    function
                        .params()
                        .iter()
                        .copied()
                        .map(value)
                        .collect::<Result<_, _>>()?,
                ))
            }
        },
    };
    root.canonical_system_closure(input)?;
    Ok(root)
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
    fn canonical_system_closure(&mut self, input: &[u8]) -> Result<(), &'static str> {
        if self.system_scope.is_none() {
            return Ok(());
        }
        let mut calls = BTreeMap::<u32, Vec<u32>>::new();
        let mut index = self.base.imported_functions;
        let mut edges = 0;
        for payload in Parser::new(0).parse_all(input) {
            if let Payload::CodeSectionEntry(body) =
                payload.map_err(|_| "rust-root-canonical-graph-parse")?
            {
                let mut targets = Vec::new();
                let mut forbidden = false;
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "rust-root-canonical-graph-code")?;
                while !ops.eof() {
                    match ops
                        .read()
                        .map_err(|_| "rust-root-canonical-graph-operator")?
                    {
                        Operator::Call { function_index } => {
                            targets.push(function_index);
                            edges += 1;
                        }
                        Operator::CallIndirect { .. }
                        | Operator::ReturnCall { .. }
                        | Operator::ReturnCallIndirect { .. }
                        | Operator::CallRef { .. }
                        | Operator::ReturnCallRef { .. }
                        | Operator::RefFunc { .. } => forbidden = true,
                        _ => {}
                    }
                }
                if forbidden {
                    targets.push(u32::MAX);
                }
                if edges > MAX_CANONICAL_EDGES {
                    return Err("rust-root-canonical-graph-edge-bound");
                }
                calls.insert(index, targets);
                index += 1;
            }
        }
        let mut pending = Vec::new();
        if let Some((function, _)) = self.realloc {
            pending.push(function);
        }
        if let Some((function, _, _)) = &self.post_return {
            pending.push(*function);
        }
        while let Some(index) = pending.pop() {
            if !self.canonical_closure.insert(index) {
                continue;
            }
            if [self.root, self.boot, self.finish, self.reap].contains(&index) {
                return Err("rust-root-canonical-lifecycle-hook-not-qualified");
            }
            // These exact helpers were independently byte-checked above. Their
            // new System branch returns before any context lookup/intrinsic.
            if index == self.get || index == self.set {
                continue;
            }
            if index < self.base.imported_functions {
                return Err("rust-root-canonical-import-or-tls-not-qualified");
            }
            let targets = calls
                .get(&index)
                .ok_or("rust-root-canonical-function-index")?;
            if targets.contains(&u32::MAX) {
                return Err("rust-root-canonical-indirect-or-callback-not-qualified");
            }
            pending.extend(targets.iter().copied());
        }
        Ok(())
    }
    fn bootstrap(&self, body: &mut Function, context: u32) {
        body.instruction(&Instruction::GlobalGet(self.lifecycle));
        reject(body);
        body.instruction(&Instruction::Call(self.base.context_get));
        reject(body);
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32Ne);
        reject(body);
        body.instruction(&Instruction::I32Const(self.low as i32));
        body.instruction(&Instruction::I32Const(self.high as i32))
            .instruction(&Instruction::Call(self.boot))
            .instruction(&Instruction::LocalTee(context))
            .instruction(&Instruction::I32Eqz);
        reject(body);
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Load(address(12)))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Ne);
        reject(body);
        for (offset, expected) in [(0, self.high), (4, self.low), (8, self.high)] {
            body.instruction(&Instruction::LocalGet(context))
                .instruction(&Instruction::I32Load(address(offset)))
                .instruction(&Instruction::I32Const(expected as i32))
                .instruction(&Instruction::I32Ne);
            reject(body);
        }
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32Ne);
        reject(body);
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::I32Store(address(12)))
            .instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::GlobalSet(self.lifecycle));
    }
    fn wrapper(&self) -> Function {
        let context = self.params.len() as u32;
        let mut locals = vec![(1, ValType::I32)];
        locals.extend(self.results.iter().map(|ty| (1, *ty)));
        if self.result_guard.is_some() {
            locals.push((3, ValType::I32));
        }
        let mut body = Function::new(locals);
        self.bootstrap(&mut body, context);
        for index in 0..self.params.len() as u32 {
            body.instruction(&Instruction::LocalGet(index));
        }
        body.instruction(&Instruction::Call(self.cloned));
        for index in (0..self.results.len() as u32).rev() {
            body.instruction(&Instruction::LocalSet(context + 1 + index));
        }
        if let Some(guard) = self.result_guard {
            self.capture_result(&mut body, context, guard);
        }
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::Call(self.finish));
        body.instruction(&Instruction::Call(self.base.context_get))
            .instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Load(address(12)))
            .instruction(&Instruction::I32Const(4))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Load(address(0)))
            .instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Load(address(8)))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        if let Some(guard) = self.result_guard {
            self.check_result_after_drain(&mut body, context, guard);
        }
        // All actual root frames, accepted continuations and TLS have exited.
        // Logical owners retire here while imports remain legal. Original guest
        // memory and physical Native permits stay Store-owned through canonical
        // cleanup; post-return itself cannot call context/settle intrinsics.
        body.instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::I32Const(5))
            .instruction(&Instruction::I32Store(address(12)))
            .instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::Call(self.context_set))
            .instruction(&Instruction::I32Const(3))
            .instruction(&Instruction::GlobalSet(self.lifecycle))
            .instruction(&Instruction::LocalGet(context))
            .instruction(&Instruction::Call(self.reap))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::GlobalSet(self.lifecycle));
        for index in 0..self.results.len() as u32 {
            body.instruction(&Instruction::LocalGet(context + 1 + index));
        }
        body.instruction(&Instruction::End);
        body
    }
    fn capture_result(&self, body: &mut Function, context: u32, guard: CanonicalResultGuard) {
        // The one original i32 result is a statically proven BSS retarea.
        // Capture before finish: accepted callbacks may still run during drain.
        body.instruction(&Instruction::LocalGet(context + 1))
            .instruction(&Instruction::I32Const(guard.static_area as i32))
            .instruction(&Instruction::I32Ne);
        reject(body);
        let mut tag = address(0);
        tag.align = 0;
        body.instruction(&Instruction::LocalGet(context + 1))
            .instruction(&Instruction::I32Load8U(tag))
            .instruction(&Instruction::LocalSet(context + 2));
        for (offset, local) in [(4, context + 3), (8, context + 4)] {
            body.instruction(&Instruction::LocalGet(context + 1))
                .instruction(&Instruction::I32Load(address(offset)))
                .instruction(&Instruction::LocalSet(local));
        }
    }
    fn check_result_after_drain(
        &self,
        body: &mut Function,
        context: u32,
        guard: CanonicalResultGuard,
    ) {
        let mut tag = address(0);
        tag.align = 0;
        body.instruction(&Instruction::LocalGet(context + 1))
            .instruction(&Instruction::I32Load8U(tag))
            .instruction(&Instruction::LocalGet(context + 2))
            .instruction(&Instruction::I32Ne);
        reject(body);
        for (offset, local) in [(4, context + 3), (8, context + 4)] {
            body.instruction(&Instruction::LocalGet(context + 1))
                .instruction(&Instruction::I32Load(address(offset)))
                .instruction(&Instruction::LocalGet(local))
                .instruction(&Instruction::I32Ne);
            reject(body);
        }
        body.instruction(&Instruction::LocalGet(context + 2))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32GtU);
        reject(body);
        body.instruction(&Instruction::MemorySize(0))
            .instruction(&Instruction::I32Const(512))
            .instruction(&Instruction::I32GtU);
        reject(body);
        // Empty strings may use original dangling sentinel1 and are not freed
        // by the authenticated post body. Nonempty strings must outlive Root:
        // no Root/System-stack or private static/context storage is accepted.
        body.instruction(&Instruction::LocalGet(context + 4))
            .instruction(&Instruction::If(BlockType::Empty))
            .instruction(&Instruction::LocalGet(context + 3))
            .instruction(&Instruction::I32Const(guard.original_heap_low as i32))
            .instruction(&Instruction::I32LtU);
        reject(body);
        body.instruction(&Instruction::LocalGet(context + 3))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::LocalGet(context + 4))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Add)
            .instruction(&Instruction::MemorySize(0))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(65_536))
            .instruction(&Instruction::I64Mul)
            .instruction(&Instruction::I64GtU);
        reject(body);
        body.instruction(&Instruction::End);
    }
    fn system_closed(&self, body: &mut Function) {
        body.instruction(&Instruction::GlobalGet(
            self.system_scope.expect("canonical scope"),
        ));
        reject(body);
    }
    fn system_pointer(&self, body: &mut Function) {
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32Ne);
        reject(body);
    }
    fn realloc_wrapper(&self) -> Function {
        let mut body = Function::new([(1, ValType::I32)]);
        self.system_closed(&mut body);
        // Fresh input allocation and live import lowering both have zeroed
        // canonical context slots. Neither may create/install a Root context.
        body.instruction(&Instruction::GlobalGet(self.lifecycle))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32GtU);
        reject(&mut body);
        self.system_pointer(&mut body);
        body.instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::GlobalSet(self.system_scope.unwrap()));
        for index in 0..4 {
            body.instruction(&Instruction::LocalGet(index));
        }
        body.instruction(&Instruction::Call(
            self.cloned + 1 + u32::from(self.post_return.is_some()),
        ))
        .instruction(&Instruction::LocalSet(4));
        self.system_pointer(&mut body);
        body.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::GlobalSet(self.system_scope.unwrap()))
            .instruction(&Instruction::LocalGet(4))
            .instruction(&Instruction::End);
        body
    }
    fn post_return_wrapper(&self) -> Function {
        let (_, _, params) = self.post_return.as_ref().expect("selected post-return");
        let mut body = Function::new([]);
        self.system_closed(&mut body);
        body.instruction(&Instruction::GlobalGet(self.lifecycle))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        self.system_pointer(&mut body);
        body.instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::GlobalSet(self.system_scope.unwrap()))
            .instruction(&Instruction::I32Const(4))
            .instruction(&Instruction::GlobalSet(self.lifecycle));
        for index in 0..params.len() as u32 {
            body.instruction(&Instruction::LocalGet(index));
        }
        body.instruction(&Instruction::Call(self.cloned + 1));
        self.system_pointer(&mut body);
        body.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::GlobalSet(self.system_scope.unwrap()))
            .instruction(&Instruction::I32Const(5))
            .instruction(&Instruction::GlobalSet(self.lifecycle))
            .instruction(&Instruction::End);
        body
    }
    fn bootstrap_stack_access(&self, body: &mut Function, write: bool) {
        if let Some(scope) = self.system_scope {
            body.instruction(&Instruction::GlobalGet(scope))
                .instruction(&Instruction::If(BlockType::Empty));
            self.system_stack_access(body, write);
            body.instruction(&Instruction::End);
        }
        // Only pre-root bootstrap and the legal pre-return reaper may use this
        // original System stack fallback. No active child gets this fallback.
        body.instruction(&Instruction::GlobalGet(self.lifecycle))
            .instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::GlobalGet(self.lifecycle))
            .instruction(&Instruction::I32Const(3))
            .instruction(&Instruction::I32Eq)
            .instruction(&Instruction::I32Or)
            .instruction(&Instruction::Call(self.base.context_get))
            .instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::I32And)
            .instruction(&Instruction::If(BlockType::Empty));
        self.system_stack_access(body, write);
        body.instruction(&Instruction::End);
    }
    fn system_stack_access(&self, body: &mut Function, write: bool) {
        let pointer = if write { 0 } else { 1 };
        if !write {
            body.instruction(&Instruction::GlobalGet(self.base.stack_global))
                .instruction(&Instruction::LocalSet(pointer));
        }
        body.instruction(&Instruction::LocalGet(pointer))
            .instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And);
        reject(body);
        body.instruction(&Instruction::LocalGet(pointer))
            .instruction(&Instruction::I32Const(if self.system_scope.is_some() {
                self.high
            } else {
                self.low
            } as i32))
            .instruction(&Instruction::I32LtU);
        reject(body);
        body.instruction(&Instruction::LocalGet(pointer))
            .instruction(&Instruction::I32Const(self.base.stack_initial as i32))
            .instruction(&Instruction::I32GtU);
        reject(body);
        if write {
            body.instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::GlobalSet(self.base.stack_global));
        } else {
            body.instruction(&Instruction::LocalGet(pointer));
        }
        body.instruction(&Instruction::Return);
    }
}

struct RewriteRoot {
    plan: Root,
    next: u32,
    original: Option<Function>,
    original_post_return: Option<Function>,
    original_realloc: Option<Function>,
}
impl Reencode for RewriteRoot {
    type Error = &'static str;
    fn function_index(&mut self, index: u32) -> Result<u32, reencode::Error<Self::Error>> {
        // Ordinary calls/references retain original allocator/cleanup semantics.
        // Only the actual canonical exports enter the guarded System wrappers.
        if self.plan.realloc.is_some_and(|(target, _)| target == index) {
            return Ok(self.plan.cloned + 1 + u32::from(self.plan.post_return.is_some()));
        }
        if self
            .plan
            .post_return
            .as_ref()
            .is_some_and(|(target, _, _)| *target == index)
        {
            return Ok(self.plan.cloned + 1);
        }
        Ok(index)
    }
    fn parse_export(
        &mut self,
        out: &mut wasm_encoder::ExportSection,
        export: wasmparser::Export<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        if export.kind == ExternalKind::Func
            && (self
                .plan
                .realloc
                .is_some_and(|(target, _)| target == export.index)
                || self
                    .plan
                    .post_return
                    .as_ref()
                    .is_some_and(|(target, _, _)| *target == export.index))
        {
            out.export(export.name, wasm_encoder::ExportKind::Func, export.index);
            return Ok(());
        }
        reencode::utils::parse_export(self, out, export)
    }
    fn parse_global_section(
        &mut self,
        section: &mut GlobalSection,
        reader: wasmparser::GlobalSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_global_section(self, section, reader)?;
        section.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(0),
        );
        if self.plan.system_scope.is_some() {
            section.global(
                GlobalType {
                    val_type: ValType::I32,
                    mutable: true,
                    shared: false,
                },
                &ConstExpr::i32_const(0),
            );
        }
        Ok(())
    }
    fn parse_function_section(
        &mut self,
        section: &mut FunctionSection,
        reader: wasmparser::FunctionSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, section, reader)?;
        section.function(self.plan.ty);
        if let Some((_, ty, _)) = self.plan.post_return.as_ref() {
            section.function(*ty);
        }
        if let Some((_, ty)) = self.plan.realloc {
            section.function(ty);
        }
        Ok(())
    }
    fn parse_function_body(
        &mut self,
        code: &mut CodeSection,
        body: wasmparser::FunctionBody<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let index = self.plan.base.imported_functions + self.next;
        self.next += 1;
        let mut function = self.new_function_with_parsed_locals(&body)?;
        if index == self.plan.get || index == self.plan.set {
            self.plan
                .bootstrap_stack_access(&mut function, index == self.plan.set);
        }
        let mut reader = body.get_operators_reader()?;
        while !reader.eof() {
            function.instruction(&self.instruction(reader.read()?)?);
        }
        if index == self.plan.root {
            self.original = Some(function);
            code.function(&self.plan.wrapper());
        } else if self
            .plan
            .post_return
            .as_ref()
            .is_some_and(|(target, _, _)| *target == index)
        {
            self.original_post_return = Some(function);
            code.function(&self.plan.post_return_wrapper());
        } else if self.plan.realloc.is_some_and(|(target, _)| target == index) {
            self.original_realloc = Some(function);
            code.function(&self.plan.realloc_wrapper());
        } else {
            code.function(&function);
        }
        Ok(())
    }
    fn parse_code_section(
        &mut self,
        code: &mut CodeSection,
        reader: wasmparser::CodeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, code, reader)?;
        code.function(
            self.original
                .as_ref()
                .ok_or(reencode::Error::UserError("rust-root-body-missing"))?,
        );
        if self.plan.post_return.is_some() {
            code.function(
                self.original_post_return
                    .as_ref()
                    .ok_or(reencode::Error::UserError(
                        "rust-root-post-return-body-missing",
                    ))?,
            );
        }
        if self.plan.realloc.is_some() {
            code.function(
                self.original_realloc
                    .as_ref()
                    .ok_or(reencode::Error::UserError("rust-root-realloc-body-missing"))?,
            );
        }
        Ok(())
    }
}

/// Wire one source-authenticated root, preserving its actual function index
/// and all numeric flat values. Support hooks and whole-component routing still
/// need their consuming sysroot qualification; receipts cannot enable the host.
pub fn transform_owned_root_bootstrap(
    input: &[u8],
    expected_preimage: [u8; 32],
    thread: &ThreadEntryReceipt,
) -> Result<(Vec<u8>, RootReceipt), &'static str> {
    transform(input, expected_preimage, thread, None, None, None)
}

/// Preserve original physical Store ownership through canonical cleanup, with
/// logical Root retirement before return and import-free System ABI scopes.
/// This does not authenticate those bodies or enable a standard runtime.
pub fn transform_owned_canonical_root_bootstrap(
    input: &[u8],
    expected_preimage: [u8; 32],
    thread: &ThreadEntryReceipt,
    post_return: Option<&str>,
    realloc: Option<&str>,
) -> Result<(Vec<u8>, RootReceipt), &'static str> {
    if post_return.is_some_and(|s| !s.starts_with("cabi_post_") || s.len() > 768)
        || realloc.is_some_and(|s| s != "cabi_realloc")
    {
        return Err("rust-root-explicit-canonical-export-name");
    }
    transform(input, expected_preimage, thread, post_return, realloc, None)
}

/// Install the dynamic result guard after the owning compiler has proved the
/// original WIT layout, every public return, disjoint private data and complete
/// post/allocator closure. This source API does not grant those authorities.
pub fn transform_owned_guarded_canonical_root_bootstrap(
    input: &[u8],
    expected_preimage: [u8; 32],
    thread: &ThreadEntryReceipt,
    post_return: &str,
    realloc: &str,
    guard: CanonicalResultGuard,
) -> Result<(Vec<u8>, RootReceipt), &'static str> {
    if !post_return.starts_with("cabi_post_")
        || post_return.len() > 768
        || realloc != "cabi_realloc"
    {
        return Err("rust-root-explicit-canonical-export-name");
    }
    transform(
        input,
        expected_preimage,
        thread,
        Some(post_return),
        Some(realloc),
        Some(guard),
    )
}

fn transform(
    input: &[u8],
    expected_preimage: [u8; 32],
    thread: &ThreadEntryReceipt,
    post_return: Option<&str>,
    realloc: Option<&str>,
    result_guard: Option<CanonicalResultGuard>,
) -> Result<(Vec<u8>, RootReceipt), &'static str> {
    let original_digest = Sha256::digest(input).into();
    if original_digest != expected_preimage || original_digest != thread.stack.derived_digest {
        return Err("rust-root-thread-transform-preimage-mismatch");
    }
    let mut root = inspect(input, thread, post_return, realloc)?;
    if let Some(guard) = result_guard {
        if root.results != [ValType::I32]
            || root
                .post_return
                .as_ref()
                .is_none_or(|(_, _, params)| params != &[ValType::I32])
            || guard.static_area == 0
            || !guard.static_area.is_multiple_of(4)
            || guard
                .static_area
                .checked_add(12)
                .is_none_or(|end| end > root.low)
            || guard.original_heap_low != root.base.stack_initial
        {
            return Err("rust-root-canonical-result-guard-layout-or-original-bounds");
        }
        root.result_guard = Some(guard);
    }
    let mut receipt = RootReceipt {
        original_digest,
        derived_digest: [0; 32],
        root_function: root.root,
        original_rust_body: root.cloned,
        bootstrap_function: root.boot,
        finish_function: root.finish,
        reap_function: root.reap,
        lifecycle_global: root.lifecycle,
        root_stack_low: root.low,
        root_stack_high: root.high,
        canonical_system_stack_low: root.system_scope.map(|_| root.high),
        canonical_system_stack_high: root.system_scope.map(|_| root.base.stack_initial),
        canonical_system_scope_global: root.system_scope,
        canonical_system_closure_functions: root.canonical_closure.len() as u32,
        canonical_result_area: result_guard.map(|guard| guard.static_area),
        canonical_result_guard_installed: result_guard.is_some(),
        post_return_function: root.post_return.as_ref().map(|(function, _, _)| *function),
        original_post_return_body: root.post_return.as_ref().map(|_| root.cloned + 1),
        realloc_function: root.realloc.map(|(function, _)| function),
        original_realloc_body: root
            .realloc
            .map(|_| root.cloned + 1 + u32::from(root.post_return.is_some())),
        root_export_bootstrap_qualified: false,
        canonical_creation_enabled: false,
    };
    let mut rewrite = RewriteRoot {
        plan: root,
        next: 0,
        original: None,
        original_post_return: None,
        original_realloc: None,
    };
    let mut module = Module::new();
    rewrite
        .parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "rust-root-bootstrap-reencode-failed")?;
    let output = module.finish();
    if output.len() > MAX_BYTES {
        return Err("rust-stack-derived-module-byte-limit");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "rust-root-bootstrap-derived-module-invalid")?;
    receipt.derived_digest = Sha256::digest(&output).into();
    Ok((output, receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        ElementSection, Elements, EntityType, ExportKind, ExportSection, ImportSection,
        MemorySection, MemoryType, TableSection, TableType,
    };

    fn fixture(low: bool, alias: bool) -> Vec<u8> {
        canonical_fixture(low, alias, false)
    }
    fn canonical_fixture(low: bool, alias: bool, canonical: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        types
            .ty()
            .function([ValType::I32, ValType::I32], [ValType::I32]);
        types
            .ty()
            .function([ValType::I64, ValType::I64, ValType::I32], []);
        types
            .ty()
            .function([ValType::I32, ValType::I64], [ValType::I64, ValType::I32]);
        if canonical {
            types.ty().function([ValType::I64, ValType::I32], []);
            types.ty().function([ValType::I32; 4], [ValType::I32]);
        }
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", "[context-set-1]", EntityType::Function(1));
        imports.import("$root", "[thread-new-indirect-v0]", EntityType::Function(2));
        imports.import(
            "latent:runtime-native/threads@0.1.0",
            "start",
            EntityType::Function(3),
        );
        module.section(&imports);
        let mut functions = FunctionSection::new();
        for ty in [1, 4, 2, 1, 1] {
            functions.function(ty);
        }
        if canonical {
            functions.function(5);
            functions.function(6);
        }
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType {
            element_type: wasm_encoder::RefType::FUNCREF,
            table64: false,
            minimum: 1,
            maximum: Some(1),
            shared: false,
        });
        module.section(&tables);
        let mut memory = MemorySection::new();
        memory.memory(MemoryType {
            minimum: 4,
            maximum: Some(4),
            memory64: false,
            shared: false,
            page_size_log2: None,
        });
        module.section(&memory);
        let mut globals = GlobalSection::new();
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(if canonical { 196_608 } else { 131_072 }),
        );
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: false,
                shared: false,
            },
            &ConstExpr::i32_const(65_536),
        );
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        if low {
            exports.export("__stack_low", ExportKind::Global, 1);
        }
        exports.export("__indirect_function_table", ExportKind::Table, 0);
        exports.export("__lsf_rust_owned_thread_entry", ExportKind::Func, 4);
        for (name, index) in [
            (ROOT, 5),
            (BOOT, 6),
            (FINISH, 7),
            (REAP, if alias { 7 } else { 8 }),
        ] {
            exports.export(name, ExportKind::Func, index);
        }
        if canonical {
            exports.export(
                "cabi_post_examples:ordinary/run@1.0.0#run",
                ExportKind::Func,
                9,
            );
            exports.export("cabi_realloc", ExportKind::Func, 10);
        }
        module.section(&exports);
        let mut elements = ElementSection::new();
        elements.active(
            Some(0),
            &ConstExpr::i32_const(0),
            Elements::Functions(Cow::Borrowed(&[4])),
        );
        module.section(&elements);
        // These are encoded stand-ins for transform/routing checks, not Rust
        // hook execution. The separate native harness executes the TLS source.
        let mut code = CodeSection::new();
        let mut entry = Function::new([]);
        entry.instruction(&Instruction::End);
        code.function(&entry);
        let mut root = Function::new([]);
        root.instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::End);
        code.function(&root);
        let mut boot = Function::new([]);
        boot.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::End);
        code.function(&boot);
        for _ in 0..2 {
            let mut body = Function::new([]);
            body.instruction(&Instruction::End);
            code.function(&body);
        }
        if canonical {
            // Encoded mechanism fixtures only: not execution of an original
            // allocator, bindgen post-return or selected Rust runtime.
            let mut post = Function::new([]);
            post.instruction(&Instruction::GlobalGet(0))
                .instruction(&Instruction::Drop)
                .instruction(&Instruction::End);
            code.function(&post);
            let mut realloc = Function::new([]);
            realloc
                .instruction(&Instruction::LocalGet(3))
                .instruction(&Instruction::End);
            code.function(&realloc);
        }
        module.section(&code);
        module.finish()
    }
    fn digest(input: &[u8]) -> [u8; 32] {
        Sha256::digest(input).into()
    }
    fn result_fixture() -> Vec<u8> {
        struct ResultAbi {
            next: u32,
        }
        impl Reencode for ResultAbi {
            type Error = &'static str;
            fn parse_function_section(
                &mut self,
                out: &mut FunctionSection,
                reader: wasmparser::FunctionSectionReader<'_>,
            ) -> Result<(), reencode::Error<Self::Error>> {
                for (index, ty) in reader.into_iter().enumerate() {
                    out.function(match index {
                        1 => 0, // Original root now returns one static i32 area.
                        5 => 1, // Original post consumes that i32 area.
                        _ => ty?,
                    });
                }
                Ok(())
            }
            fn parse_function_body(
                &mut self,
                out: &mut CodeSection,
                body: wasmparser::FunctionBody<'_>,
            ) -> Result<(), reencode::Error<Self::Error>> {
                let index = self.next;
                self.next += 1;
                if index == 5 {
                    let mut function = Function::new([]);
                    function
                        .instruction(&Instruction::I32Const(512))
                        .instruction(&Instruction::End);
                    out.function(&function);
                } else if index == 9 {
                    let mut function = Function::new([]);
                    function
                        .instruction(&Instruction::LocalGet(0))
                        .instruction(&Instruction::Drop)
                        .instruction(&Instruction::End);
                    out.function(&function);
                } else {
                    reencode::utils::parse_function_body(self, out, body)?;
                }
                Ok(())
            }
        }
        let mut rewrite = ResultAbi { next: 4 };
        let mut module = Module::new();
        rewrite
            .parse_core_module(
                &mut module,
                Parser::new(0),
                &canonical_fixture(true, false, true),
            )
            .unwrap();
        module.finish()
    }
    fn bodies(input: &[u8]) -> Vec<wasmparser::FunctionBody<'_>> {
        Parser::new(0)
            .parse_all(input)
            .filter_map(|payload| match payload.unwrap() {
                Payload::CodeSectionEntry(body) => Some(body),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn root_attach_finish_detach_and_reap_preserve_original_index_and_numeric_values() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (output, receipt) =
            transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        assert_eq!((receipt.root_function, receipt.original_rust_body), (5, 12));
        assert_eq!(
            (receipt.root_stack_low, receipt.root_stack_high),
            (65_536, 131_072)
        );
        let bodies = bodies(&output);
        let mut reader = bodies[1].get_operators_reader().unwrap();
        let mut calls = Vec::new();
        let mut writes = Vec::new();
        let mut results = Vec::new();
        let mut loads = Vec::new();
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
        let root_type = Parser::new(0)
            .parse_all(&output)
            .find_map(|payload| match payload.unwrap() {
                Payload::TypeSection(types) => {
                    Some(types.into_iter_err_on_gc_types().nth(4).unwrap().unwrap())
                }
                _ => None,
            })
            .unwrap();
        assert_eq!(
            root_type.params(),
            [wasmparser::ValType::I32, wasmparser::ValType::I64]
        );
        assert_eq!(
            root_type.results(),
            [wasmparser::ValType::I64, wasmparser::ValType::I32]
        );
        Validator::new().validate_all(&output).unwrap();
        assert!(!receipt.root_export_bootstrap_qualified && !receipt.canonical_creation_enabled);
    }

    #[test]
    fn shared_stack_fallback_is_confined_to_pre_root_and_final_system_reaper() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (output, _) =
            transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        let bodies = bodies(&output);
        for index in [5, 6] {
            // defined helper indices9 and10, imported functions4
            let mut reader = bodies[index].get_operators_reader().unwrap();
            let mut prefix = Vec::new();
            for _ in 0..6 {
                prefix.push(format!("{:?}", reader.read().unwrap()));
            }
            assert_eq!(
                prefix,
                [
                    "GlobalGet { global_index: 2 }",
                    "I32Eqz",
                    "GlobalGet { global_index: 2 }",
                    "I32Const { value: 3 }",
                    "I32Eq",
                    "I32Or"
                ]
            );
            let mut calls = Vec::new();
            let mut returns = 0;
            while !reader.eof() {
                match reader.read().unwrap() {
                    Operator::Call { function_index } => calls.push(function_index),
                    Operator::Return => returns += 1,
                    _ => {}
                }
            }
            assert_eq!(calls, [0, 0]); // fallback also requires a null canonical context
            assert_eq!(returns, 1);
        }
    }

    #[test]
    fn missing_linker_range_or_aliased_support_hooks_never_emit_bootstrap() {
        for (low, alias, expected) in [
            (false, false, "rust-root-linker-stack-low-missing"),
            (true, true, "rust-root-support-function-alias-denied"),
        ] {
            let input = fixture(low, alias);
            let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
            assert_eq!(
                transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(),
                expected
            );
        }
    }

    #[test]
    fn stale_chain_and_forged_stack_layout_receipts_are_rejected() {
        let input = fixture(true, false);
        let (threaded, mut thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        assert_eq!(
            transform_owned_root_bootstrap(&threaded, digest(&input), &thread).unwrap_err(),
            "rust-root-thread-transform-preimage-mismatch"
        );
        thread.stack.original_initial_stack_pointer -= 16;
        assert_eq!(
            transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(),
            "rust-root-thread-receipt-layout"
        );
        thread.stack.original_initial_stack_pointer += 16;
        thread.stack.helper_get_function = thread.entry_function;
        assert_eq!(
            transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap_err(),
            "rust-root-thread-helper-body-mismatch"
        );
    }

    #[test]
    fn root_and_child_admission_transform_chain_validates_without_enabling_component_threads() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (rooted, root) =
            transform_owned_root_bootstrap(&threaded, digest(&threaded), &thread).unwrap();
        let (output, admission) =
            transform_owned_thread_admission(&rooted, digest(&rooted)).unwrap();
        assert_eq!(root.derived_digest, admission.original_digest);
        Validator::new().validate_all(&output).unwrap();
        assert!(!admission.component_routing_authenticated);
        assert!(!admission.canonical_creation_enabled);
        assert!(!root.root_export_bootstrap_qualified);
    }

    #[test]
    fn canonical_post_return_keeps_root_context_until_actual_cleanup_returns() {
        // Historical case ID retained. Canonical cleanup retains the original
        // Store-owned backing/physical permits, not installed context slots.
        let input = canonical_fixture(true, false, true);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let (output, receipt) = transform_owned_canonical_root_bootstrap(
            &threaded,
            digest(&threaded),
            &thread,
            Some("cabi_post_examples:ordinary/run@1.0.0#run"),
            Some("cabi_realloc"),
        )
        .unwrap();
        assert_eq!(receipt.post_return_function, Some(9));
        assert_eq!(receipt.realloc_function, Some(10));
        assert_eq!(
            receipt.original_post_return_body,
            Some(receipt.original_rust_body + 1)
        );
        assert_eq!(
            receipt.original_realloc_body,
            Some(receipt.original_rust_body + 2)
        );
        let bodies = bodies(&output);
        let calls = |body: &wasmparser::FunctionBody<'_>| {
            let mut reader = body.get_operators_reader().unwrap();
            let mut calls = Vec::new();
            while !reader.eof() {
                if let Operator::Call { function_index } = reader.read().unwrap() {
                    calls.push(function_index);
                }
            }
            calls
        };
        let root_calls = calls(&bodies[1]);
        let root_ops = bodies[1]
            .get_operators_reader()
            .unwrap()
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let boot = root_ops
            .iter()
            .position(|op| {
                matches!(op,
            Operator::Call { function_index } if *function_index == receipt.bootstrap_function)
            })
            .unwrap();
        assert!(matches!(
            &root_ops[boot - 2..boot],
            [
                Operator::I32Const { value: 65_536 },
                Operator::I32Const { value: 131_072 }
            ]
        ));
        assert_eq!(
            root_ops
                .windows(3)
                .filter(|ops| matches!(
                    ops,
                    [
                        Operator::GlobalGet { global_index: 0 },
                        Operator::I32Const { value: 196_608 },
                        Operator::I32Ne
                    ]
                ))
                .count(),
            2
        );
        assert!(root_calls.contains(&receipt.finish_function));
        assert!(root_calls.contains(&receipt.reap_function));
        assert!(
            root_calls
                .iter()
                .position(|index| *index == receipt.finish_function)
                < root_calls
                    .iter()
                    .position(|index| *index == receipt.reap_function)
        );
        assert_eq!(
            (receipt.root_stack_low, receipt.root_stack_high),
            (65_536, 131_072)
        );
        assert_eq!(
            (
                receipt.canonical_system_stack_low,
                receipt.canonical_system_stack_high
            ),
            (Some(131_072), Some(196_608))
        );
        let post_calls = calls(&bodies[5]);
        assert_eq!(post_calls, [receipt.original_post_return_body.unwrap()]);
        let realloc_calls = calls(&bodies[6]);
        assert_eq!(realloc_calls, [receipt.original_realloc_body.unwrap()]);
        assert!(receipt.canonical_system_closure_functions >= 3);
        let (admitted, admission) =
            transform_owned_thread_admission(&output, digest(&output)).unwrap();
        Validator::new().validate_all(&admitted).unwrap();
        assert!(!receipt.canonical_creation_enabled && !receipt.root_export_bootstrap_qualified);
        assert!(
            !admission.component_routing_authenticated && !admission.canonical_creation_enabled
        );
        // Exercise the actual emitted guarded wrapper, not a copied guard
        // model. Native validation also checks its additional locals/branches.
        // This encoded fixture is not an original Rust allocator or runtime.
        let input = result_fixture();
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        let guard = CanonicalResultGuard {
            static_area: 512,
            original_heap_low: 196_608,
        };
        let (guarded, receipt) = transform_owned_guarded_canonical_root_bootstrap(
            &threaded,
            digest(&threaded),
            &thread,
            "cabi_post_examples:ordinary/run@1.0.0#run",
            "cabi_realloc",
            guard,
        )
        .unwrap();
        Validator::new().validate_all(&guarded).unwrap();
        assert!(receipt.canonical_result_guard_installed);
        assert_eq!(receipt.canonical_result_area, Some(512));
        let guarded_bodies = self::bodies(&guarded);
        let ops = guarded_bodies[1]
            .get_operators_reader()
            .unwrap()
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let finish = ops
            .iter()
            .position(|op| {
                matches!(op,
            Operator::Call { function_index } if *function_index == receipt.finish_function)
            })
            .unwrap();
        let reap = ops
            .iter()
            .position(|op| {
                matches!(op,
            Operator::Call { function_index } if *function_index == receipt.reap_function)
            })
            .unwrap();
        assert!(
            ops[..finish]
                .iter()
                .any(|op| matches!(op, Operator::I32Load8U { .. }))
        );
        assert!(
            ops[finish..reap]
                .iter()
                .any(|op| matches!(op, Operator::I32Load8U { .. }))
        );
        for offset in [4, 8] {
            assert!(ops[..finish].iter().any(|op| matches!(op,
                Operator::I32Load { memarg } if memarg.offset == offset)));
            assert!(ops[finish..reap].iter().any(|op| matches!(op,
                Operator::I32Load { memarg } if memarg.offset == offset)));
        }
        assert!(ops[finish..reap].windows(3).any(|ops| matches!(
            ops,
            [
                Operator::LocalGet { local_index: 3 },
                Operator::I32Const { value: 196_608 },
                Operator::I32LtU
            ]
        )));
        assert!(
            ops[finish..reap]
                .iter()
                .any(|op| matches!(op, Operator::I64Add))
        );
        assert!(
            ops[finish..reap]
                .iter()
                .any(|op| matches!(op, Operator::I64GtU))
        );
        for bad in [
            CanonicalResultGuard {
                static_area: 0,
                ..guard
            },
            CanonicalResultGuard {
                static_area: 65_532,
                ..guard
            },
            CanonicalResultGuard {
                static_area: 513,
                ..guard
            },
            CanonicalResultGuard {
                original_heap_low: 131_072,
                ..guard
            },
        ] {
            assert_eq!(
                transform_owned_guarded_canonical_root_bootstrap(
                    &threaded,
                    digest(&threaded),
                    &thread,
                    "cabi_post_examples:ordinary/run@1.0.0#run",
                    "cabi_realloc",
                    bad,
                )
                .unwrap_err(),
                "rust-root-canonical-result-guard-layout-or-original-bounds"
            );
        }
    }

    #[test]
    fn canonical_cleanup_names_and_actual_exports_are_required() {
        let input = fixture(true, false);
        let (threaded, thread) = transform_owned_thread_entry(&input, digest(&input)).unwrap();
        assert_eq!(
            transform_owned_canonical_root_bootstrap(
                &threaded,
                digest(&threaded),
                &thread,
                Some("ordinary-user-cleanup"),
                None,
            )
            .unwrap_err(),
            "rust-root-explicit-canonical-export-name"
        );
        assert_eq!(
            transform_owned_canonical_root_bootstrap(
                &threaded,
                digest(&threaded),
                &thread,
                Some("cabi_post_examples:ordinary/run@1.0.0#run"),
                Some("cabi_realloc"),
            )
            .unwrap_err(),
            "rust-root-support-exports-or-bounds"
        );
        struct HookCall {
            next: u32,
            target: u32,
        }
        impl Reencode for HookCall {
            type Error = &'static str;
            fn parse_function_body(
                &mut self,
                out: &mut CodeSection,
                body: wasmparser::FunctionBody<'_>,
            ) -> Result<(), reencode::Error<Self::Error>> {
                let index = self.next;
                self.next += 1;
                if index != 10 {
                    return reencode::utils::parse_function_body(self, out, body);
                }
                let mut function = self.new_function_with_parsed_locals(&body)?;
                function.instruction(&Instruction::I32Const(0));
                match self.target {
                    5 => {
                        function.instruction(&Instruction::I64Const(0));
                    }
                    6 => {
                        function.instruction(&Instruction::I32Const(0));
                    }
                    _ => {}
                }
                function.instruction(&Instruction::Call(self.target));
                if self.target <= 6 {
                    function.instruction(&Instruction::Drop);
                }
                if self.target == 5 {
                    function.instruction(&Instruction::Drop);
                }
                let mut ops = body.get_operators_reader()?;
                while !ops.eof() {
                    function.instruction(&self.instruction(ops.read()?)?);
                }
                out.function(&function);
                Ok(())
            }
        }
        // Each source fixture hook is otherwise import-free. An ordinary
        // canonical allocator must still be unable to reset/drain/reap a Root.
        for target in 5..=8 {
            let original = canonical_fixture(true, false, true);
            let mut poisoned = Module::new();
            HookCall { next: 4, target }
                .parse_core_module(&mut poisoned, Parser::new(0), &original)
                .unwrap();
            let poisoned = poisoned.finish();
            let (threaded, thread) =
                transform_owned_thread_entry(&poisoned, digest(&poisoned)).unwrap();
            assert_eq!(
                transform_owned_canonical_root_bootstrap(
                    &threaded,
                    digest(&threaded),
                    &thread,
                    Some("cabi_post_examples:ordinary/run@1.0.0#run"),
                    Some("cabi_realloc")
                )
                .unwrap_err(),
                "rust-root-canonical-lifecycle-hook-not-qualified"
            );
        }
    }
}
