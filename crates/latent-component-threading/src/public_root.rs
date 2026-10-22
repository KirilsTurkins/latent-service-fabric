//! Prepare one explicit ordinary WIT core export for the owned Rust transforms.
//! This does not authenticate the selected std/pool bodies or enable execution.
use super::*;
use wasm_encoder::{EntityType, ExportKind, ExportSection, ImportSection};

const ROOT: &str = "__lsf_rust_activation_root";
const NATIVE: &str = "latent:runtime-native/threads@0.1.0";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicRootReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub original_public_function: u32,
    pub derived_public_function: u32,
    pub native_admission_import: u32,
    pub native_import_inserted: bool,
    pub private_executor_graph_authenticated: bool,
    pub runtime_profile_qualified: bool,
}

struct Prepare {
    imported: u32,
    type_count: u32,
    public: u32,
    insert_native: bool,
}
impl Reencode for Prepare {
    type Error = &'static str;
    fn function_index(&mut self, index: u32) -> Result<u32, reencode::Error<Self::Error>> {
        Ok(index + u32::from(self.insert_native && index >= self.imported))
    }
    fn parse_type_section(
        &mut self,
        out: &mut TypeSection,
        reader: wasmparser::TypeSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_type_section(self, out, reader)?;
        if self.insert_native {
            out.ty()
                .function([ValType::I64, ValType::I64, ValType::I32], []);
        }
        Ok(())
    }
    fn parse_import_section(
        &mut self,
        out: &mut ImportSection,
        reader: wasmparser::ImportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_import_section(self, out, reader)?;
        if self.insert_native {
            out.import(NATIVE, "start", EntityType::Function(self.type_count));
        }
        Ok(())
    }
    fn parse_export_section(
        &mut self,
        out: &mut ExportSection,
        reader: wasmparser::ExportSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_export_section(self, out, reader)?;
        let public = self.function_index(self.public)?;
        out.export(ROOT, ExportKind::Func, public);
        Ok(())
    }
}

/// The caller must derive `public` from the actual maintained WIT surface and
/// later authenticate its final component lift, post-return and private graph.
/// No guest marker is accepted: an existing private root export is rejected.
pub fn prepare_owned_public_root(
    input: &[u8],
    expected_preimage: [u8; 32],
    public: &str,
) -> Result<(Vec<u8>, PublicRootReceipt), &'static str> {
    let original_digest = Sha256::digest(input).into();
    if original_digest != expected_preimage {
        return Err("rust-public-root-preimage-mismatch");
    }
    if public.is_empty()
        || public.len() > 512
        || (public.starts_with('_') || public.starts_with('['))
        || !public.contains('#')
    {
        return Err("rust-public-root-explicit-wit-export");
    }
    let base = plan(input)?;
    let mut types = Vec::new();
    let mut imported = 0;
    let mut native = None;
    let mut selected = None;
    let mut support = Vec::new();
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-public-root-core-parse")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "rust-public-root-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for row in reader.into_imports() {
                    let row = row.map_err(|_| "rust-public-root-import")?;
                    if row.module == NATIVE && row.name == "start" {
                        let TypeRef::Func(ty) = row.ty else {
                            return Err("rust-public-root-native-import-shape");
                        };
                        let ty = types
                            .get(ty as usize)
                            .ok_or("rust-public-root-native-type")?;
                        if native.replace(imported).is_some()
                            || ty.params()
                                != [
                                    wasmparser::ValType::I64,
                                    wasmparser::ValType::I64,
                                    wasmparser::ValType::I32,
                                ]
                            || !ty.results().is_empty()
                        {
                            return Err("rust-public-root-native-signature-or-duplicate");
                        }
                    }
                    if matches!(row.ty, TypeRef::Func(_) | TypeRef::FuncExact(_)) {
                        imported += 1;
                    }
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "rust-public-root-export")?;
                    if row.name == ROOT {
                        return Err("rust-public-root-guest-marker-denied");
                    }
                    if row.name == public {
                        if row.kind != ExternalKind::Func || selected.replace(row.index).is_some() {
                            return Err("rust-public-root-export-shape");
                        }
                    }
                    if row.name.starts_with("__lsf_rust_") && row.kind == ExternalKind::Func {
                        support.push(row.index);
                    }
                }
            }
            Payload::StartSection { .. } => return Err("rust-public-root-start-denied"),
            _ => {}
        }
    }
    let public_function = selected.ok_or("rust-public-root-export-missing")?;
    if public_function < imported || support.contains(&public_function) {
        return Err("rust-public-root-defined-nonsupport-function-required");
    }
    let insert_native = native.is_none();
    if insert_native
        && (base.type_count >= MAX_FUNCTIONS
            || base.imported_functions + base.function_count >= MAX_FUNCTIONS)
    {
        return Err("rust-public-root-append-bound");
    }
    let native_import = native.unwrap_or(imported);
    let mut rewrite = Prepare {
        imported,
        type_count: base.type_count,
        public: public_function,
        insert_native,
    };
    let mut module = Module::new();
    rewrite
        .parse_core_module(&mut module, Parser::new(0), input)
        .map_err(|_| "rust-public-root-reencode")?;
    let output = module.finish();
    if output.len() > MAX_BYTES {
        return Err("rust-public-root-output-bound");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "rust-public-root-derived-invalid")?;
    let derived_public = public_function + u32::from(insert_native);
    let derived_digest = Sha256::digest(&output).into();
    Ok((
        output,
        PublicRootReceipt {
            original_digest,
            derived_digest,
            original_public_function: public_function,
            derived_public_function: derived_public,
            native_admission_import: native_import,
            native_import_inserted: insert_native,
            private_executor_graph_authenticated: false,
            runtime_profile_qualified: false,
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        ConstExpr, ElementSection, Elements, GlobalSection, GlobalType, MemorySection, MemoryType,
        RefType, TableSection, TableType,
    };

    const PUBLIC: &str = "examples:ordinary/run@1.0.0#run";

    fn fixture(native: bool, marker: bool, wrong_signature: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types
            .ty()
            .function([ValType::I64, ValType::I64, ValType::I32], []);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        if native {
            imports.import(
                NATIVE,
                "start",
                EntityType::Function(if wrong_signature { 0 } else { 1 }),
            );
        }
        module.section(&imports);
        let first = 1 + u32::from(native);
        let mut functions = FunctionSection::new();
        functions.function(0);
        functions.function(0);
        module.section(&functions);
        let mut tables = TableSection::new();
        tables.table(TableType {
            element_type: RefType::FUNCREF,
            table64: false,
            minimum: 2,
            maximum: Some(2),
            shared: false,
        });
        module.section(&tables);
        let mut memory = MemorySection::new();
        memory.memory(MemoryType {
            minimum: 2,
            maximum: Some(2),
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
            &ConstExpr::i32_const(65_536),
        );
        module.section(&globals);
        let mut exports = ExportSection::new();
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export(PUBLIC, ExportKind::Func, first);
        if marker {
            exports.export(ROOT, ExportKind::Func, first);
        }
        module.section(&exports);
        let mut elements = ElementSection::new();
        elements.active(
            Some(0),
            &ConstExpr::i32_const(0),
            Elements::Functions(Cow::Borrowed(&[first, first + 1])),
        );
        module.section(&elements);
        let mut code = CodeSection::new();
        let mut public = Function::new([]);
        public
            .instruction(&Instruction::Call(first + 1))
            .instruction(&Instruction::End);
        code.function(&public);
        let mut helper = Function::new([]);
        helper
            .instruction(&Instruction::I32Const(42))
            .instruction(&Instruction::End);
        code.function(&helper);
        module.section(&code);
        module.finish()
    }
    fn digest(input: &[u8]) -> [u8; 32] {
        Sha256::digest(input).into()
    }

    #[test]
    fn inserted_native_import_remaps_the_real_public_export_body_and_table() {
        let input = fixture(false, false, false);
        let (output, receipt) = prepare_owned_public_root(&input, digest(&input), PUBLIC).unwrap();
        assert_eq!(
            (
                receipt.original_public_function,
                receipt.derived_public_function,
                receipt.native_admission_import
            ),
            (1, 2, 1)
        );
        assert!(receipt.native_import_inserted);
        assert!(
            !receipt.private_executor_graph_authenticated && !receipt.runtime_profile_qualified
        );
        let mut exports = Vec::new();
        let mut calls = Vec::new();
        let mut table = Vec::new();
        for payload in Parser::new(0).parse_all(&output) {
            match payload.unwrap() {
                Payload::ExportSection(reader) => {
                    for row in reader {
                        let row = row.unwrap();
                        if row.kind == ExternalKind::Func {
                            exports.push((row.name, row.index));
                        }
                    }
                }
                Payload::CodeSectionEntry(body) => {
                    let mut reader = body.get_operators_reader().unwrap();
                    while !reader.eof() {
                        if let Operator::Call { function_index } = reader.read().unwrap() {
                            calls.push(function_index);
                        }
                    }
                }
                Payload::ElementSection(reader) => {
                    for row in reader {
                        if let wasmparser::ElementItems::Functions(items) = row.unwrap().items {
                            table.extend(items.into_iter().map(Result::unwrap));
                        }
                    }
                }
                _ => {}
            }
        }
        assert_eq!(exports, [(PUBLIC, 2), (ROOT, 2)]);
        assert_eq!(calls, [3]);
        assert_eq!(table, [2, 3]);
    }

    #[test]
    fn existing_exact_native_import_is_reused_but_guest_markers_and_foreign_types_are_refused() {
        let input = fixture(true, false, false);
        let (_, receipt) = prepare_owned_public_root(&input, digest(&input), PUBLIC).unwrap();
        assert!(!receipt.native_import_inserted);
        assert_eq!(
            (
                receipt.original_public_function,
                receipt.derived_public_function
            ),
            (2, 2)
        );
        for (native, marker, wrong, reason) in [
            (false, true, false, "rust-public-root-guest-marker-denied"),
            (
                true,
                false,
                true,
                "rust-public-root-native-signature-or-duplicate",
            ),
        ] {
            let input = fixture(native, marker, wrong);
            assert_eq!(
                prepare_owned_public_root(&input, digest(&input), PUBLIC),
                Err(reason)
            );
        }
        assert_eq!(
            prepare_owned_public_root(&input, [0; 32], PUBLIC),
            Err("rust-public-root-preimage-mismatch")
        );
        assert_eq!(
            prepare_owned_public_root(&input, digest(&input), "__lsf_guest_marker"),
            Err("rust-public-root-explicit-wit-export")
        );
        assert_eq!(
            prepare_owned_public_root(&input, digest(&input), "absent:ordinary/run@1.0.0#run"),
            Err("rust-public-root-export-missing")
        );
    }
}
