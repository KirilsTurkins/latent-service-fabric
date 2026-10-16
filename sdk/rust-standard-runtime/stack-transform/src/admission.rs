//! Route every core reference to canonical child creation through one fixed,
//! stackless admission body. This does not enable component-model threading.
use super::*;
use wasmparser::{ElementItems, ElementKind};

const NATIVE: &str = "latent:runtime-native/threads@0.1.0";
const NEW: &str = "[thread-new-indirect-v0]";
const PREPARED: i32 = 1;
const GENERATION: u64 = 16;
const OWNER: u64 = 24;
const RESULT: u64 = 32;
const STARTED: u64 = 34;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub raw_creation_import: u32,
    pub native_admission_import: u32,
    pub admission_function: u32,
    pub remapped_references: u64,
    pub component_routing_authenticated: bool,
    pub canonical_creation_enabled: bool,
}

#[derive(Clone, Copy)]
struct Admission {
    raw: u32,
    admit: u32,
    function: u32,
    ty: u32,
}

fn inspect(input: &[u8]) -> Result<Admission, &'static str> {
    let base = plan(input)?;
    if base.imported_functions + base.function_count >= MAX_FUNCTIONS {
        return Err("rust-child-admission-function-limit");
    }
    let mut types = Vec::new();
    let mut imported = 0;
    let mut raw = None;
    let mut admit = None;
    let mut new_type = None;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-child-admission-core-shape")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "rust-child-admission-core-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for import in reader.into_imports() {
                    let import = import.map_err(|_| "rust-child-admission-import")?;
                    if let TypeRef::Func(index) | TypeRef::FuncExact(index) = import.ty {
                        let ty = types.get(index as usize).ok_or("rust-child-admission-import-type")?;
                        if import.module == "$root" && import.name.starts_with("[thread-new") {
                            if import.name != NEW || raw.replace(imported).is_some()
                                || ty.params() != [wasmparser::ValType::I32, wasmparser::ValType::I32]
                                || ty.results() != [wasmparser::ValType::I32]
                            {
                                return Err("rust-child-admission-creation-signature-or-duplicate");
                            }
                            new_type = Some(index);
                        }
                        if import.module == NATIVE && import.name == "start" {
                            if admit.replace(imported).is_some()
                                || ty.params() != [wasmparser::ValType::I64, wasmparser::ValType::I64, wasmparser::ValType::I32]
                                || !ty.results().is_empty()
                            {
                                return Err("rust-child-admission-native-signature-or-duplicate");
                            }
                        }
                        imported += 1;
                    }
                }
            }
            Payload::StartSection { .. } => return Err("rust-child-admission-core-start-denied"),
            _ => {}
        }
    }
    Ok(Admission {
        raw: raw.ok_or("rust-child-admission-creation-import-missing")?,
        admit: admit.ok_or("rust-child-admission-native-import-missing")?,
        function: base.imported_functions + base.function_count,
        ty: new_type.ok_or("rust-child-admission-creation-import-missing")?,
    })
}

fn memory(offset: u64, align: u32) -> MemArg { MemArg { offset, align, memory_index: 0 } }
fn reject(body: &mut Function) {
    body.instruction(&Instruction::If(BlockType::Empty))
        .instruction(&Instruction::Unreachable).instruction(&Instruction::End);
}

impl Admission {
    fn wrapper(self) -> Function {
        let mut body = Function::new([]);
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Eqz);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Const(7))
            .instruction(&Instruction::I32And);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Load(memory(12, 2)))
            .instruction(&Instruction::I32Const(PREPARED)).instruction(&Instruction::I32Ne);
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Load8U(memory(STARTED, 0)));
        reject(&mut body);
        for offset in [GENERATION, OWNER] {
            body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I64Load(memory(offset, 3)))
                .instruction(&Instruction::I64Eqz);
            reject(&mut body);
        }
        // A failed or partially written result cannot look like admission.
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Const(-1))
            .instruction(&Instruction::I32Store16(memory(RESULT, 1)));
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I64Load(memory(GENERATION, 3)))
            .instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I64Load(memory(OWNER, 3)))
            .instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Const(RESULT as i32))
            .instruction(&Instruction::I32Add).instruction(&Instruction::Call(self.admit));
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Load8U(memory(RESULT, 0)));
        reject(&mut body);
        body.instruction(&Instruction::LocalGet(1)).instruction(&Instruction::I32Const(1))
            .instruction(&Instruction::I32Store8(memory(STARTED, 0)));
        // This is the only reference to the actual primitive after rewriting.
        // Any failure/trap keeps the accepted host reservation through StoreDrop.
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Call(self.raw)).instruction(&Instruction::End);
        body
    }
}

struct RewriteAdmission { plan: Admission, references: u64 }
impl Reencode for RewriteAdmission {
    type Error = &'static str;
    fn function_index(&mut self, function: u32) -> Result<u32, reencode::Error<Self::Error>> {
        if function == self.plan.raw {
            self.references += 1;
            Ok(self.plan.function)
        } else { Ok(function) }
    }
    fn parse_function_section(&mut self, section: &mut FunctionSection,
            reader: wasmparser::FunctionSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_function_section(self, section, reader)?;
        section.function(self.plan.ty);
        Ok(())
    }
    fn parse_code_section(&mut self, code: &mut CodeSection,
            reader: wasmparser::CodeSectionReader<'_>) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_code_section(self, code, reader)?;
        code.function(&self.plan.wrapper());
        Ok(())
    }
}

fn verify(input: &[u8], admission: Admission) -> Result<(), &'static str> {
    let expected = admission.wrapper().into_raw_body();
    let base = plan(input)?;
    let mut index = base.imported_functions;
    let mut consumers = 0;
    let mut saw_wrapper = false;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-child-admission-verification-shape")? {
            Payload::CodeSectionEntry(body) => {
                if index == admission.function {
                    let range = body.range();
                    let start = usize::try_from(range.start).map_err(|_| "rust-child-admission-body-range")?;
                    let end = usize::try_from(range.end).map_err(|_| "rust-child-admission-body-range")?;
                    if input.get(start..end) != Some(expected.as_slice()) {
                        return Err("rust-child-admission-fixed-body-mismatch");
                    }
                    saw_wrapper = true;
                }
                let mut operators = body.get_operators_reader().map_err(|_| "rust-child-admission-operators")?;
                while !operators.eof() {
                    match operators.read().map_err(|_| "rust-child-admission-operator")? {
                        Operator::Call { function_index } | Operator::ReturnCall { function_index }
                        | Operator::RefFunc { function_index } if function_index == admission.raw => {
                            if index != admission.function { return Err("rust-child-admission-raw-creation-escape"); }
                            consumers += 1;
                        }
                        _ => {}
                    }
                }
                index += 1;
            }
            Payload::ExportSection(reader) => {
                for export in reader {
                    let export = export.map_err(|_| "rust-child-admission-export")?;
                    if export.kind == ExternalKind::Func && export.index == admission.raw {
                        return Err("rust-child-admission-raw-export-escape");
                    }
                }
            }
            Payload::ElementSection(reader) => {
                for item in reader {
                    let item = item.map_err(|_| "rust-child-admission-element")?;
                    if let ElementKind::Active { offset_expr, .. } = item.kind {
                        reject_reference(offset_expr.get_operators_reader(), admission.raw)?;
                    }
                    match item.items {
                        ElementItems::Functions(reader) => for function in reader {
                            if function.map_err(|_| "rust-child-admission-element-function")? == admission.raw {
                                return Err("rust-child-admission-raw-table-escape");
                            }
                        },
                        ElementItems::Expressions(_, reader) => for expression in reader {
                            reject_reference(expression.map_err(|_| "rust-child-admission-element-expression")?
                                .get_operators_reader(), admission.raw)?;
                        },
                    }
                }
            }
            Payload::GlobalSection(reader) => for global in reader {
                reject_reference(global.map_err(|_| "rust-child-admission-global")?
                    .init_expr.get_operators_reader(), admission.raw)?;
            },
            _ => {}
        }
    }
    if !saw_wrapper || consumers != 1 { return Err("rust-child-admission-requires-one-fixed-consumer"); }
    Ok(())
}

fn reject_reference(mut operators: wasmparser::OperatorsReader<'_>, raw: u32) -> Result<(), &'static str> {
    while !operators.eof() {
        if matches!(operators.read().map_err(|_| "rust-child-admission-expression")?,
            Operator::RefFunc { function_index } if function_index == raw) {
            return Err("rust-child-admission-raw-reference-escape");
        }
    }
    Ok(())
}

/// Authenticates a linked-core preimage, including call/ref.func/export/table
/// references. Whole-component routing and root bootstrap must be checked by
/// the consuming profile before it may enable canonical thread creation.
pub fn transform_owned_thread_admission(input: &[u8], expected_preimage: [u8; 32])
    -> Result<(Vec<u8>, AdmissionReceipt), &'static str>
{
    let original_digest = Sha256::digest(input).into();
    if original_digest != expected_preimage { return Err("rust-stack-input-preimage-mismatch"); }
    let admission = inspect(input)?;
    let mut rewrite = RewriteAdmission { plan: admission, references: 0 };
    let mut module = Module::new();
    rewrite.parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "rust-child-admission-reencode-failed")?;
    let output = module.finish();
    if output.len() > MAX_BYTES { return Err("rust-stack-derived-module-byte-limit"); }
    Validator::new().validate_all(&output).map_err(|_| "rust-child-admission-derived-module-invalid")?;
    verify(&output, admission)?;
    let derived_digest = Sha256::digest(&output).into();
    Ok((output, AdmissionReceipt { original_digest, derived_digest,
        raw_creation_import: admission.raw, native_admission_import: admission.admit,
        admission_function: admission.function, remapped_references: rewrite.references,
        component_routing_authenticated: false, canonical_creation_enabled: false }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{ConstExpr, CustomSection, ElementSection, Elements, EntityType,
        ExportKind, ExportSection, GlobalSection, GlobalType, ImportSection, MemorySection,
        MemoryType, RefType, TableSection, TableType};

    fn fixture(native: bool, correct: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32, ValType::I32], [ValType::I32]);
        types.ty().function(if correct { vec![ValType::I64, ValType::I64, ValType::I32] }
            else { vec![ValType::I32] }, []);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        imports.import("$root", NEW, EntityType::Function(1));
        if native { imports.import(NATIVE, "start", EntityType::Function(2)); }
        module.section(&imports);
        let mut functions = FunctionSection::new(); functions.function(1); module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType { element_type: RefType::FUNCREF, minimum: 1, maximum: Some(1),
            table64: false, shared: false }); module.section(&tables);
        let mut memories = MemorySection::new();
        memories.memory(MemoryType { minimum: 2, maximum: Some(2), memory64: false,
            shared: false, page_size_log2: None }); module.section(&memories);
        let mut globals = GlobalSection::new();
        globals.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false },
            &ConstExpr::i32_const(65536));
        globals.global(GlobalType { val_type: ValType::Ref(RefType::FUNCREF), mutable: false, shared: false },
            &ConstExpr::ref_func(1)); module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export("raw-looking-export", ExportKind::Func, 1);
        exports.export("run", ExportKind::Func, if native { 3 } else { 2 }); module.section(&exports);
        let mut elements = ElementSection::new();
        elements.active(Some(0), &ConstExpr::i32_const(0), Elements::Functions(Cow::Borrowed(&[1])));
        module.section(&elements);
        let mut code = CodeSection::new(); let mut body = Function::new([]);
        body.instruction(&Instruction::LocalGet(0)).instruction(&Instruction::LocalGet(1))
            .instruction(&Instruction::Call(1)).instruction(&Instruction::End);
        code.function(&body); module.section(&code);
        module.section(&CustomSection { name: Cow::Borrowed("original-source"), data: Cow::Borrowed(b"unchanged") });
        module.finish()
    }
    fn hash(bytes: &[u8]) -> [u8; 32] { Sha256::digest(bytes).into() }

    #[test]
    fn calls_exports_tables_and_constant_references_reach_only_the_fixed_admission_body() {
        let input = fixture(true, true); let original = input.clone();
        let (output, receipt) = transform_owned_thread_admission(&input, hash(&input)).unwrap();
        assert_eq!(input, original);
        assert_eq!(receipt.remapped_references, 4);
        assert_eq!((receipt.raw_creation_import, receipt.native_admission_import, receipt.admission_function), (1, 2, 4));
        assert!(!receipt.component_routing_authenticated && !receipt.canonical_creation_enabled);
        let mut bodies = Vec::new();
        for payload in Parser::new(0).parse_all(&output) {
            match payload.unwrap() {
                Payload::CodeSectionEntry(body) => {
                    let mut reader = body.get_operators_reader().unwrap(); let mut calls = Vec::new();
                    while !reader.eof() { if let Operator::Call { function_index } = reader.read().unwrap() { calls.push(function_index); } }
                    bodies.push(calls);
                }
                Payload::CustomSection(section) if section.name() == "original-source" => assert_eq!(section.data(), b"unchanged"),
                _ => {}
            }
        }
        assert_eq!(bodies, [vec![4], vec![2, 1]]);
        verify(&output, inspect(&input).unwrap()).unwrap();
    }

    #[test]
    fn missing_or_wrong_native_support_import_is_rejected_before_rewriting() {
        for (native, correct, expected) in [(false, true, "rust-child-admission-native-import-missing"),
            (true, false, "rust-child-admission-native-signature-or-duplicate")] {
            let input = fixture(native, correct); let original = input.clone();
            assert_eq!(transform_owned_thread_admission(&input, hash(&input)).unwrap_err(), expected);
            assert_eq!(input, original);
        }
    }

    #[test]
    fn a_changed_shim_body_cannot_pass_fixed_body_authentication() {
        let input = fixture(true, true);
        let admission = inspect(&input).unwrap();
        let (mut output, _) = transform_owned_thread_admission(&input, hash(&input)).unwrap();
        let mut target = None;
        let mut index = 3;
        for payload in Parser::new(0).parse_all(&output) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                if index == admission.function { target = Some(body.range().start as usize); }
                index += 1;
            }
        }
        // Change the first argument selection; preserve byte length/validity.
        let offset = target.unwrap(); assert_eq!(&output[offset..offset + 3], &[0, 0x20, 1]);
        output[offset + 2] = 0;
        assert_eq!(verify(&output, admission).unwrap_err(), "rust-child-admission-fixed-body-mismatch");
    }

    #[test]
    fn old_preimage_and_unwrapped_raw_call_are_not_authenticated() {
        let input = fixture(true, true);
        assert_eq!(transform_owned_thread_admission(&input, [0; 32]).unwrap_err(), "rust-stack-input-preimage-mismatch");
        let admission = inspect(&input).unwrap();
        assert!(verify(&input, admission).is_err());
    }
}
