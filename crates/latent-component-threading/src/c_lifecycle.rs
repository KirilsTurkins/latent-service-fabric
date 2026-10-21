//! C-specific canonical entry/admission source transform. Never selects a host
//! profile. Root bootstrap and whole-component authentication remain required.
use super::*;

const ENTRY: &str = "__lsf_c_owned_thread_entry";
const BODY: &str = "__lsf_c_thread_body";
const NATIVE: &str = "latent:runtime-native/threads@0.1.0";
const PHASE: u64 = 20;
const TASK: u64 = 32;
const ADMISSION: u64 = 80;
const STARTED: u64 = 82;
const TLS_FINISHED: u64 = 83;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CThreadLifecycleReceipt {
    pub context: c_context::CContextReceipt,
    pub derived_digest: [u8; 32],
    pub entry_function: u32,
    pub original_c_body: u32,
    pub sole_creation_consumer: u32,
    pub original_entry_table_slot: u32,
    pub context_installed_before_c_prologue: bool,
    pub context_detached_after_c_epilogue: bool,
    pub native_reservation_refunded: bool,
    pub root_bootstrap_installed: bool,
    pub component_routing_authenticated: bool,
    pub runtime_profile_qualified: bool,
}

struct CEntry {
    base: Plan,
    raw_new: u32,
    raw_new_type: u32,
    entry: u32,
    body: u32,
    next_body: u32,
    entry_slot: u32,
    template_extent: u32,
}

fn inspect(input: &[u8], template_extent: u32) -> Result<CEntry, &'static str> {
    if template_extent == 0 || template_extent > 1024 * 1024 {
        return Err("c-lifecycle-original-template-bound");
    }
    let base = plan(input)?;
    if base.imported_functions + base.function_count > MAX_FUNCTIONS - 3
        || base.type_count > MAX_FUNCTIONS - 2
    {
        return Err("c-lifecycle-function-or-type-limit");
    }
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut imported = 0;
    let mut raw_new = None;
    let mut raw_new_type = None;
    let mut entry = None;
    let mut body = None;
    let mut entry_refusal = false;
    let mut code = base.imported_functions;
    let mut tables = 0;
    let mut table_exported = false;
    let mut elements = Vec::new();
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-lifecycle-core-parse")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "c-lifecycle-core-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for row in reader.into_imports() {
                    let row = row.map_err(|_| "c-lifecycle-core-import")?;
                    if matches!(row.ty, TypeRef::Table(_)) {
                        return Err("c-lifecycle-imported-table");
                    }
                    if let TypeRef::Func(ty) | TypeRef::FuncExact(ty) = row.ty {
                        if row.module == NATIVE
                            || row.module == "$root" && row.name == "[context-set-1]"
                        {
                            return Err("c-lifecycle-reserved-bootstrap-import");
                        }
                        if row.module == "$root" && row.name.starts_with("[thread-new") {
                            let signature = types.get(ty as usize).ok_or("c-lifecycle-new-type")?;
                            if row.name != "[thread-new-indirect-v0]"
                                || raw_new.replace(imported).is_some()
                                || signature.params() != [wasmparser::ValType::I32; 2]
                                || signature.results() != [wasmparser::ValType::I32]
                            {
                                return Err("c-lifecycle-new-signature-or-duplicate");
                            }
                            raw_new_type = Some(ty);
                        }
                        imported += 1;
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    functions.push(ty.map_err(|_| "c-lifecycle-function-type")?);
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-lifecycle-export")?;
                    if row.name == "__indirect_function_table" {
                        if row.kind != ExternalKind::Table || row.index != 0 || table_exported {
                            return Err("c-lifecycle-table-export");
                        }
                        table_exported = true;
                    }
                    let selected = match row.name {
                        ENTRY => &mut entry,
                        BODY => &mut body,
                        _ => continue,
                    };
                    if row.kind != ExternalKind::Func || selected.replace(row.index).is_some() {
                        return Err("c-lifecycle-entry-or-body-export");
                    }
                }
            }
            Payload::TableSection(reader) => {
                for table in reader {
                    let table = table.map_err(|_| "c-lifecycle-table")?;
                    tables += 1;
                    if tables != 1
                        || table.ty.element_type != wasmparser::RefType::FUNCREF
                        || table.ty.table64
                        || table.ty.shared
                        || table.ty.initial > 65_536
                        || table.ty.maximum.is_none_or(|n| n > 65_536)
                    {
                        return Err("c-lifecycle-finite-original-table");
                    }
                }
            }
            Payload::ElementSection(reader) => {
                if reader.count() != 1 {
                    return Err("c-lifecycle-one-static-element-segment");
                }
                for element in reader {
                    let element = element.map_err(|_| "c-lifecycle-element")?;
                    let wasmparser::ElementKind::Active {
                        table_index,
                        offset_expr,
                    } = element.kind
                    else {
                        return Err("c-lifecycle-static-elements-only");
                    };
                    if table_index.unwrap_or(0) != 0 {
                        return Err("c-lifecycle-element-table");
                    }
                    let mut offset = offset_expr.get_operators_reader();
                    let start = match offset.read().map_err(|_| "c-lifecycle-element-offset")? {
                        Operator::I32Const { value } if value >= 0 => value as u32,
                        _ => return Err("c-lifecycle-constant-element-offset"),
                    };
                    if !matches!(offset.read(), Ok(Operator::End)) || !offset.eof() {
                        return Err("c-lifecycle-single-constant-element-offset");
                    }
                    let wasmparser::ElementItems::Functions(functions) = element.items else {
                        return Err("c-lifecycle-function-elements-only");
                    };
                    for (ordinal, function) in functions.into_iter().enumerate() {
                        let slot = start
                            .checked_add(ordinal as u32)
                            .filter(|n| *n < 65_536)
                            .ok_or("c-lifecycle-element-slot-bound")?;
                        elements
                            .push((slot, function.map_err(|_| "c-lifecycle-element-function")?));
                    }
                }
            }
            Payload::CodeSectionEntry(function) => {
                if Some(code) == entry {
                    if function
                        .get_locals_reader()
                        .map_err(|_| "c-lifecycle-entry-locals")?
                        .get_count()
                        != 0
                    {
                        return Err("c-lifecycle-entry-refusal-locals");
                    }
                    let mut ops = function
                        .get_operators_reader()
                        .map_err(|_| "c-lifecycle-entry-code")?;
                    entry_refusal = matches!(ops.read(), Ok(Operator::Unreachable))
                        && matches!(ops.read(), Ok(Operator::End))
                        && ops.eof();
                }
                let mut ops = function
                    .get_operators_reader()
                    .map_err(|_| "c-lifecycle-operators")?;
                while !ops.eof() {
                    if matches!(
                        ops.read().map_err(|_| "c-lifecycle-operator")?,
                        Operator::TableSet { .. }
                            | Operator::TableGrow { .. }
                            | Operator::TableFill { .. }
                            | Operator::TableInit { .. }
                            | Operator::TableCopy { .. }
                            | Operator::ElemDrop { .. }
                    ) {
                        return Err("c-lifecycle-original-table-mutation");
                    }
                }
                code += 1;
            }
            Payload::StartSection { .. } => return Err("c-lifecycle-start-before-bootstrap"),
            _ => {}
        }
    }
    let entry = entry.ok_or("c-lifecycle-owned-entry-missing")?;
    let body = body.ok_or("c-lifecycle-original-body-missing")?;
    if entry == body || !entry_refusal {
        return Err("c-lifecycle-entry-must-be-deliberate-refusal");
    }
    let slots: Vec<_> = elements
        .iter()
        .filter_map(|(slot, function)| (*function == entry).then_some(*slot))
        .collect();
    if tables != 1 || !table_exported || slots.len() != 1 {
        return Err("c-lifecycle-exact-original-entry-table-slot");
    }
    for function in [entry, body] {
        let defined = function
            .checked_sub(base.imported_functions)
            .ok_or("c-lifecycle-defined-entry")?;
        let ty = *functions
            .get(defined as usize)
            .ok_or("c-lifecycle-entry-function")?;
        let ty = types.get(ty as usize).ok_or("c-lifecycle-entry-type")?;
        if ty.params() != [wasmparser::ValType::I32] || !ty.results().is_empty() {
            return Err("c-lifecycle-entry-signature");
        }
    }
    Ok(CEntry {
        base,
        raw_new: raw_new.ok_or("c-lifecycle-creation-import-missing")?,
        raw_new_type: raw_new_type.ok_or("c-lifecycle-creation-import-missing")?,
        entry,
        body,
        next_body: imported,
        entry_slot: slots[0],
        template_extent,
    })
}

fn memory(offset: u64, align: u32) -> MemArg {
    MemArg {
        offset,
        align,
        memory_index: 0,
    }
}
fn reject(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty))
        .instruction(&Instruction::Unreachable)
        .instruction(&Instruction::End);
}
fn require_field(body: &mut Function, parameter: u32, offset: u64, value: i32) {
    body.instruction(&Instruction::LocalGet(parameter))
        .instruction(&Instruction::I32Load(memory(offset, 2)))
        .instruction(&Instruction::I32Const(value))
        .instruction(&Instruction::I32Ne);
    reject(body);
}
fn require_byte(body: &mut Function, parameter: u32, offset: u64, value: i32) {
    body.instruction(&Instruction::LocalGet(parameter))
        .instruction(&Instruction::I32Load8U(memory(offset, 0)))
        .instruction(&Instruction::I32Const(value))
        .instruction(&Instruction::I32Ne);
    reject(body);
}
fn pointer(body: &mut Function, parameter: u32) {
    body.instruction(&Instruction::LocalGet(parameter))
        .instruction(&Instruction::I32Eqz);
    reject(body);
    body.instruction(&Instruction::LocalGet(parameter))
        .instruction(&Instruction::I32Const(15))
        .instruction(&Instruction::I32And);
    reject(body);
}
fn memory_bytes(body: &mut Function) {
    body.instruction(&Instruction::MemorySize(0))
        .instruction(&Instruction::I64ExtendI32U)
        .instruction(&Instruction::I64Const(16))
        .instruction(&Instruction::I64Shl);
}
fn range_start(body: &mut Function, parameter: u32, offset: Option<u64>) {
    body.instruction(&Instruction::LocalGet(parameter));
    if let Some(offset) = offset {
        body.instruction(&Instruction::I32Load(memory(offset, 2)));
    }
}
fn range_end(body: &mut Function, parameter: u32, offset: Option<u64>, extent: u32) {
    if offset == Some(4) {
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(8, 2)));
    } else {
        range_start(body, parameter, offset);
        body.instruction(&Instruction::I32Const(if offset.is_none() {
            144
        } else {
            extent as i32
        }))
        .instruction(&Instruction::I32Add);
    }
}

impl CEntry {
    fn set(&self) -> u32 {
        self.base.imported_functions
    }
    fn admit(&self) -> u32 {
        self.base.imported_functions + 1
    }
    fn creation(&self) -> u32 {
        self.base.imported_functions + 2 + self.base.function_count
    }
    fn remap(&self, function: u32) -> u32 {
        if function == self.raw_new {
            self.creation()
        } else if function >= self.base.imported_functions {
            function + 2
        } else {
            function
        }
    }
    fn context(&self, body: &mut Function, parameter: u32) {
        pointer(body, parameter);
        // Validate the complete aligned record before reading any field. Use
        // i64 for end addresses, including the memory32 end at 2^32.
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(144))
            .instruction(&Instruction::I64Add);
        memory_bytes(body);
        body.instruction(&Instruction::I64GtU);
        reject(body);
        for offset in [4, 8, 12] {
            body.instruction(&Instruction::LocalGet(parameter))
                .instruction(&Instruction::I32Load(memory(offset, 2)))
                .instruction(&Instruction::I32Const(15))
                .instruction(&Instruction::I32And);
            reject(body);
        }
        for offset in [4, 12] {
            body.instruction(&Instruction::LocalGet(parameter))
                .instruction(&Instruction::I32Load(memory(offset, 2)))
                .instruction(&Instruction::I32Eqz);
            reject(body);
        }
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(4, 2)))
            .instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(8, 2)))
            .instruction(&Instruction::I32GeU);
        reject(body);
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(8, 2)))
            .instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(4, 2)))
            .instruction(&Instruction::I32Sub)
            .instruction(&Instruction::I32Const(65536))
            .instruction(&Instruction::I32Ne);
        reject(body);
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(8, 2)))
            .instruction(&Instruction::I64ExtendI32U);
        memory_bytes(body);
        body.instruction(&Instruction::I64GtU);
        reject(body);
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(0, 2)))
            .instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(8, 2)))
            .instruction(&Instruction::I32Ne);
        reject(body);
        require_field(body, parameter, 16, self.template_extent as i32);
        body.instruction(&Instruction::LocalGet(parameter))
            .instruction(&Instruction::I32Load(memory(12, 2)))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(i64::from(self.template_extent)))
            .instruction(&Instruction::I64Add);
        memory_bytes(body);
        body.instruction(&Instruction::I64GtU);
        reject(body);
        // All addresses are now bounded below the original <=64MiB limit.
        // Disjoint [context,context+144), [low,high), [tls,tls+extent).
        for (left, right) in [(None, Some(4)), (None, Some(12)), (Some(12), Some(4))] {
            range_end(body, parameter, left, self.template_extent);
            range_start(body, parameter, right);
            body.instruction(&Instruction::I32LeU);
            range_start(body, parameter, left);
            range_end(body, parameter, right, self.template_extent);
            body.instruction(&Instruction::I32GeU)
                .instruction(&Instruction::I32Or)
                .instruction(&Instruction::I32Eqz);
            reject(body);
        }
    }
    fn entry_body(&self) -> Function {
        let mut body = Function::new([]);
        self.context(&mut body, 0);
        body.instruction(&Instruction::Call(self.base.context_get));
        reject(&mut body);
        require_field(&mut body, 0, PHASE, 1);
        require_byte(&mut body, 0, ADMISSION, 0);
        require_byte(&mut body, 0, STARTED, 1);
        require_byte(&mut body, 0, TLS_FINISHED, 0);
        body.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(2))
            .instruction(&Instruction::I32Store(memory(PHASE, 2)))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::Call(self.set()))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::Call(self.remap(self.body)))
            .instruction(&Instruction::Call(self.base.context_get))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        require_field(&mut body, 0, PHASE, 2);
        require_byte(&mut body, 0, TLS_FINISHED, 1);
        body.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(memory(0, 2)))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Load(memory(8, 2)))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(5))
            .instruction(&Instruction::I32Store(memory(PHASE, 2)))
            .instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::Call(self.set()))
            .instruction(&Instruction::End);
        body
    }
    fn creation_body(&self) -> Function {
        let mut body = Function::new([]);
        body.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(self.entry_slot as i32))
            .instruction(&Instruction::I32Ne);
        reject(&mut body);
        self.context(&mut body, 1);
        require_field(&mut body, 1, PHASE, 1);
        require_byte(&mut body, 1, STARTED, 0);
        for offset in [TASK, TASK + 8] {
            body.instruction(&Instruction::LocalGet(1))
                .instruction(&Instruction::I64Load(memory(offset, 3)))
                .instruction(&Instruction::I64Eqz);
            reject(&mut body);
        }
        body.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Const(-1))
            .instruction(&Instruction::I32Store16(memory(ADMISSION, 1)))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I64Load(memory(TASK, 3)))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I64Load(memory(TASK + 8, 3)))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Const(ADMISSION as i32))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::Call(self.admit()))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Load8U(memory(ADMISSION, 0)))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Eq)
            .instruction(&Instruction::If(BlockType::Empty))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Load8U(memory(ADMISSION + 1, 0)))
            .instruction(&Instruction::I32Const(6))
            .instruction(&Instruction::I32GtU);
        reject(&mut body);
        body.instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::Return)
            .instruction(&Instruction::End);
        require_byte(&mut body, 1, ADMISSION, 0);
        body.instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Store8(memory(STARTED, 0)))
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Call(self.raw_new))
            .instruction(&Instruction::End);
        body
    }
}

impl Reencode for CEntry {
    type Error = &'static str;
    fn function_index(&mut self, index: u32) -> Result<u32, reencode::Error<Self::Error>> {
        Ok(self.remap(index))
    }
    fn parse_type_section(
        &mut self,
        output: &mut TypeSection,
        reader: wasmparser::TypeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_type_section(self, output, reader)?;
        output.ty().function([ValType::I32], []);
        output
            .ty()
            .function([ValType::I64, ValType::I64, ValType::I32], []);
        Ok(())
    }
    fn parse_import_section(
        &mut self,
        output: &mut wasm_encoder::ImportSection,
        reader: wasmparser::ImportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_import_section(self, output, reader)?;
        output.import(
            "$root",
            "[context-set-1]",
            wasm_encoder::EntityType::Function(self.base.type_count),
        );
        output.import(
            NATIVE,
            "start",
            wasm_encoder::EntityType::Function(self.base.type_count + 1),
        );
        Ok(())
    }
    fn parse_function_section(
        &mut self,
        output: &mut FunctionSection,
        reader: wasmparser::FunctionSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, output, reader)?;
        output.function(self.raw_new_type);
        Ok(())
    }
    fn parse_function_body(
        &mut self,
        output: &mut CodeSection,
        body: wasmparser::FunctionBody<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let index = self.next_body;
        self.next_body += 1;
        if index == self.entry {
            output.function(&self.entry_body());
            Ok(())
        } else {
            reencode::utils::parse_function_body(self, output, body)
        }
    }
    fn parse_code_section(
        &mut self,
        output: &mut CodeSection,
        reader: wasmparser::CodeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, output, reader)?;
        output.function(&self.creation_body());
        Ok(())
    }
}

fn verify(input: &[u8], entry: &CEntry) -> Result<(), &'static str> {
    let expected_entry = entry.entry_body().into_raw_body();
    let expected_creation = entry.creation_body().into_raw_body();
    let mut function = entry.base.imported_functions + 2;
    let mut found = 0;
    let mut raw_calls = 0;
    let mut native_calls = 0;
    let mut set_calls = 0;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-lifecycle-final-core")? {
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-lifecycle-final-export")?;
                    if row.kind == ExternalKind::Func
                        && [entry.raw_new, entry.admit(), entry.set()].contains(&row.index)
                    {
                        return Err("c-lifecycle-reserved-export-escape");
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                let expected = if function == entry.remap(entry.entry) {
                    Some(&expected_entry)
                } else if function == entry.creation() {
                    Some(&expected_creation)
                } else {
                    None
                };
                if let Some(expected) = expected {
                    let range = body.range();
                    let begin =
                        usize::try_from(range.start).map_err(|_| "c-lifecycle-fixed-body-range")?;
                    let end =
                        usize::try_from(range.end).map_err(|_| "c-lifecycle-fixed-body-range")?;
                    if input.get(begin..end) != Some(expected.as_slice()) {
                        return Err("c-lifecycle-fixed-body-mismatch");
                    }
                    found += 1;
                }
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "c-lifecycle-final-operators")?;
                while !ops.eof() {
                    match ops.read().map_err(|_| "c-lifecycle-final-operator")? {
                        Operator::Call { function_index } if function_index == entry.raw_new => {
                            if function != entry.creation() {
                                return Err("c-lifecycle-raw-creation-escape");
                            }
                            raw_calls += 1;
                        }
                        Operator::Call { function_index } if function_index == entry.admit() => {
                            if function != entry.creation() {
                                return Err("c-lifecycle-native-admission-escape");
                            }
                            native_calls += 1;
                        }
                        Operator::Call { function_index } if function_index == entry.set() => {
                            if function != entry.remap(entry.entry) {
                                return Err("c-lifecycle-context-set-escape");
                            }
                            set_calls += 1;
                        }
                        Operator::RefFunc { function_index }
                        | Operator::ReturnCall { function_index }
                            if [entry.raw_new, entry.admit(), entry.set()]
                                .contains(&function_index) =>
                        {
                            return Err("c-lifecycle-reserved-reference-escape");
                        }
                        _ => {}
                    }
                }
                function += 1;
            }
            _ => {}
        }
    }
    if (found, raw_calls, native_calls, set_calls) != (2, 1, 1, 2) {
        return Err("c-lifecycle-exact-fixed-body-call-count");
    }
    Ok(())
}

pub fn transform_c_owned_lifecycle(
    input: &[u8],
    expected: [u8; 32],
) -> Result<(Vec<u8>, CThreadLifecycleReceipt), &'static str> {
    let (contextual, context) = c_context::transform_c_context(input, expected)?;
    let mut entry = inspect(&contextual, context.template_extent)?;
    let entry_function = entry.remap(entry.entry);
    let original_c_body = entry.remap(entry.body);
    let sole_creation_consumer = entry.creation();
    let original_entry_table_slot = entry.entry_slot;
    let mut output = Module::new();
    entry
        .parse_core_module(&mut output, Parser::new(0), &contextual)
        .map_err(|_| "c-lifecycle-reencode")?;
    let output = output.finish();
    if output.len() > MAX_BYTES {
        return Err("c-lifecycle-derived-byte-bound");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "c-lifecycle-derived-invalid")?;
    verify(&output, &entry)?;
    let receipt = CThreadLifecycleReceipt {
        context,
        derived_digest: Sha256::digest(&output).into(),
        entry_function,
        original_c_body,
        sole_creation_consumer,
        original_entry_table_slot,
        context_installed_before_c_prologue: true,
        context_detached_after_c_epilogue: true,
        native_reservation_refunded: false,
        root_bootstrap_installed: false,
        component_routing_authenticated: false,
        runtime_profile_qualified: false,
    };
    Ok((output, receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        ConstExpr, ElementSection, Elements, EntityType, ExportKind, ExportSection, GlobalSection,
        GlobalType, ImportSection, MemorySection, MemoryType, RefType, TableSection, TableType,
    };

    fn fixture_with_offset(refusal: bool, table_entry: bool, extended: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types
            .ty()
            .function([ValType::I32, ValType::I32], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", "[thread-new-indirect-v0]", EntityType::Function(1));
        module.section(&imports);
        let mut functions = FunctionSection::new();
        functions.function(2);
        functions.function(2);
        functions.function(1);
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType {
            element_type: RefType::FUNCREF,
            minimum: if extended { 4 } else { 3 },
            maximum: Some(if extended { 4 } else { 3 }),
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
        for (value, mutable) in [(65536, true), (131072, false), (131120, false)] {
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
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export("__tls_base", ExportKind::Global, 1);
        exports.export("__data_end", ExportKind::Global, 2);
        exports.export("__indirect_function_table", ExportKind::Table, 0);
        exports.export(ENTRY, ExportKind::Func, 2);
        exports.export(BODY, ExportKind::Func, 3);
        exports.export("raw-looking-export", ExportKind::Func, 1);
        module.section(&exports);
        let mut elements = ElementSection::new();
        let offset = if extended {
            ConstExpr::extended([
                Instruction::I32Const(1),
                Instruction::I32Const(1),
                Instruction::I32Add,
            ])
        } else {
            ConstExpr::i32_const(1)
        };
        elements.active(
            Some(0),
            &offset,
            Elements::Functions(Cow::Owned(vec![if table_entry { 2 } else { 3 }, 1])),
        );
        module.section(&elements);
        let mut code = CodeSection::new();
        let mut entry = Function::new([]);
        if !refusal {
            entry.instruction(&Instruction::Nop);
        }
        entry
            .instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End);
        code.function(&entry);
        let mut body = Function::new([]);
        body.instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Sub)
            .instruction(&Instruction::GlobalSet(0))
            .instruction(&Instruction::GlobalGet(1))
            .instruction(&Instruction::I32Load(memory(0, 2)))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::GlobalGet(0))
            .instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Add)
            .instruction(&Instruction::GlobalSet(0))
            .instruction(&Instruction::End);
        code.function(&body);
        let mut caller = Function::new([]);
        caller
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Call(1))
            .instruction(&Instruction::End);
        code.function(&caller);
        module.section(&code);
        module.finish()
    }

    fn fixture(refusal: bool, table_entry: bool) -> Vec<u8> {
        fixture_with_offset(refusal, table_entry, false)
    }

    #[test]
    fn c_entry_and_creation_are_fixed_without_changing_the_original_context_layout() {
        let input = fixture(true, true);
        let original = input.clone();
        let (output, receipt) =
            transform_c_owned_lifecycle(&input, Sha256::digest(&input).into()).unwrap();
        assert_eq!(input, original);
        assert_eq!(receipt.original_entry_table_slot, 1);
        assert!(
            receipt.context_installed_before_c_prologue
                && receipt.context_detached_after_c_epilogue
        );
        assert!(
            !receipt.root_bootstrap_installed
                && !receipt.component_routing_authenticated
                && !receipt.runtime_profile_qualified
                && !receipt.native_reservation_refunded
        );
        let (contextual, context) =
            c_context::transform_c_context(&input, Sha256::digest(&input).into()).unwrap();
        verify(
            &output,
            &inspect(&contextual, context.template_extent).unwrap(),
        )
        .unwrap();
    }

    #[test]
    fn wrong_entry_table_and_nonrefusing_placeholder_fail_before_lifecycle_rewrite() {
        for (refusal, slot, expected) in [
            (false, true, "c-lifecycle-entry-must-be-deliberate-refusal"),
            (true, false, "c-lifecycle-exact-original-entry-table-slot"),
        ] {
            let input = fixture(refusal, slot);
            assert_eq!(
                transform_c_owned_lifecycle(&input, Sha256::digest(&input).into()).unwrap_err(),
                expected
            );
        }
    }

    #[test]
    fn a_mutated_fixed_body_is_not_a_c_bootstrap_proof() {
        let input = fixture(true, true);
        let (contextual, context) =
            c_context::transform_c_context(&input, Sha256::digest(&input).into()).unwrap();
        let entry = inspect(&contextual, context.template_extent).unwrap();
        let (mut output, _) =
            transform_c_owned_lifecycle(&input, Sha256::digest(&input).into()).unwrap();
        let mut function = entry.base.imported_functions + 2;
        let mut offset = None;
        for payload in Parser::new(0).parse_all(&output) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                if function == entry.remap(entry.entry) {
                    offset = Some(usize::try_from(body.range().start).unwrap());
                }
                function += 1;
            }
        }
        let at = offset.unwrap();
        assert_eq!(&output[at..at + 3], &[0, 0x20, 0]);
        output[at + 2] = 1;
        assert_eq!(
            verify(&output, &entry).unwrap_err(),
            "c-lifecycle-fixed-body-mismatch"
        );
    }

    #[test]
    fn stale_input_identity_cannot_select_a_c_entry_transform() {
        let input = fixture(true, true);
        assert_eq!(
            transform_c_owned_lifecycle(&input, [0; 32]).unwrap_err(),
            "c-context-preimage-mismatch"
        );
    }

    #[test]
    fn extended_constant_offset_cannot_be_mistaken_for_its_first_table_operand() {
        // This valid core installs the entry in slot2, not the first operand1.
        let input = fixture_with_offset(true, true, true);
        Validator::new().validate_all(&input).unwrap();
        assert_eq!(
            transform_c_owned_lifecycle(&input, Sha256::digest(&input).into()).unwrap_err(),
            "c-lifecycle-single-constant-element-offset"
        );
    }
}
