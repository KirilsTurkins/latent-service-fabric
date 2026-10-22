//! C canonical allocation/initialization/post-return scopes. This source
//! transform does not enable an engine profile or change the ordinary C ABI.
use super::*;
use std::collections::{BTreeMap, BTreeSet};
use wasm_encoder::{ConstExpr, ExportSection, GlobalSection, GlobalType};

const INITIALIZE: &str = "_initialize";
const INITIALIZE_BODY: &str = "__lsf_c_canonical_initialize_body";
const REALLOC: &str = "cabi_realloc";
const GUARD: i32 = c_root::SYSTEM_STACK_LOW as i32;
const HIGH: i32 = c_root::SYSTEM_STACK_HIGH as i32;
const MAX_EDGES: usize = 65_536;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CCanonicalAbiReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub root: c_root::CRootReceipt,
    pub initialize_wrapper: u32,
    pub realloc_wrapper: u32,
    pub post_return_wrapper: u32,
    pub system_closure_functions: u32,
    pub system_scope_reads_tls: bool,
    pub canonical_component_authenticated: bool,
    pub runtime_profile_qualified: bool,
}

#[derive(Clone)]
struct Signature {
    ty: u32,
    params: Vec<ValType>,
    results: Vec<ValType>,
}

struct Abi {
    base: Plan,
    signatures: Vec<Signature>,
    init: u32,
    realloc: u32,
    post: u32,
    root_entry: u32,
    root_lifecycle: u32,
    system_scope: u32,
    initialized: u32,
    post_done: u32,
    first_wrapper: u32,
    stack_get: u32,
    stack_set: u32,
    tls_get: u32,
    root_tls: u32,
    heap_base: u32,
    closure: BTreeSet<u32>,
    post_name: String,
}

fn flat(ty: wasmparser::ValType) -> Result<ValType, &'static str> {
    Ok(match ty {
        wasmparser::ValType::I32 => ValType::I32,
        wasmparser::ValType::I64 => ValType::I64,
        wasmparser::ValType::F32 => ValType::F32,
        wasmparser::ValType::F64 => ValType::F64,
        _ => return Err("c-abi-flat-numeric-value-only"),
    })
}

fn reject(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty))
        .instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}

// Keep the original initializer function and body; only its export becomes
// private during the already-authenticated scalar root derivation. The final
// ABI transform restores the actual encoder-facing name to its fixed wrapper.
struct InitializeName;
impl Reencode for InitializeName {
    type Error = &'static str;
    fn parse_export_section(
        &mut self,
        out: &mut ExportSection,
        reader: wasmparser::ExportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let mut found = false;
        for row in reader {
            let row = row.map_err(|_| reencode::Error::UserError("c-abi-export-parse"))?;
            if row.name == INITIALIZE_BODY {
                return Err(reencode::Error::UserError(
                    "c-abi-reserved-initializer-name",
                ));
            }
            if row.name == INITIALIZE {
                if found || row.kind != ExternalKind::Func {
                    return Err(reencode::Error::UserError(
                        "c-abi-single-reactor-initializer",
                    ));
                }
                found = true;
            }
            out.export(
                if row.name == INITIALIZE {
                    INITIALIZE_BODY
                } else {
                    row.name
                },
                self.export_kind(row.kind)?,
                row.index,
            );
        }
        if !found {
            return Err(reencode::Error::UserError(
                "c-abi-reactor-initializer-required",
            ));
        }
        Ok(())
    }
}

impl Abi {
    fn inspect(
        input: &[u8],
        public: &str,
        original: &Plan,
        root_tls: u32,
    ) -> Result<Self, &'static str> {
        let base = plan(input)?;
        let mut types = Vec::new();
        let mut functions = Vec::new();
        let mut exports = BTreeMap::new();
        let mut globals = 0;
        let mut global_values = Vec::new();
        for payload in Parser::new(0).parse_all(input) {
            match payload.map_err(|_| "c-abi-core-parse")? {
                Payload::TypeSection(reader) => {
                    for ty in reader.into_iter_err_on_gc_types() {
                        let ty = ty.map_err(|_| "c-abi-type")?;
                        types.push((ty.params().to_vec(), ty.results().to_vec()));
                    }
                }
                Payload::FunctionSection(reader) => {
                    for ty in reader {
                        functions.push(ty.map_err(|_| "c-abi-function-type")?);
                    }
                }
                Payload::ExportSection(reader) => {
                    for row in reader {
                        let row = row.map_err(|_| "c-abi-export")?;
                        if exports
                            .insert(row.name.to_owned(), (row.kind, row.index))
                            .is_some()
                        {
                            return Err("c-abi-duplicate-export");
                        }
                    }
                }
                Payload::GlobalSection(reader) => {
                    globals = reader.count();
                    for global in reader {
                        let global = global.map_err(|_| "c-abi-global")?;
                        let mut ops = global.init_expr.get_operators_reader();
                        let value = match ops.read().map_err(|_| "c-abi-global-value")? {
                            Operator::I32Const { value }
                                if matches!(ops.read(), Ok(Operator::End)) && ops.eof() =>
                            {
                                Some(value as u32)
                            }
                            _ => None,
                        };
                        global_values.push((global.ty, value));
                    }
                }
                _ => {}
            }
        }
        if globals < 1
            || globals > MAX_FUNCTIONS - 3
            || base.imported_functions + base.function_count > MAX_FUNCTIONS - 3
        {
            return Err("c-abi-global-or-function-bound");
        }
        let mut signatures = Vec::new();
        for ty in functions {
            let (params, results) = types.get(ty as usize).ok_or("c-abi-type-index")?;
            if params.len() > 16 || results.len() > 16 {
                return Err("c-abi-flat-signature-bound");
            }
            signatures.push(Signature {
                ty,
                params: params.iter().copied().map(flat).collect::<Result<_, _>>()?,
                results: results
                    .iter()
                    .copied()
                    .map(flat)
                    .collect::<Result<_, _>>()?,
            });
        }
        let function = |name: &str| -> Result<u32, &'static str> {
            let (kind, index) = *exports.get(name).ok_or("c-abi-required-export-missing")?;
            if kind != ExternalKind::Func
                || index < base.imported_functions
                || index - base.imported_functions >= signatures.len() as u32
            {
                return Err("c-abi-defined-function-required");
            }
            Ok(index)
        };
        let init = function(INITIALIZE_BODY)?;
        let realloc = function(REALLOC)?;
        let post_name = format!("cabi_post_{public}");
        let post = function(&post_name)?;
        let root = function(public)?;
        let (kind, index) = *exports
            .get("__heap_base")
            .ok_or("c-abi-heap-base-required")?;
        let (ty, heap_base) = *global_values
            .get(index as usize)
            .ok_or("c-abi-heap-base-index")?;
        if kind != ExternalKind::Global
            || ty.mutable
            || ty.shared
            || ty.content_type != wasmparser::ValType::I32
        {
            return Err("c-abi-constant-heap-base");
        }
        let heap_base = heap_base.ok_or("c-abi-constant-heap-base")?;
        if [init, realloc, post, root]
            .into_iter()
            .collect::<BTreeSet<_>>()
            .len()
            != 4
        {
            return Err("c-abi-entry-alias");
        }
        let sig = |index: u32| &signatures[(index - base.imported_functions) as usize];
        if !sig(init).params.is_empty()
            || !sig(init).results.is_empty()
            || sig(realloc).params != [ValType::I32; 4]
            || sig(realloc).results != [ValType::I32]
            || sig(post).params != sig(root).results
            || !sig(post).results.is_empty()
        {
            return Err("c-abi-generator-signatures");
        }
        let mut abi = Self {
            stack_get: original.imported_functions + original.function_count + 2,
            stack_set: original.imported_functions + original.function_count + 3,
            tls_get: original.imported_functions + original.function_count + 4,
            root_tls,
            heap_base,
            first_wrapper: base.imported_functions + base.function_count,
            root_lifecycle: globals - 1,
            system_scope: globals,
            initialized: globals + 1,
            post_done: globals + 2,
            base,
            signatures,
            init,
            realloc,
            post,
            root_entry: root,
            closure: BTreeSet::new(),
            post_name,
        };
        abi.system_closure(input)?;
        Ok(abi)
    }

    fn system_closure(&mut self, input: &[u8]) -> Result<(), &'static str> {
        let mut calls = BTreeMap::<u32, Vec<u32>>::new();
        let mut index = self.base.imported_functions;
        let mut edges = 0;
        for payload in Parser::new(0).parse_all(input) {
            if let Payload::CodeSectionEntry(body) = payload.map_err(|_| "c-abi-closure-parse")? {
                let mut targets = Vec::new();
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "c-abi-closure-operators")?;
                let mut forbidden = false;
                while !ops.eof() {
                    match ops.read().map_err(|_| "c-abi-closure-operator")? {
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
                // Store a sentinel in unreachable-from-system functions rather
                // than rejecting normal user callbacks in the original app.
                if forbidden {
                    targets.push(u32::MAX);
                }
                if edges > MAX_EDGES {
                    return Err("c-abi-direct-call-edge-bound");
                }
                calls.insert(index, targets);
                index += 1;
            }
        }
        for root in [self.init, self.realloc, self.post] {
            let mut pending = vec![root];
            let mut visited = BTreeSet::new();
            while let Some(index) = pending.pop() {
                if !visited.insert(index) {
                    continue;
                }
                self.closure.insert(index);
                if index == self.tls_get {
                    if root == self.realloc {
                        return Err("c-abi-live-realloc-tls-alias-not-qualified");
                    }
                    continue;
                }
                // System stack helpers do not consult context slots. Original
                // init/post TLS access remains outside all live C frames.
                if index == self.stack_get || index == self.stack_set {
                    continue;
                }
                if index < self.base.imported_functions {
                    return Err("c-abi-system-host-or-thread-import");
                }
                let targets = calls
                    .get(&index)
                    .ok_or("c-abi-system-indirect-or-invalid-target")?;
                if targets.contains(&u32::MAX) {
                    return Err("c-abi-system-indirect-or-reference-call");
                }
                pending.extend(targets.iter().copied());
            }
        }
        Ok(())
    }

    fn signature(&self, function: u32) -> &Signature {
        &self.signatures[(function - self.base.imported_functions) as usize]
    }

    fn stack_pointer(&self, body: &mut Function) {
        body.instruction(&Instruction::GlobalGet(self.base.stack_global))
            .instruction(&Instruction::I32Const(HIGH))
            .instruction(&Instruction::I32Ne);
        reject(body);
    }
    fn mode_closed(&self, body: &mut Function) {
        body.instruction(&Instruction::GlobalGet(self.system_scope));
        reject(body);
    }
    fn forward(&self, body: &mut Function, function: u32) {
        for p in 0..self.signature(function).params.len() as u32 {
            body.instruction(&Instruction::LocalGet(p));
        }
        body.instruction(&Instruction::Call(function));
    }
    fn wrapper(&self, function: u32) -> Function {
        let sig = self.signature(function);
        let mut body = Function::new(sig.results.iter().map(|t| (1, *t)));
        self.mode_closed(&mut body);
        body.instruction(&Instruction::GlobalGet(self.root_lifecycle));
        if function == self.realloc {
            // Canonical realloc clears context slots, including when called
            // while a root/child frame is suspended in a host import. Both
            // input allocation (0) and live allocation (1) use the distinct
            // original-memory System stack. No current context is borrowed.
            body.instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32GtU);
        } else {
            body.instruction(&Instruction::I32Const(if function == self.post {
                2
            } else {
                0
            }))
            .instruction(&Instruction::I32Ne);
        }
        reject(&mut body);
        body.instruction(&Instruction::GlobalGet(if function == self.init {
            self.initialized
        } else {
            self.post_done
        }));
        reject(&mut body);
        if function != self.init {
            body.instruction(&Instruction::GlobalGet(self.initialized))
                .instruction(&Instruction::I32Eqz);
            reject(&mut body);
        }
        self.stack_pointer(&mut body);
        body.instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::GlobalSet(self.system_scope));
        self.forward(&mut body, function);
        for r in (0..sig.results.len() as u32).rev() {
            body.instruction(&Instruction::LocalSet(sig.params.len() as u32 + r));
        }
        if function == self.realloc {
            // Preserve the generator's size-zero sentinel. A real allocation
            // cannot export a pointer into System TLS, the fixed guard, or a
            // stack. The original heap starts beyond the authenticated TLS
            // tail; all bytes stay within the original memory reservation.
            body.instruction(&Instruction::LocalGet(3))
                .instruction(&Instruction::If(BlockType::Empty));
            body.instruction(&Instruction::LocalGet(4))
                .instruction(&Instruction::I32Const(self.heap_base as i32))
                .instruction(&Instruction::I32LtU);
            reject(&mut body);
            body.instruction(&Instruction::LocalGet(2))
                .instruction(&Instruction::I32Eqz);
            reject(&mut body);
            body.instruction(&Instruction::LocalGet(2))
                .instruction(&Instruction::LocalGet(2))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Sub)
                .instruction(&Instruction::I32And);
            reject(&mut body);
            body.instruction(&Instruction::LocalGet(4))
                .instruction(&Instruction::LocalGet(2))
                .instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::I32Sub)
                .instruction(&Instruction::I32And);
            reject(&mut body);
            body.instruction(&Instruction::LocalGet(4))
                .instruction(&Instruction::I64ExtendI32U)
                .instruction(&Instruction::LocalGet(3))
                .instruction(&Instruction::I64ExtendI32U)
                .instruction(&Instruction::I64Add)
                .instruction(&Instruction::MemorySize(0))
                .instruction(&Instruction::I64ExtendI32U)
                .instruction(&Instruction::I64Const(16))
                .instruction(&Instruction::I64Shl)
                .instruction(&Instruction::I64GtU);
            reject(&mut body);
            body.instruction(&Instruction::End);
        }
        self.stack_pointer(&mut body);
        body.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::GlobalSet(self.system_scope));
        if function != self.realloc {
            body.instruction(&Instruction::I32Const(1))
                .instruction(&Instruction::GlobalSet(if function == self.init {
                    self.initialized
                } else {
                    self.post_done
                }));
        }
        for r in 0..sig.results.len() as u32 {
            body.instruction(&Instruction::LocalGet(sig.params.len() as u32 + r));
        }
        body.instruction(&Instruction::End);
        body
    }

    fn helper(
        &mut self,
        index: u32,
        original: &wasmparser::FunctionBody<'_>,
    ) -> Result<Function, reencode::Error<&'static str>> {
        let mut function = self.new_function_with_parsed_locals(original)?;
        function
            .instruction(&Instruction::GlobalGet(self.system_scope))
            .instruction(&Instruction::If(BlockType::Empty));
        if index == self.tls_get {
            function
                .instruction(&Instruction::I32Const(self.root_tls as i32))
                .instruction(&Instruction::Return);
        } else if index == self.stack_get {
            function
                .instruction(&Instruction::GlobalGet(self.base.stack_global))
                .instruction(&Instruction::Return);
        } else {
            function
                .instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::I32Const(15))
                .instruction(&Instruction::I32And);
            reject(&mut function);
            for (limit, op) in [(GUARD, Instruction::I32LtU), (HIGH, Instruction::I32GtU)] {
                function
                    .instruction(&Instruction::LocalGet(0))
                    .instruction(&Instruction::I32Const(limit))
                    .instruction(&op);
                reject(&mut function);
            }
            function
                .instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::GlobalSet(self.base.stack_global))
                .instruction(&Instruction::Return);
        }
        function.instruction(&Instruction::End);
        let mut ops = original.get_operators_reader()?;
        while !ops.eof() {
            function.instruction(&self.instruction(ops.read()?)?);
        }
        Ok(function)
    }

    fn root_body(
        &mut self,
        original: &wasmparser::FunctionBody<'_>,
    ) -> Result<Function, reencode::Error<&'static str>> {
        let mut function = self.new_function_with_parsed_locals(original)?;
        self.mode_closed(&mut function);
        function
            .instruction(&Instruction::GlobalGet(self.initialized))
            .instruction(&Instruction::I32Eqz);
        reject(&mut function);
        let mut ops = original.get_operators_reader()?;
        while !ops.eof() {
            function.instruction(&self.instruction(ops.read()?)?);
        }
        Ok(function)
    }
}

impl Reencode for Abi {
    type Error = &'static str;
    fn parse_function_section(
        &mut self,
        out: &mut FunctionSection,
        reader: wasmparser::FunctionSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, out, reader)?;
        for index in [self.init, self.realloc, self.post] {
            out.function(self.signature(index).ty);
        }
        Ok(())
    }
    fn parse_global_section(
        &mut self,
        out: &mut GlobalSection,
        reader: wasmparser::GlobalSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_global_section(self, out, reader)?;
        for _ in 0..3 {
            out.global(
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
    fn parse_export_section(
        &mut self,
        out: &mut ExportSection,
        reader: wasmparser::ExportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        for row in reader {
            let row = row.map_err(|_| reencode::Error::UserError("c-abi-export-reencode"))?;
            let (name, index) = if row.name == INITIALIZE_BODY {
                (INITIALIZE, self.first_wrapper)
            } else if row.name == REALLOC {
                (row.name, self.first_wrapper + 1)
            } else if row.name == self.post_name {
                (row.name, self.first_wrapper + 2)
            } else {
                (row.name, row.index)
            };
            out.export(name, self.export_kind(row.kind)?, index);
        }
        Ok(())
    }
    fn parse_code_section(
        &mut self,
        out: &mut CodeSection,
        reader: wasmparser::CodeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let mut index = self.base.imported_functions;
        for body in reader {
            let body = body?;
            if index == self.stack_get || index == self.stack_set || index == self.tls_get {
                out.function(&self.helper(index, &body)?);
            } else if index == self.root_entry {
                out.function(&self.root_body(&body)?);
            } else {
                self.parse_function_body(out, body)?;
            }
            index += 1;
        }
        for index in [self.init, self.realloc, self.post] {
            out.function(&self.wrapper(index));
        }
        Ok(())
    }
}

/// Recompute every intermediate from the one original linked core. No
/// supplied receipt, marker, export name or hash is sufficient for selection.
pub fn transform_c_canonical_abi(
    input: &[u8],
    expected: [u8; 32],
    public: &str,
) -> Result<(Vec<u8>, CCanonicalAbiReceipt), &'static str> {
    if <[u8; 32]>::from(Sha256::digest(input)) != expected {
        return Err("c-abi-original-preimage-mismatch");
    }
    let original = plan(input)?;
    let mut renamed = Module::new();
    InitializeName
        .parse_core_module(&mut renamed, Parser::new(0), input)
        .map_err(|_| "c-abi-initializer-export-derivation")?;
    let renamed = renamed.finish();
    let (rooted, root) =
        c_root::transform_c_root_bootstrap(&renamed, Sha256::digest(&renamed).into(), public)?;
    let mut abi = Abi::inspect(
        &rooted,
        public,
        &original,
        root.template.original_template_start,
    )?;
    let mut module = Module::new();
    abi.parse_core_module(&mut module, Parser::new(0), &rooted)
        .map_err(|_| "c-abi-reencode")?;
    let output = module.finish();
    if output.len() > MAX_BYTES {
        return Err("c-abi-derived-byte-limit");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "c-abi-derived-invalid")?;
    Ok((
        output.clone(),
        CCanonicalAbiReceipt {
            original_digest: expected,
            derived_digest: Sha256::digest(&output).into(),
            root,
            initialize_wrapper: abi.first_wrapper,
            realloc_wrapper: abi.first_wrapper + 1,
            post_return_wrapper: abi.first_wrapper + 2,
            system_closure_functions: abi.closure.len() as u32,
            system_scope_reads_tls: abi.closure.contains(&abi.tls_get),
            canonical_component_authenticated: false,
            runtime_profile_qualified: false,
        },
    ))
}

pub fn verify_c_canonical_abi(
    original: &[u8],
    derived: &[u8],
    public: &str,
) -> Result<CCanonicalAbiReceipt, &'static str> {
    let (expected, receipt) =
        transform_c_canonical_abi(original, Sha256::digest(original).into(), public)?;
    if expected != derived {
        return Err("c-abi-final-core-byte-mismatch");
    }
    Ok(receipt)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use wasm_encoder::ExportKind;

    struct Generated {
        first: u32,
        types: u32,
        variant: u8,
    }
    impl Reencode for Generated {
        type Error = &'static str;
        fn parse_type_section(
            &mut self,
            out: &mut TypeSection,
            reader: wasmparser::TypeSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_type_section(self, out, reader)?;
            out.ty().function([ValType::I32; 4], [ValType::I32]);
            out.ty().function([ValType::I64], []);
            Ok(())
        }
        fn parse_function_section(
            &mut self,
            out: &mut FunctionSection,
            reader: wasmparser::FunctionSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_function_section(self, out, reader)?;
            out.function(4)
                .function(self.types)
                .function(self.types + 1);
            Ok(())
        }
        fn parse_export_section(
            &mut self,
            out: &mut ExportSection,
            reader: wasmparser::ExportSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_export_section(self, out, reader)?;
            for (name, offset) in [(INITIALIZE, 0), (REALLOC, 1), ("cabi_post_run", 2)] {
                out.export(name, ExportKind::Func, self.first + offset);
            }
            Ok(())
        }
        fn parse_code_section(
            &mut self,
            out: &mut CodeSection,
            reader: wasmparser::CodeSectionReader<'_>,
        ) -> Result<(), reencode::Error<Self::Error>> {
            reencode::utils::parse_code_section(self, out, reader)?;
            let mut init = Function::new([]);
            init.instruction(&Instruction::Call(self.first - 1));
            if self.variant == 4 {
                init.instruction(&Instruction::GlobalGet(1))
                    .instruction(&Instruction::Drop);
            }
            init.instruction(&Instruction::End);
            out.function(&init);
            let mut alloc = Function::new([]);
            alloc
                .instruction(&Instruction::GlobalGet(0))
                .instruction(&Instruction::I32Const(16))
                .instruction(&Instruction::I32Sub)
                .instruction(&Instruction::GlobalSet(0));
            match self.variant {
                1 => {
                    alloc
                        .instruction(&Instruction::I32Const(0))
                        .instruction(&Instruction::I32Const(0))
                        .instruction(&Instruction::Call(1))
                        .instruction(&Instruction::Drop);
                }
                2 => {
                    alloc
                        .instruction(&Instruction::GlobalGet(1))
                        .instruction(&Instruction::Drop);
                }
                3 => {
                    alloc
                        .instruction(&Instruction::I32Const(0))
                        .instruction(&Instruction::I32Const(0))
                        .instruction(&Instruction::I32Const(0))
                        .instruction(&Instruction::CallIndirect {
                            type_index: 1,
                            table_index: 0,
                        })
                        .instruction(&Instruction::Drop);
                }
                // Actual OOM/abort-like failure is a trap, not an effectful
                // host fallback. Both the success and trap paths are audited.
                _ => {
                    alloc
                        .instruction(&Instruction::LocalGet(3))
                        .instruction(&Instruction::I32Const(4096))
                        .instruction(&Instruction::I32GtU)
                        .instruction(&Instruction::If(BlockType::Empty))
                        .instruction(&Instruction::Unreachable)
                        .instruction(&Instruction::End);
                }
            }
            alloc
                .instruction(&Instruction::GlobalGet(0))
                .instruction(&Instruction::I32Const(16))
                .instruction(&Instruction::I32Add)
                .instruction(&Instruction::GlobalSet(0))
                .instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::End);
            out.function(&alloc);
            let mut post = Function::new([]);
            if self.variant == 5 {
                post.instruction(&Instruction::GlobalGet(1))
                    .instruction(&Instruction::Drop);
            }
            post.instruction(&Instruction::LocalGet(0))
                .instruction(&Instruction::Drop)
                .instruction(&Instruction::End);
            out.function(&post);
            Ok(())
        }
    }
    pub(crate) fn fixture(variant: u8) -> Vec<u8> {
        let original = c_root::tests::fixture(HIGH, false, false);
        let plan = plan(&original).unwrap();
        let mut generated = Generated {
            first: plan.imported_functions + plan.function_count,
            types: plan.type_count,
            variant,
        };
        let mut out = Module::new();
        generated
            .parse_core_module(&mut out, Parser::new(0), &original)
            .unwrap();
        out.finish()
    }

    #[test]
    fn c_reactor_allocation_and_post_return_have_closed_system_scopes() {
        let original = fixture(0);
        let (output, receipt) =
            transform_c_canonical_abi(&original, Sha256::digest(&original).into(), "run").unwrap();
        assert_eq!(
            verify_c_canonical_abi(&original, &output, "run").unwrap(),
            receipt
        );
        assert_eq!(receipt.initialize_wrapper + 1, receipt.realloc_wrapper);
        assert_eq!(receipt.realloc_wrapper + 1, receipt.post_return_wrapper);
        assert!(
            !receipt.system_scope_reads_tls
                && !receipt.canonical_component_authenticated
                && !receipt.runtime_profile_qualified
        );
        assert!(receipt.system_closure_functions >= 6);
        // The ordinary root and caller result are still the original core
        // signature; there is no callback-code or task.return substitution.
        assert_eq!(receipt.root.root_record_bytes, 144);
    }

    #[test]
    fn c_system_closure_rejects_host_and_indirect_failure_paths() {
        for (variant, error) in [
            (1, "c-abi-system-host-or-thread-import"),
            (3, "c-abi-system-indirect-or-reference-call"),
        ] {
            let original = fixture(variant);
            assert_eq!(
                transform_c_canonical_abi(&original, Sha256::digest(&original).into(), "run")
                    .unwrap_err(),
                error
            );
        }
    }

    #[test]
    fn c_system_errno_tls_path_preserves_original_root_storage() {
        let original = fixture(4);
        let (output, receipt) =
            transform_c_canonical_abi(&original, Sha256::digest(&original).into(), "run").unwrap();
        assert!(receipt.system_scope_reads_tls);
        assert_eq!(receipt.root.template.original_template_start, 196608);
        assert_eq!(
            verify_c_canonical_abi(&original, &output, "run").unwrap(),
            receipt
        );
    }

    fn operators(input: &[u8], function: u32) -> Vec<Operator<'_>> {
        let imported = plan(input).unwrap().imported_functions;
        Parser::new(0)
            .parse_all(input)
            .filter_map(|payload| match payload.unwrap() {
                Payload::CodeSectionEntry(body) => Some(body),
                _ => None,
            })
            .nth((function - imported) as usize)
            .unwrap()
            .get_operators_reader()
            .unwrap()
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    }

    #[test]
    fn c_system_stack_disjoint_reservation_and_zero_context_realloc_scope() {
        let original = fixture(0);
        let (output, receipt) =
            transform_c_canonical_abi(&original, Sha256::digest(&original).into(), "run").unwrap();
        assert_eq!(plan(&original).unwrap().stack_initial, 135168);
        assert_eq!(
            (receipt.root.root_stack_low, receipt.root.root_stack_high),
            (4096, 69632)
        );
        assert_eq!((GUARD, HIGH), (69632, 135168));
        let memories = |input: &[u8]| {
            Parser::new(0)
                .parse_all(input)
                .filter_map(|payload| match payload.unwrap() {
                    Payload::MemorySection(reader) => {
                        Some(reader.into_iter().collect::<Result<Vec<_>, _>>().unwrap())
                    }
                    _ => None,
                })
                .collect::<Vec<_>>()
        };
        assert_eq!(memories(&original), memories(&output));
        let globals = Parser::new(0)
            .parse_all(&original)
            .find_map(|payload| match payload.unwrap() {
                Payload::GlobalSection(reader) => Some(reader.count()),
                _ => None,
            })
            .unwrap();
        let scope = globals + 1; // root lifecycle follows the original globals
        let ops = operators(&output, receipt.realloc_wrapper);
        // The real old regression bypassed System scope for lifecycle=1.
        // There must now be exactly one allocator call, enclosed in System
        // scope, with no early Return or context intrinsic at this boundary.
        let call = ops
            .iter()
            .position(|op| matches!(op, Operator::Call { .. }))
            .unwrap();
        assert_eq!(
            ops.iter()
                .filter(|op| matches!(op, Operator::Call { .. }))
                .count(),
            1
        );
        assert!(!ops.iter().any(|op| matches!(op, Operator::Return)));
        assert!(ops[..call].windows(2).any(|pair| matches!(pair,
            [Operator::I32Const { value: 1 }, Operator::GlobalSet { global_index }] if *global_index == scope)));
        assert!(ops[call..].windows(2).any(|pair| matches!(pair,
            [Operator::I32Const { value: 0 }, Operator::GlobalSet { global_index }] if *global_index == scope)));
        assert!(ops[..call].iter().any(|op| matches!(op, Operator::I32GtU)));
        // In the actual emitted stack helper, a System call returns the
        // reserved global SP before any zeroed context lookup. The private
        // root/child record is untouched along that complete early branch.
        let get = plan(&original).unwrap();
        let helper = operators(&output, get.imported_functions + get.function_count + 2);
        let returns = helper
            .iter()
            .position(|op| matches!(op, Operator::Return))
            .unwrap();
        let context = helper.iter().position(|op| matches!(op, Operator::Call { function_index } if *function_index == get.context_get)).unwrap();
        assert!(returns < context);
        assert!(
            matches!(&helper[..returns], [Operator::GlobalGet { global_index }, Operator::If { .. }, Operator::GlobalGet { .. }] if *global_index == scope)
        );
        assert_eq!(
            verify_c_canonical_abi(&original, &output, "run").unwrap(),
            receipt
        );
    }

    #[test]
    fn c_system_stack_rejects_aliases_and_live_realloc_tls() {
        // The former single reservation cannot silently host both stacks.
        let aliased = c_root::tests::fixture(69632, false, false);
        assert_eq!(
            transform_c_root_bootstrap(&aliased, Sha256::digest(&aliased).into(), "run")
                .unwrap_err(),
            "c-root-exact-guard-and-usable-stack-layout"
        );
        let occupied = c_root::tests::fixture(HIGH, true, false);
        assert_eq!(
            transform_c_root_bootstrap(&occupied, Sha256::digest(&occupied).into(), "run")
                .unwrap_err(),
            "c-root-original-active-data-overlaps-guard-or-stack"
        );
        let allocator_tls = fixture(2);
        assert_eq!(
            transform_c_canonical_abi(&allocator_tls, Sha256::digest(&allocator_tls).into(), "run")
                .unwrap_err(),
            "c-abi-live-realloc-tls-alias-not-qualified"
        );
        // TLS remains available to the authentic non-live initializer and
        // post-return closures; its presence there cannot hide allocator TLS.
        for variant in [4, 5] {
            let input = fixture(variant);
            let (output, receipt) =
                transform_c_canonical_abi(&input, Sha256::digest(&input).into(), "run").unwrap();
            assert!(receipt.system_scope_reads_tls);
            assert_eq!(
                verify_c_canonical_abi(&input, &output, "run").unwrap(),
                receipt
            );
        }
    }

    #[test]
    fn c_canonical_proof_recomputes_the_original_core_and_all_fixed_wrappers() {
        let original = fixture(0);
        let (mut derived, _) =
            transform_c_canonical_abi(&original, Sha256::digest(&original).into(), "run").unwrap();
        let last = derived.len() - 1;
        derived[last] ^= 1;
        assert_eq!(
            verify_c_canonical_abi(&original, &derived, "run").unwrap_err(),
            "c-abi-final-core-byte-mismatch"
        );
        assert_eq!(
            transform_c_canonical_abi(&original, [0; 32], "run").unwrap_err(),
            "c-abi-original-preimage-mismatch"
        );
    }
}
