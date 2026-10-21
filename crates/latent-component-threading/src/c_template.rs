//! Immutable original-data image for C static TLS. No C++ dynamic TLS support,
//! root bootstrap or final component selection is established by this helper.
use super::*;
use wasm_encoder::{DataCountSection, DataSection, SectionId};

const COPY: &str = "__lsf_c_template_copy";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CTemplateReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub original_template_start: u32,
    pub conservative_template_extent: u32,
    pub template_digest: [u8; 32],
    pub original_active_segments: u32,
    pub original_passive_segments: u32,
    pub segment_intersections: u32,
    pub template_copy_function: u32,
    pub private_passive_segment: u32,
    pub source_image_is_pre_initializer: bool,
    pub root_bootstrap_installed: bool,
    pub runtime_profile_qualified: bool,
}

struct Template {
    start: u32,
    image: Vec<u8>,
    active: u32,
    passive: u32,
    intersections: u32,
    copy: u32,
    next: u32,
    data_count: u32,
    had_count: bool,
    count_emitted: bool,
    data_emitted: bool,
}

fn inspect(input: &[u8]) -> Result<Template, &'static str> {
    let (start, extent) = c_context::original_template_layout(input)?;
    let end = start
        .checked_add(extent)
        .ok_or("c-template-range-overflow")?;
    let base = plan(input)?;
    let mut image = vec![0; extent as usize];
    let mut active = 0;
    let mut passive = 0;
    let mut intersections = 0;
    let mut copy = None;
    let mut imports = 0;
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut index = base.imported_functions;
    let mut refusal = false;
    let mut had_count = false;
    let mut initial_bytes = None;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "c-template-core-parse")? {
            Payload::TypeSection(reader) => {
                for ty in reader.into_iter_err_on_gc_types() {
                    types.push(ty.map_err(|_| "c-template-core-type")?);
                }
            }
            Payload::ImportSection(reader) => {
                for row in reader.into_imports() {
                    if matches!(
                        row.map_err(|_| "c-template-import")?.ty,
                        TypeRef::Func(_) | TypeRef::FuncExact(_)
                    ) {
                        imports += 1;
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                for ty in reader {
                    functions.push(ty.map_err(|_| "c-template-function-type")?);
                }
            }
            Payload::MemorySection(reader) => {
                for memory in reader {
                    let memory = memory.map_err(|_| "c-template-memory")?;
                    if initial_bytes.replace(memory.initial * 65_536).is_some() {
                        return Err("c-template-single-memory");
                    }
                }
            }
            Payload::ExportSection(reader) => {
                for row in reader {
                    let row = row.map_err(|_| "c-template-export")?;
                    if row.name == COPY
                        && (row.kind != ExternalKind::Func || copy.replace(row.index).is_some())
                    {
                        return Err("c-template-copy-export");
                    }
                }
            }
            Payload::DataSection(reader) => {
                if reader.count() > 4096 {
                    return Err("c-template-data-segment-bound");
                }
                for row in reader {
                    let row = row.map_err(|_| "c-template-data")?;
                    match row.kind {
                        wasmparser::DataKind::Passive => passive += 1,
                        wasmparser::DataKind::Active {
                            memory_index,
                            offset_expr,
                        } => {
                            if memory_index != 0 {
                                return Err("c-template-original-memory-index");
                            }
                            let mut offset = offset_expr.get_operators_reader();
                            let begin = match offset.read().map_err(|_| "c-template-offset")? {
                                Operator::I32Const { value } => value as u32,
                                _ => return Err("c-template-constant-original-offset"),
                            };
                            if !matches!(offset.read(), Ok(Operator::End)) || !offset.eof() {
                                return Err("c-template-single-original-offset");
                            }
                            let segment_end = begin
                                .checked_add(
                                    u32::try_from(row.data.len())
                                        .map_err(|_| "c-template-data-length")?,
                                )
                                .ok_or("c-template-segment-overflow")?;
                            if u64::from(segment_end)
                                > initial_bytes.ok_or("c-template-memory-before-data")?
                            {
                                return Err("c-template-original-segment-outside-initial-memory");
                            }
                            // Segments are applied in actual module order; later
                            // active bytes override earlier bytes. Missing/BSS
                            // bytes remain zero. Passive bytes are not initial
                            // memory and are never guessed to have executed.
                            let low = begin.max(start);
                            let high = segment_end.min(end);
                            if low < high {
                                image[(low - start) as usize..(high - start) as usize]
                                    .copy_from_slice(
                                        &row.data[(low - begin) as usize..(high - begin) as usize],
                                    );
                                intersections += 1;
                            }
                            active += 1;
                        }
                    }
                }
            }
            Payload::DataCountSection { .. } => had_count = true,
            Payload::StartSection { .. } => {
                return Err("c-template-start-mutation-before-bootstrap");
            }
            Payload::CodeSectionEntry(body) => {
                if Some(index) == copy {
                    let mut ops = body
                        .get_operators_reader()
                        .map_err(|_| "c-template-copy-code")?;
                    refusal = body
                        .get_locals_reader()
                        .map_err(|_| "c-template-copy-locals")?
                        .count()
                        == 0
                        && matches!(ops.read(), Ok(Operator::Unreachable))
                        && matches!(ops.read(), Ok(Operator::End))
                        && ops.eof();
                }
                index += 1;
            }
            _ => {}
        }
    }
    let copy = copy.ok_or("c-template-refusing-copy-missing")?;
    if !refusal {
        return Err("c-template-copy-must-be-deliberate-refusal");
    }
    let function = copy
        .checked_sub(imports)
        .ok_or("c-template-copy-must-be-defined")?;
    let ty = *functions
        .get(function as usize)
        .ok_or("c-template-copy-function")?;
    let ty = types.get(ty as usize).ok_or("c-template-copy-type")?;
    if ty.params() != [wasmparser::ValType::I32] || !ty.results().is_empty() {
        return Err("c-template-copy-signature");
    }
    Ok(Template {
        start,
        image,
        active,
        passive,
        intersections,
        copy,
        next: imports,
        data_count: active + passive,
        had_count,
        count_emitted: false,
        data_emitted: false,
    })
}

impl Template {
    fn copy_body(&self) -> Function {
        let mut body = Function::new([]);
        body.instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Eqz)
            .instruction(&Instruction::If(BlockType::Empty))
            .instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End)
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(15))
            .instruction(&Instruction::I32And)
            .instruction(&Instruction::If(BlockType::Empty))
            .instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End)
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(self.image.len() as i64))
            .instruction(&Instruction::I64Add)
            .instruction(&Instruction::MemorySize(0))
            .instruction(&Instruction::I64ExtendI32U)
            .instruction(&Instruction::I64Const(16))
            .instruction(&Instruction::I64Shl)
            .instruction(&Instruction::I64GtU)
            .instruction(&Instruction::If(BlockType::Empty))
            .instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End)
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::I32Const(0))
            .instruction(&Instruction::I32Const(self.image.len() as i32))
            .instruction(&Instruction::MemoryInit {
                mem: 0,
                data_index: self.data_count,
            })
            .instruction(&Instruction::End);
        body
    }
}

impl Reencode for Template {
    type Error = &'static str;
    fn data_count(&mut self, count: u32) -> Result<u32, reencode::Error<Self::Error>> {
        if count != self.data_count {
            return Err(reencode::Error::UserError("c-template-original-data-count"));
        }
        self.count_emitted = true;
        Ok(count + 1)
    }
    fn intersperse_section_hook(
        &mut self,
        module: &mut Module,
        _after: Option<SectionId>,
        before: Option<SectionId>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        if before == Some(SectionId::Code) && !self.had_count && !self.count_emitted {
            module.section(&DataCountSection {
                count: self.data_count + 1,
            });
            self.count_emitted = true;
        }
        if before.is_none() && !self.data_emitted {
            let mut data = DataSection::new();
            data.passive(self.image.iter().copied());
            module.section(&data);
            self.data_emitted = true;
        }
        Ok(())
    }
    fn parse_data_section(
        &mut self,
        output: &mut DataSection,
        reader: wasmparser::DataSectionReader<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        reencode::utils::parse_data_section(self, output, reader)?;
        output.passive(self.image.iter().copied());
        self.data_emitted = true;
        Ok(())
    }
    fn parse_function_body(
        &mut self,
        output: &mut CodeSection,
        body: wasmparser::FunctionBody<'_>,
    ) -> Result<(), reencode::Error<Self::Error>> {
        let index = self.next;
        self.next += 1;
        if index == self.copy {
            output.function(&self.copy_body());
            Ok(())
        } else {
            reencode::utils::parse_function_body(self, output, body)
        }
    }
}

fn bytes(input: &[u8], range: std::ops::Range<u64>) -> Result<Vec<u8>, &'static str> {
    let start = usize::try_from(range.start).map_err(|_| "c-template-range-start")?;
    let end = usize::try_from(range.end).map_err(|_| "c-template-range-end")?;
    Ok(input
        .get(start..end)
        .ok_or("c-template-byte-range")?
        .to_vec())
}

#[derive(PartialEq, Eq)]
struct OriginalBytes {
    sections: Vec<(u8, Vec<u8>)>,
    bodies: Vec<Vec<u8>>,
    segments: Vec<Vec<u8>>,
}

fn original_bytes(input: &[u8]) -> Result<OriginalBytes, &'static str> {
    let mut original = OriginalBytes {
        sections: Vec::new(),
        bodies: Vec::new(),
        segments: Vec::new(),
    };
    for payload in Parser::new(0).parse_all(input) {
        let payload = payload.map_err(|_| "c-template-proof-parse")?;
        if let Some((id, range)) = payload.as_section()
            && ![10, 11, 12].contains(&id)
        {
            original.sections.push((id, bytes(input, range)?));
        }
        match payload {
            Payload::CodeSectionEntry(body) => original.bodies.push(bytes(input, body.range())?),
            Payload::DataSection(reader) => {
                for row in reader {
                    original.segments.push(bytes(
                        input,
                        row.map_err(|_| "c-template-proof-data")?.range,
                    )?);
                }
            }
            _ => {}
        }
    }
    Ok(original)
}

fn verify(input: &[u8], output: &[u8], template: &Template) -> Result<(), &'static str> {
    let mut old = original_bytes(input)?;
    let new = original_bytes(output)?;
    let defined = usize::try_from(template.copy - plan(input)?.imported_functions)
        .map_err(|_| "c-template-proof-defined-function")?;
    *old.bodies
        .get_mut(defined)
        .ok_or("c-template-proof-copy-body")? = template.copy_body().into_raw_body();
    let mut segment = DataSection::new();
    segment.passive(template.image.iter().copied());
    // A one-segment data payload starts with its count byte. Preserve every
    // original segment encoding, not just reconstructed memory contents.
    use wasm_encoder::Encode;
    let mut encoded = Vec::new();
    segment.encode(&mut encoded);
    // Section::encode includes payload length, which may use more than one
    // LEB byte. Read only that framing; the segment itself stays exact.
    let mut framing = wasmparser::BinaryReader::new(&encoded, 0);
    framing
        .read_var_u32()
        .map_err(|_| "c-template-proof-segment-length")?;
    if !matches!(framing.read_var_u32(), Ok(1)) {
        return Err("c-template-proof-segment-count");
    }
    old.segments.push(framing.remaining_buffer().to_vec());
    if old != new {
        return Err("c-template-original-remainder-or-fixed-copy-changed");
    }
    let mut index = plan(output)?.imported_functions;
    let mut count = None;
    let mut copies = 0;
    for payload in Parser::new(0).parse_all(output) {
        match payload.map_err(|_| "c-template-proof-private-parse")? {
            Payload::DataCountSection { count: value, .. } => count = Some(value),
            Payload::CodeSectionEntry(body) => {
                let mut ops = body
                    .get_operators_reader()
                    .map_err(|_| "c-template-proof-private-code")?;
                while !ops.eof() {
                    match ops
                        .read()
                        .map_err(|_| "c-template-proof-private-operator")?
                    {
                        Operator::MemoryInit { data_index, mem }
                            if data_index == template.data_count =>
                        {
                            if index != template.copy || mem != 0 {
                                return Err("c-template-private-copy-escaped");
                            }
                            copies += 1;
                        }
                        Operator::DataDrop { data_index } if data_index == template.data_count => {
                            return Err("c-template-private-image-dropped");
                        }
                        _ => {}
                    }
                }
                index += 1;
            }
            _ => {}
        }
    }
    if copies != 1 || count != Some(template.data_count + 1) {
        return Err("c-template-private-copy-or-count");
    }
    Ok(())
}

pub fn transform_c_initial_template(
    input: &[u8],
    expected: [u8; 32],
) -> Result<(Vec<u8>, CTemplateReceipt), &'static str> {
    let original_digest: [u8; 32] = Sha256::digest(input).into();
    if original_digest != expected {
        return Err("c-template-original-preimage-mismatch");
    }
    let mut template = inspect(input)?;
    let mut output = Module::new();
    template
        .parse_core_module(&mut output, Parser::new(0), input)
        .map_err(|_| "c-template-reencode")?;
    let output = output.finish();
    if output.len() > MAX_BYTES {
        return Err("c-template-derived-byte-bound");
    }
    Validator::new()
        .validate_all(&output)
        .map_err(|_| "c-template-derived-invalid")?;
    verify(input, &output, &template)?;
    let receipt = CTemplateReceipt {
        original_digest,
        derived_digest: Sha256::digest(&output).into(),
        original_template_start: template.start,
        conservative_template_extent: template.image.len() as u32,
        template_digest: Sha256::digest(&template.image).into(),
        original_active_segments: template.active,
        original_passive_segments: template.passive,
        segment_intersections: template.intersections,
        template_copy_function: template.copy,
        private_passive_segment: template.data_count,
        source_image_is_pre_initializer: true,
        root_bootstrap_installed: false,
        runtime_profile_qualified: false,
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

    fn fixture(data: bool, outside: bool, refusal: bool) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        types.ty().function([ValType::I32], []);
        module.section(&types);
        let mut imports = ImportSection::new();
        imports.import("$root", "[context-get-1]", EntityType::Function(0));
        module.section(&imports);
        let mut functions = FunctionSection::new();
        functions.function(1).function(1);
        module.section(&functions);
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
        for (value, mutable) in [(69632, true), (131072, false), (131104, false)] {
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
        exports.export("__stack_pointer", ExportKind::Global, 0);
        exports.export("__tls_base", ExportKind::Global, 1);
        exports.export("__data_end", ExportKind::Global, 2);
        exports.export(COPY, ExportKind::Func, 1);
        module.section(&exports);
        let mut code = CodeSection::new();
        let mut copy = Function::new([]);
        if !refusal {
            copy.instruction(&Instruction::Nop);
        }
        copy.instruction(&Instruction::Unreachable)
            .instruction(&Instruction::End);
        code.function(&copy);
        let mut untouched = Function::new([]);
        untouched
            .instruction(&Instruction::LocalGet(0))
            .instruction(&Instruction::Drop)
            .instruction(&Instruction::End);
        code.function(&untouched);
        module.section(&code);
        if data {
            let mut segments = DataSection::new();
            segments.active(0, &ConstExpr::i32_const(131070), [9, 8, 1, 2, 3, 4]);
            segments.active(0, &ConstExpr::i32_const(131074), [7, 6]);
            segments.active(
                0,
                &ConstExpr::i32_const(if outside { 262144 } else { 1024 }),
                [11],
            );
            segments.passive([5; 32]);
            module.section(&segments);
        }
        module.finish()
    }

    #[test]
    fn original_overlay_order_bss_and_passive_data_have_exact_distinct_meanings() {
        let input = fixture(true, false, true);
        let old = input.clone();
        let (output, receipt) =
            transform_c_initial_template(&input, Sha256::digest(&input).into()).unwrap();
        let mut expected = vec![0; 32];
        expected[..4].copy_from_slice(&[1, 2, 7, 6]);
        assert_eq!(inspect(&input).unwrap().image, expected);
        assert_eq!(input, old);
        let digest: [u8; 32] = Sha256::digest(&expected).into();
        assert_eq!(receipt.template_digest, digest);
        assert_eq!(receipt.original_active_segments, 3);
        assert_eq!(receipt.original_passive_segments, 1);
        assert_eq!(receipt.segment_intersections, 2);
        assert_eq!(receipt.private_passive_segment, 4);
        assert!(receipt.source_image_is_pre_initializer);
        assert!(!receipt.root_bootstrap_installed && !receipt.runtime_profile_qualified);
        verify(&input, &output, &inspect(&input).unwrap()).unwrap();
    }

    #[test]
    fn zero_only_original_template_gets_a_private_passive_image_and_count() {
        let input = fixture(false, false, true);
        let (output, receipt) =
            transform_c_initial_template(&input, Sha256::digest(&input).into()).unwrap();
        assert_eq!(receipt.private_passive_segment, 0);
        assert_eq!(inspect(&input).unwrap().image, vec![0; 32]);
        verify(&input, &output, &inspect(&input).unwrap()).unwrap();
    }

    #[test]
    fn active_data_outside_initial_memory_and_nonrefusing_copy_are_rejected() {
        for (outside, refusal, expected) in [
            (
                true,
                true,
                "c-template-original-segment-outside-initial-memory",
            ),
            (false, false, "c-template-copy-must-be-deliberate-refusal"),
        ] {
            let input = fixture(true, outside, refusal);
            assert_eq!(
                transform_c_initial_template(&input, Sha256::digest(&input).into()).unwrap_err(),
                expected
            );
        }
    }

    #[test]
    fn stale_original_and_changed_private_bytes_cannot_authenticate_a_template() {
        let input = fixture(true, false, true);
        assert_eq!(
            transform_c_initial_template(&input, [0; 32]).unwrap_err(),
            "c-template-original-preimage-mismatch"
        );
        let (mut output, _) =
            transform_c_initial_template(&input, Sha256::digest(&input).into()).unwrap();
        *output.last_mut().unwrap() = 99;
        assert_eq!(
            verify(&input, &output, &inspect(&input).unwrap()).unwrap_err(),
            "c-template-original-remainder-or-fixed-copy-changed"
        );
    }
}
