//! Closed, host-owned original-object expectations for the selected Rust port.
//!
//! A guest cannot provide or select this catalogue. The current immutable corpus
//! is the independently verified passed28059 remapped compiler observation.
//! Its original app and guarded core compiled; the ordinary guest was not run.
//! The earlier byte-identical ec11 failure remains an immutable distinct event.
//! This source proof alone does not enable any runtime or component profile.
use wasmparser::{BinaryReader, Encoding, Operator, Parser, Payload, Validator};

#[rustfmt::skip]
#[path = "rust_catalogue.rs"]
mod catalogue;

const NODE_COUNT: usize = 1222;
const REFERENCE_COUNT: usize = 5309;
const MAX_BYTES: usize = 1024 * 1024;
const MAX_FUNCTIONS: u32 = 1024;
const MAX_OPERATORS: u64 = 262_144;
const MAX_MEMORY: usize = 2 * 1024 * 1024;
const MAX_PHYSICAL_MEMORY: usize = 32 * 1024 * 1024;
const MAX_TABLE: usize = 1024;
const MAX_TYPES: usize = 128;
const MAX_GLOBALS: usize = 32;
const MAX_EXPORTS: usize = 128;
const MAX_IMPORTS: usize = 64;
const MAX_GROUPS: u32 = 256;
const MAX_LOCALS: u64 = 8192;
const MAX_COMPARISON_BYTES: usize = 64 * 1024 * 1024;
const UNBOUND: u32 = u32::MAX;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Signature<'a> {
    params: &'a [u8],
    results: &'a [u8],
}
struct Node {
    kind: u8,
    signature: Signature<'static>,
    name: &'static str,
    start: usize,
    size: usize,
    references: &'static [Reference],
}
struct Reference {
    offset: usize,
    extent: usize,
    kind: u8,
    addend: i64,
    target: Target,
}
struct Root {
    node: u32,
    export: Option<&'static str>,
}
enum Target {
    Definition(u32),
    Type(Signature<'static>),
    Export {
        kind: u8,
        name: &'static str,
    },
    Import {
        module: &'static str,
        name: &'static str,
        signature: Signature<'static>,
    },
    Heap {
        end: bool,
    },
    Shim {
        arity: i8,
        delegate: Option<u32>,
        signature: Signature<'static>,
    },
}

#[derive(Clone, Copy)]
struct Import<'a> {
    module: &'a str,
    name: &'a str,
}
#[derive(Clone, Copy)]
struct Export<'a> {
    name: &'a str,
    kind: u8,
    index: u32,
}
struct Original<'a> {
    types: Vec<Signature<'a>>,
    functions: Vec<u32>,
    imports: Vec<Import<'a>>,
    bodies: Vec<&'a [u8]>,
    exports: Vec<Export<'a>>,
    globals: Vec<(bool, u32)>,
    memory: Vec<u8>,
    table: Vec<u32>,
    active_data_high: u32,
    stack_low: u32,
    stack_high: u32,
}

fn u32_value(raw: &mut BinaryReader<'_>) -> Result<u32, &'static str> {
    raw.read_var_u32().map_err(|_| "rust-original-u32")
}
fn byte(raw: &mut BinaryReader<'_>) -> Result<u8, &'static str> {
    raw.read_u8().map_err(|_| "rust-original-byte")
}
fn count(raw: &mut BinaryReader<'_>, maximum: usize) -> Result<usize, &'static str> {
    let value = u32_value(raw)? as usize;
    if value > maximum {
        return Err("rust-original-count-bound");
    }
    Ok(value)
}
fn string<'a>(raw: &mut BinaryReader<'a>) -> Result<&'a str, &'static str> {
    let size = count(raw, 512)?;
    std::str::from_utf8(
        raw.read_bytes(size)
            .map_err(|_| "rust-original-string-bytes")?,
    )
    .map_err(|_| "rust-original-string-utf8")
}
fn offset(raw: &mut BinaryReader<'_>) -> Result<u32, &'static str> {
    if byte(raw)? != 0x41 {
        return Err("rust-original-constant-offset");
    }
    let value = raw
        .read_var_i32()
        .map_err(|_| "rust-original-constant-offset")? as u32;
    if byte(raw)? != 0x0b {
        return Err("rust-original-constant-offset-end");
    }
    Ok(value)
}
fn signature<'a>(raw: &mut BinaryReader<'a>) -> Result<Signature<'a>, &'static str> {
    if byte(raw)? != 0x60 {
        return Err("rust-original-numeric-function-type");
    }
    let params = count(raw, 64)?;
    let params = raw
        .read_bytes(params)
        .map_err(|_| "rust-original-parameters")?;
    let results = count(raw, 16)?;
    let results = raw
        .read_bytes(results)
        .map_err(|_| "rust-original-results")?;
    if !params
        .iter()
        .chain(results)
        .all(|ty| matches!(ty, 0x7c..=0x7f))
    {
        return Err("rust-original-scalar-signature");
    }
    Ok(Signature { params, results })
}

impl<'a> Original<'a> {
    fn signature(&self, function: u32) -> Result<Signature<'a>, &'static str> {
        let index = *self
            .functions
            .get(function as usize)
            .ok_or("rust-original-function-index")?;
        self.types
            .get(index as usize)
            .copied()
            .ok_or("rust-original-type-index")
    }
    fn body(&self, function: u32) -> Result<&'a [u8], &'static str> {
        let index = (function as usize)
            .checked_sub(self.imports.len())
            .ok_or("rust-original-defined-function")?;
        self.bodies
            .get(index)
            .copied()
            .ok_or("rust-original-function-body-index")
    }
    fn export(&self, name: &str, kind: u8) -> Result<u32, &'static str> {
        let mut rows = self
            .exports
            .iter()
            .filter(|row| row.name == name && row.kind == kind);
        let found = rows.next().ok_or("rust-original-export-missing")?.index;
        if rows.next().is_some() {
            return Err("rust-original-export-duplicate");
        }
        Ok(found)
    }
    fn parse(input: &'a [u8]) -> Result<Self, &'static str> {
        if input.len() > MAX_BYTES || input.get(..8) != Some(b"\0asm\x01\0\0\0") {
            return Err("rust-original-core-byte-bound-or-version");
        }
        let mut result = Self {
            types: Vec::new(),
            functions: Vec::new(),
            imports: Vec::new(),
            bodies: Vec::new(),
            exports: Vec::new(),
            globals: Vec::new(),
            memory: Vec::new(),
            table: Vec::new(),
            active_data_high: 0,
            stack_low: 0,
            stack_high: 0,
        };
        let mut module = BinaryReader::new(&input[8..], 8);
        let mut sections = 0;
        let mut seen = [false; 13];
        while !module.eof() {
            sections += 1;
            if sections > 512 {
                return Err("rust-original-section-bound");
            }
            let id = byte(&mut module)? as usize;
            let size = count(&mut module, MAX_BYTES)?;
            let data = module
                .read_bytes(size)
                .map_err(|_| "rust-original-section-bytes")?;
            if id == 0 {
                continue;
            }
            if id >= seen.len() || seen[id] {
                return Err("rust-original-section-duplicate-or-kind");
            }
            seen[id] = true;
            let mut raw = BinaryReader::new(data, 0);
            match id {
                1 => {
                    for _ in 0..count(&mut raw, MAX_TYPES)? {
                        result.types.push(signature(&mut raw)?);
                    }
                }
                2 => {
                    for _ in 0..count(&mut raw, MAX_IMPORTS)? {
                        let module = string(&mut raw)?;
                        let name = string(&mut raw)?;
                        if byte(&mut raw)? != 0 {
                            return Err("rust-original-function-imports-only");
                        }
                        result.functions.push(u32_value(&mut raw)?);
                        result.imports.push(Import { module, name });
                    }
                }
                3 => {
                    let count = count(&mut raw, MAX_FUNCTIONS as usize)?;
                    if result.functions.len() + count > MAX_FUNCTIONS as usize {
                        return Err("rust-original-function-bound");
                    }
                    for _ in 0..count {
                        result.functions.push(u32_value(&mut raw)?);
                    }
                }
                4 => {
                    if count(&mut raw, 1)? != 1 || byte(&mut raw)? != 0x70 || byte(&mut raw)? != 1 {
                        return Err("rust-original-fixed-funcref-table");
                    }
                    let initial = count(&mut raw, MAX_TABLE)?;
                    if count(&mut raw, MAX_TABLE)? != initial {
                        return Err("rust-original-fixed-table-bound");
                    }
                    result.table.resize(initial, UNBOUND);
                }
                5 => {
                    if count(&mut raw, 1)? != 1 {
                        return Err("rust-original-one-memory");
                    }
                    let flags = byte(&mut raw)?;
                    if flags > 1 {
                        return Err("rust-original-unshared-memory32");
                    }
                    let pages = count(&mut raw, MAX_MEMORY / 65536)?;
                    if flags == 1 && count(&mut raw, MAX_PHYSICAL_MEMORY / 65536)? < pages {
                        return Err("rust-original-memory-maximum");
                    }
                    result.memory.resize(pages * 65536, 0);
                }
                6 => {
                    for _ in 0..count(&mut raw, MAX_GLOBALS)? {
                        if byte(&mut raw)? != 0x7f {
                            return Err("rust-original-i32-global");
                        }
                        let mutable = byte(&mut raw)?;
                        if mutable > 1 {
                            return Err("rust-original-global-mutability");
                        }
                        result.globals.push((mutable == 1, offset(&mut raw)?));
                    }
                }
                7 => {
                    for _ in 0..count(&mut raw, MAX_EXPORTS)? {
                        let name = string(&mut raw)?;
                        let kind = byte(&mut raw)?;
                        let index = u32_value(&mut raw)?;
                        if result.exports.iter().any(|row| row.name == name) {
                            return Err("rust-original-export-duplicate");
                        }
                        result.exports.push(Export { name, kind, index });
                    }
                }
                9 => {
                    for _ in 0..count(&mut raw, 256)? {
                        if u32_value(&mut raw)? != 0 {
                            return Err("rust-original-active-function-elements-only");
                        }
                        let start = offset(&mut raw)? as usize;
                        let size = count(&mut raw, MAX_TABLE)?;
                        let end = start.checked_add(size).ok_or("rust-original-table-span")?;
                        let target = result
                            .table
                            .get_mut(start..end)
                            .ok_or("rust-original-table-span")?;
                        for item in target {
                            *item = u32_value(&mut raw)?;
                        }
                    }
                }
                10 => {
                    for _ in 0..count(&mut raw, MAX_FUNCTIONS as usize)? {
                        let size = count(&mut raw, MAX_BYTES)?;
                        result.bodies.push(
                            raw.read_bytes(size)
                                .map_err(|_| "rust-original-code-body-bytes")?,
                        );
                    }
                }
                11 => {
                    for _ in 0..count(&mut raw, 4096)? {
                        if u32_value(&mut raw)? != 0 {
                            return Err("rust-original-active-memory-data-only");
                        }
                        let start = offset(&mut raw)? as usize;
                        let size = count(&mut raw, MAX_BYTES)?;
                        let end = start.checked_add(size).ok_or("rust-original-data-span")?;
                        result
                            .memory
                            .get_mut(start..end)
                            .ok_or("rust-original-data-span")?
                            .copy_from_slice(
                                raw.read_bytes(size)
                                    .map_err(|_| "rust-original-data-bytes")?,
                            );
                        result.active_data_high = result.active_data_high.max(end as u32);
                    }
                }
                _ => return Err("rust-original-section-not-qualified"),
            }
            if !raw.eof() {
                return Err("rust-original-section-trailing-bytes");
            }
        }
        if result.bodies.len() + result.imports.len() != result.functions.len()
            || result
                .functions
                .iter()
                .any(|index| *index as usize >= result.types.len())
        {
            return Err("rust-original-function-signatures-or-code-count");
        }
        let low_index = result.export("__stack_low", 3)? as usize;
        let high_index = result.export("__stack_pointer", 3)? as usize;
        let (low_mutable, low) = *result
            .globals
            .get(low_index)
            .ok_or("rust-original-stack-low-global")?;
        let (high_mutable, high) = *result
            .globals
            .get(high_index)
            .ok_or("rust-original-stack-high-global")?;
        if low_mutable
            || !high_mutable
            || low == 0
            || low & 15 != 0
            || high & 15 != 0
            || low >= high
            || result.active_data_high > low
            || high as usize > result.memory.len()
        {
            return Err("rust-original-authentic-stack-layout");
        }
        result.stack_low = low;
        result.stack_high = high;
        finite_code(input)?;
        Validator::new()
            .validate_all(input)
            .map_err(|_| "rust-original-invalid-core")?;
        Ok(result)
    }
}

// All allocating signature/section shapes were constrained by the raw pass.
// Constrain control/local forms before the full validator builds its state.
fn finite_code(input: &[u8]) -> Result<(), &'static str> {
    let mut operators = 0u64;
    let mut locals = 0u64;
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-original-finite-core-parse")? {
            Payload::Version { encoding, .. } if encoding != Encoding::Module => {
                return Err("rust-original-core-only");
            }
            Payload::CodeSectionEntry(body) => {
                let declarations = body
                    .get_locals_reader()
                    .map_err(|_| "rust-original-locals")?;
                if declarations.get_count() > MAX_GROUPS {
                    return Err("rust-original-local-groups");
                }
                for declaration in declarations {
                    let (count, ty) = declaration.map_err(|_| "rust-original-local")?;
                    if !matches!(
                        ty,
                        wasmparser::ValType::I32
                            | wasmparser::ValType::I64
                            | wasmparser::ValType::F32
                            | wasmparser::ValType::F64
                    ) {
                        return Err("rust-original-scalar-locals");
                    }
                    locals = locals
                        .checked_add(u64::from(count))
                        .ok_or("rust-original-local-overflow")?;
                    if locals > MAX_LOCALS {
                        return Err("rust-original-local-bound");
                    }
                }
                let mut reader = body
                    .get_operators_reader()
                    .map_err(|_| "rust-original-operators")?;
                let mut depth = 0u32;
                while !reader.eof() {
                    let opcode = reader
                        .get_binary_reader()
                        .read_u8()
                        .map_err(|_| "rust-original-opcode")?;
                    if matches!(opcode, 0x06..=0x0a | 0x18 | 0x19 | 0x1c | 0x1f | 0xe0..=0xe6 | 0xfb | 0xfd | 0xfe)
                    {
                        return Err("rust-original-numeric-control-only");
                    }
                    if opcode == 0x0e {
                        let mut raw = reader.get_binary_reader();
                        byte(&mut raw)?;
                        count(&mut raw, 256)?;
                    }
                    let operator = reader.read().map_err(|_| "rust-original-operator")?;
                    operators += 1;
                    if operators > MAX_OPERATORS {
                        return Err("rust-original-operator-bound");
                    }
                    match operator {
                        Operator::Block { .. } | Operator::Loop { .. } | Operator::If { .. } => {
                            depth += 1;
                            if depth > 256 {
                                return Err("rust-original-control-bound");
                            }
                        }
                        Operator::End => {
                            depth = depth.saturating_sub(1);
                        }
                        Operator::TableSet { .. }
                        | Operator::TableGrow { .. }
                        | Operator::TableFill { .. }
                        | Operator::TableCopy { .. }
                        | Operator::TableInit { .. } => return Err("rust-original-table-mutation"),
                        _ => {}
                    }
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn relocation(actual: &[u8], reference: &Reference) -> Result<u32, &'static str> {
    let mut reader = BinaryReader::new(actual, 0);
    let value = match reference.kind {
        0 | 3 | 6 | 7 | 20 => u32_value(&mut reader)?,
        1 | 4 => reader
            .read_var_i32()
            .map_err(|_| "rust-original-signed-relocation")? as u32,
        2 | 5 if actual.len() == 4 => u32::from_le_bytes(
            actual
                .try_into()
                .map_err(|_| "rust-original-fixed-relocation")?,
        ),
        _ => return Err("rust-original-unqualified-relocation-kind"),
    };
    if !matches!(reference.kind, 2 | 5) && !reader.eof() {
        return Err("rust-original-relocation-trailing");
    }
    Ok(value)
}

fn body_matches(
    node: &Node,
    actual: &[u8],
    signature: Signature<'_>,
    compared: &mut usize,
) -> Result<bool, &'static str> {
    if node.size != actual.len() || node.signature != signature {
        return Ok(false);
    }
    *compared = compared
        .checked_add(actual.len())
        .ok_or("rust-original-comparison-overflow")?;
    if *compared > MAX_COMPARISON_BYTES {
        return Err("rust-original-comparison-bound");
    }
    let original = catalogue::BODIES
        .get(node.start..node.start + node.size)
        .ok_or("rust-original-host-image-range")?;
    let mut previous = 0;
    for reference in node.references {
        let end = reference
            .offset
            .checked_add(reference.extent)
            .ok_or("rust-original-reference-overflow")?;
        if reference.offset < previous || end > actual.len() || reference.extent == 0 {
            return Err("rust-original-host-reference-range");
        }
        if original[previous..reference.offset] != actual[previous..reference.offset] {
            return Ok(false);
        }
        relocation(&actual[reference.offset..end], reference)?;
        previous = end;
    }
    Ok(original[previous..] == actual[previous..])
}

/// Source-only original graph proof. Its private fields cannot be forged from
/// a guest JSON receipt. Construction alone selects no engine or runtime gate.
#[derive(Debug)]
pub struct VerifiedOriginal {
    bindings: [u32; NODE_COUNT],
    pub stack_low: u32,
    pub stack_high: u32,
    pub memory_bytes: u32,
}

impl VerifiedOriginal {
    pub fn original_function(&self, name: &str) -> Result<u32, &'static str> {
        let mut rows = catalogue::NODES
            .iter()
            .enumerate()
            .filter(|(_, row)| row.kind == 0 && row.name == name);
        let (index, _) = rows.next().ok_or("rust-original-source-function-missing")?;
        if rows.next().is_some() {
            return Err("rust-original-source-function-ambiguous");
        }
        Ok(self.bindings[index])
    }
}

pub fn verify(input: &[u8]) -> Result<VerifiedOriginal, &'static str> {
    let module = Original::parse(input)?;
    if catalogue::NODES.len() != NODE_COUNT
        || catalogue::ROOTS.len() != 11
        || catalogue::NODES
            .iter()
            .map(|node| node.references.len())
            .sum::<usize>()
            != REFERENCE_COUNT
    {
        return Err("rust-original-host-catalogue-membership");
    }
    // Fixed, indexed records: no parsed global cache, recursive traversal or
    // unbounded per-component hash map. Every verified node contributes its
    // finite references to this queue at most once.
    let mut queue = [(0u32, 0u32); REFERENCE_COUNT + 11];
    let mut tail = 0;
    let mut compared = 0;
    for root in catalogue::ROOTS {
        let node = catalogue::NODES
            .get(root.node as usize)
            .ok_or("rust-original-host-root-node")?;
        let actual = if let Some(name) = root.export {
            module.export(name, 0)?
        } else {
            let mut found = None;
            for candidate in module.imports.len()..module.functions.len() {
                let candidate = candidate as u32;
                if body_matches(
                    node,
                    module.body(candidate)?,
                    module.signature(candidate)?,
                    &mut compared,
                )? {
                    if found.is_some() {
                        return Err("rust-original-root-body-ambiguous");
                    }
                    found = Some(candidate);
                }
            }
            found.ok_or("rust-original-root-body-missing")?
        };
        queue[tail] = (root.node, actual);
        tail += 1;
    }
    let mut bindings = [UNBOUND; NODE_COUNT];
    let mut head = 0;
    while head < tail {
        let (index, actual) = queue[head];
        head += 1;
        let index = index as usize;
        let node = catalogue::NODES
            .get(index)
            .ok_or("rust-original-definition-node")?;
        if bindings[index] != UNBOUND {
            if bindings[index] != actual {
                return Err("rust-original-inconsistent-definition-binding");
            }
            continue;
        }
        let (body, signature) = match node.kind {
            0 => (module.body(actual)?, module.signature(actual)?),
            1 => {
                let end = (actual as usize)
                    .checked_add(node.size)
                    .ok_or("rust-original-data-range-overflow")?;
                (
                    module
                        .memory
                        .get(actual as usize..end)
                        .ok_or("rust-original-data-range")?,
                    Signature {
                        params: &[],
                        results: &[],
                    },
                )
            }
            _ => return Err("rust-original-host-node-kind"),
        };
        if !body_matches(node, body, signature, &mut compared)? {
            return Err("rust-original-full-body-or-signature");
        }
        bindings[index] = actual;
        for reference in node.references {
            let end = reference
                .offset
                .checked_add(reference.extent)
                .ok_or("rust-original-reference-overflow")?;
            let value = relocation(
                body.get(reference.offset..end)
                    .ok_or("rust-original-reference-range")?,
                reference,
            )?;
            let destination = match reference.kind {
                1 | 2 => *module
                    .table
                    .get(value as usize)
                    .filter(|value| **value != UNBOUND)
                    .ok_or("rust-original-table-reference")?,
                3 | 4 | 5 => value.wrapping_sub(reference.addend as u32),
                _ => value,
            };
            let next = match &reference.target {
                Target::Definition(node) => Some((*node, destination)),
                Target::Type(signature) => {
                    if module.types.get(value as usize) != Some(signature) {
                        return Err("rust-original-type-reference");
                    }
                    None
                }
                Target::Export { kind, name } => {
                    if module.export(name, *kind)? != value {
                        return Err("rust-original-global-or-table-reference");
                    }
                    None
                }
                Target::Import {
                    module: expected_module,
                    name,
                    signature,
                } => {
                    let imported = module
                        .imports
                        .get(destination as usize)
                        .ok_or("rust-original-import-reference")?;
                    if imported.module != *expected_module
                        || imported.name != *name
                        || module.signature(destination)? != *signature
                    {
                        return Err("rust-original-exact-import-reference");
                    }
                    None
                }
                Target::Heap { end } => {
                    let expected = if *end {
                        module.memory.len() as u32
                    } else {
                        module.stack_high
                    };
                    if !matches!(reference.kind, 3..=5) || destination != expected {
                        return Err("rust-original-authentic-heap-reference");
                    }
                    None
                }
                Target::Shim {
                    arity,
                    delegate,
                    signature,
                } => {
                    if module.signature(destination)? != *signature {
                        return Err("rust-original-compiler-shim-signature");
                    }
                    let called = compiler_shim(module.body(destination)?, *arity)?;
                    match (*delegate, called) {
                        (Some(node), Some(actual)) => Some((node, actual)),
                        (None, None) => None,
                        _ => return Err("rust-original-compiler-shim-delegate"),
                    }
                }
            };
            if let Some(next) = next {
                let slot = queue
                    .get_mut(tail)
                    .ok_or("rust-original-fixed-work-queue-bound")?;
                *slot = next;
                tail += 1;
            }
        }
    }
    if bindings.contains(&UNBOUND) {
        return Err("rust-original-whole-catalogue-not-reached");
    }
    verify_private_incoming(input, &module, &bindings)?;
    Ok(VerifiedOriginal {
        bindings,
        stack_low: module.stack_low,
        stack_high: module.stack_high,
        memory_bytes: module.memory.len() as u32,
    })
}

fn compiler_shim(body: &[u8], arity: i8) -> Result<Option<u32>, &'static str> {
    let mut raw = BinaryReader::new(body, 0);
    if u32_value(&mut raw)? != 0 {
        return Err("rust-original-compiler-shim-locals");
    }
    if arity < 0 {
        if byte(&mut raw)? != 0x0f || byte(&mut raw)? != 0x0b || !raw.eof() {
            return Err("rust-original-compiler-shim-empty-body");
        }
        return Ok(None);
    }
    for argument in 0..arity as u32 {
        if byte(&mut raw)? != 0x20 || u32_value(&mut raw)? != argument {
            return Err("rust-original-compiler-shim-argument");
        }
    }
    if byte(&mut raw)? != 0x10 {
        return Err("rust-original-compiler-shim-call");
    }
    let callee = u32_value(&mut raw)?;
    if byte(&mut raw)? != 0x0f || byte(&mut raw)? != 0x0b || !raw.eof() {
        return Err("rust-original-compiler-shim-body");
    }
    Ok(Some(callee))
}

fn verify_private_incoming(
    input: &[u8],
    module: &Original<'_>,
    bindings: &[u32; NODE_COUNT],
) -> Result<(), &'static str> {
    let mut defined = module.imports.len() as u32;
    for payload in Parser::new(0).parse_all(input) {
        if let Payload::CodeSectionEntry(body) =
            payload.map_err(|_| "rust-original-incoming-parse")?
        {
            let caller_verified = catalogue::NODES
                .iter()
                .zip(bindings)
                .any(|(node, actual)| node.kind == 0 && *actual == defined);
            let mut reader = body
                .get_operators_reader()
                .map_err(|_| "rust-original-incoming-code")?;
            while !reader.eof() {
                let operator = reader
                    .read()
                    .map_err(|_| "rust-original-incoming-operator")?;
                let target = match operator {
                    Operator::Call { function_index }
                    | Operator::ReturnCall { function_index }
                    | Operator::RefFunc { function_index } => Some(function_index),
                    Operator::CallRef { .. } | Operator::ReturnCallRef { .. } => {
                        return Err("rust-original-unqualified-call-ref");
                    }
                    _ => None,
                };
                if let Some(target) = target {
                    let private = catalogue::ROOTS
                        .iter()
                        .filter(|root| root.export.is_some())
                        .any(|root| bindings[root.node as usize] == target);
                    if private && !caller_verified {
                        return Err("rust-original-private-incoming-unmatched");
                    }
                }
            }
            defined += 1;
        }
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct CallbackTarget {
    slot: u32,
    function: u32,
}
#[derive(Clone, Copy)]
struct CallbackSite {
    function: u32,
    offset: usize,
    target: usize,
    fallback: bool,
}

fn source_role(proof: &VerifiedOriginal, suffix: &str) -> Result<u32, &'static str> {
    // Names locate a record in OUR immutable source catalogue. Authority is
    // the whole original-body/referent proof, never a guest symbol/name/hash.
    let mut found = None;
    for (index, node) in catalogue::NODES.iter().enumerate() {
        if node.kind == 0
            && node
                .name
                .split(".llvm.")
                .next()
                .unwrap_or("")
                .ends_with(suffix)
        {
            if found.replace(proof.bindings[index]).is_some() {
                return Err("rust-callback-source-role-ambiguous");
            }
        }
    }
    found.ok_or("rust-callback-source-role-missing")
}

fn indirect_sites(
    module: &Original<'_>,
    function: u32,
    expected: &[Signature<'_>],
) -> Result<Vec<usize>, &'static str> {
    let body = wasmparser::FunctionBody::new(BinaryReader::new(module.body(function)?, 0));
    let mut reader = body
        .get_operators_reader()
        .map_err(|_| "rust-callback-owner-operators")?;
    let mut found = Vec::new();
    while !reader.eof() {
        let position = usize::try_from(reader.original_position())
            .map_err(|_| "rust-callback-owner-position")?;
        if let Operator::CallIndirect {
            type_index,
            table_index,
        } = reader.read().map_err(|_| "rust-callback-owner-operator")?
        {
            if table_index != 0
                || module.types.get(type_index as usize) != expected.get(found.len())
            {
                return Err("rust-callback-owner-indirect-signature");
            }
            found.push(position);
        }
    }
    if found.len() != expected.len() {
        return Err("rust-callback-owner-indirect-count");
    }
    Ok(found)
}

fn callback_plan(
    module: &Original<'_>,
    proof: &VerifiedOriginal,
) -> Result<([CallbackTarget; 5], [CallbackSite; 6]), &'static str> {
    let progress = Signature {
        params: &[0x7f],
        results: &[0x7f],
    };
    let release = Signature {
        params: &[0x7f],
        results: &[],
    };
    let notified = Signature {
        params: &[0x7f, 0x7f],
        results: &[],
    };
    let functions = [
        source_role(proof, "_9PoolState8progress")?,
        source_role(proof, "_9PoolState7release")?,
        source_role(proof, "runtime13executor_root14worker_release")?,
        source_role(proof, "runtime13executor_root20worker_frames_exited")?,
        source_role(proof, "runtime13executor_root18worker_tls_drained")?,
    ];
    let mut targets = [CallbackTarget {
        slot: 0,
        function: 0,
    }; 5];
    for (index, function) in functions.into_iter().enumerate() {
        let mut slots = module
            .table
            .iter()
            .enumerate()
            .filter(|(_, target)| **target == function);
        let (slot, _) = slots
            .next()
            .ok_or("rust-callback-original-table-target-missing")?;
        if slots.next().is_some() || targets[..index].iter().any(|row| row.function == function) {
            return Err("rust-callback-original-table-target-ambiguous");
        }
        if module
            .exports
            .iter()
            .any(|row| row.kind == 0 && row.index == function)
        {
            return Err("rust-callback-original-target-export");
        }
        targets[index] = CallbackTarget {
            slot: slot as u32,
            function,
        };
    }
    let root = source_role(proof, "runtime13executor_root12progress_all")?;
    let reaper = source_role(proof, "runtime4reap")?;
    let entered = source_role(proof, "runtime7entered")?;
    let root_sites = indirect_sites(module, root, &[progress, progress, release])?;
    let worker_sites = indirect_sites(module, functions[2], &[release])?;
    let reaper_sites = indirect_sites(module, reaper, &[notified, release])?;
    let entered_sites = indirect_sites(module, entered, &[release, notified])?;
    // The authenticated original Captured1/Source branch and genuine Arc
    // allocation/header/increments/worker/destructor paths remain byte-exact.
    // Only these six owner dispatches change. Source progress and ordinary TLS
    // callbacks retain their original indirect path; shared release keeps its
    // original Source fallback when the receiver's callback is not private.
    Ok((
        targets,
        [
            CallbackSite {
                function: root,
                offset: root_sites[0],
                target: 0,
                fallback: false,
            },
            CallbackSite {
                function: root,
                offset: root_sites[2],
                target: 1,
                fallback: true,
            },
            CallbackSite {
                function: functions[2],
                offset: worker_sites[0],
                target: 1,
                fallback: false,
            },
            CallbackSite {
                function: reaper,
                offset: reaper_sites[0],
                target: 3,
                fallback: false,
            },
            CallbackSite {
                function: reaper,
                offset: reaper_sites[1],
                target: 2,
                fallback: false,
            },
            CallbackSite {
                function: entered,
                offset: entered_sites[1],
                target: 4,
                fallback: false,
            },
        ],
    ))
}

fn unsigned(mut value: u32, output: &mut Vec<u8>) {
    loop {
        let part = value as u8 & 0x7f;
        value >>= 7;
        output.push(part | if value == 0 { 0 } else { 0x80 });
        if value == 0 {
            break;
        }
    }
}
fn signed(mut value: i32, output: &mut Vec<u8>) {
    loop {
        let part = value as u8 & 0x7f;
        value >>= 7;
        let end = (value == 0 && part & 0x40 == 0) || (value == -1 && part & 0x40 != 0);
        output.push(part | if end { 0 } else { 0x80 });
        if end {
            break;
        }
    }
}
fn local(index: u32, output: &mut Vec<u8>) {
    output.push(0x20);
    unsigned(index, output);
}
fn vector(original: &[u8], additions: &[Vec<u8>]) -> Result<Vec<u8>, &'static str> {
    let mut reader = BinaryReader::new(original, 0);
    let original_count = u32_value(&mut reader)?;
    let mut result = Vec::new();
    unsigned(
        original_count
            .checked_add(additions.len() as u32)
            .ok_or("rust-callback-vector-count-overflow")?,
        &mut result,
    );
    result.extend_from_slice(&original[reader.current_position()..]);
    for item in additions {
        result.extend_from_slice(item);
    }
    Ok(result)
}

fn dispatch_helper(
    target: CallbackTarget,
    signature: Signature<'_>,
    type_index: u32,
    fallback: bool,
) -> Result<Vec<u8>, &'static str> {
    if !signature.params.iter().all(|ty| *ty == 0x7f)
        || !(1..=2).contains(&signature.params.len())
        || !(signature.results.is_empty() || signature.results == [0x7f])
    {
        return Err("rust-callback-helper-signature");
    }
    let mut body = vec![0];
    local(signature.params.len() as u32, &mut body);
    body.push(0x41);
    signed(target.slot as i32, &mut body);
    body.extend_from_slice(&[0x46, 0x04]);
    body.push(signature.results.first().copied().unwrap_or(0x40));
    for index in 0..signature.params.len() {
        local(index as u32, &mut body);
    }
    body.push(0x10);
    unsigned(target.function, &mut body);
    body.push(0x05);
    if fallback {
        for index in 0..signature.params.len() + 1 {
            local(index as u32, &mut body);
        }
        body.push(0x11);
        unsigned(type_index, &mut body);
        body.push(0);
    } else {
        body.push(0);
    }
    body.extend_from_slice(&[0x0b, 0x0b]);
    Ok(body)
}

/// Tiny engine control using the SAME helper emitter as the authentic sealer.
/// Arithmetic receivers deliberately represent no Rust/Arc/runtime execution.
pub fn emitted_dispatch_controls() -> Result<Vec<u8>, &'static str> {
    use std::borrow::Cow;
    use wasm_encoder::{
        ConstExpr, ElementSection, Elements, ExportKind, ExportSection, FunctionSection, Module,
        RawSection, RefType, TableSection, TableType, TypeSection, ValType,
    };
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32], [ValType::I32]);
    types
        .ty()
        .function([ValType::I32, ValType::I32], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    for ty in [0, 0, 0, 1, 1, 1] {
        functions.function(ty);
    }
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
    let mut exports = ExportSection::new();
    for (name, index) in [("strict", 3), ("release", 4), ("ordinary", 5)] {
        exports.export(name, ExportKind::Func, index);
    }
    module.section(&exports);
    let mut elements = ElementSection::new();
    elements.active(
        Some(0),
        &ConstExpr::i32_const(0),
        Elements::Functions(Cow::Borrowed(&[2, 1])),
    );
    module.section(&elements);
    let target = CallbackTarget {
        slot: 0,
        function: 0,
    };
    let signature = Signature {
        params: &[0x7f],
        results: &[0x7f],
    };
    let bodies = [
        vec![0, 0x20, 0, 0x41, 0xe4, 0, 0x6a, 0x0b], // receiver+100.
        vec![0, 0x20, 0, 0x41, 10, 0x6a, 0x0b],      // receiver+10.
        vec![0, 0, 0x0b],                            // Ordinary private-table substitute traps.
        dispatch_helper(target, signature, 0, false)?,
        dispatch_helper(target, signature, 0, true)?,
        vec![0, 0x20, 0, 0x20, 1, 0x11, 0, 0, 0x0b],
    ];
    let mut code = vec![6];
    for body in bodies {
        unsigned(body.len() as u32, &mut code);
        code.extend_from_slice(&body);
    }
    module.section(&RawSection {
        id: 10,
        data: &code,
    });
    let bytes = module.finish();
    Validator::new()
        .validate_all(&bytes)
        .map_err(|_| "rust-callback-control-invalid")?;
    Ok(bytes)
}

fn sealed_elements(
    raw: &[u8],
    targets: &[CallbackTarget; 5],
    first_trap: u32,
) -> Result<Vec<u8>, &'static str> {
    let mut reader = BinaryReader::new(raw, 0);
    let groups = count(&mut reader, 256)?;
    let mut output = Vec::new();
    unsigned(groups as u32, &mut output);
    for _ in 0..groups {
        if u32_value(&mut reader)? != 0 {
            return Err("rust-callback-active-elements-only");
        }
        output.push(0);
        let start = offset(&mut reader)?;
        output.push(0x41);
        signed(start as i32, &mut output);
        output.push(0x0b);
        let size = count(&mut reader, MAX_TABLE)?;
        unsigned(size as u32, &mut output);
        for relative in 0..size {
            let function = u32_value(&mut reader)?;
            let replacement = targets
                .iter()
                .enumerate()
                .find(|(_, row)| row.function == function);
            let function = if let Some((index, target)) = replacement {
                if start.checked_add(relative as u32) != Some(target.slot) {
                    return Err("rust-callback-element-alias");
                }
                first_trap + index as u32
            } else {
                function
            };
            unsigned(function, &mut output);
        }
    }
    if !reader.eof() {
        return Err("rust-callback-element-trailing");
    }
    Ok(output)
}

fn sealed_body(
    body: &[u8],
    function: u32,
    module: &Original<'_>,
    targets: &[CallbackTarget; 5],
    sites: &[CallbackSite; 6],
    first_helper: u32,
) -> Result<Vec<u8>, &'static str> {
    let parsed = wasmparser::FunctionBody::new(BinaryReader::new(body, 0));
    let mut reader = parsed
        .get_operators_reader()
        .map_err(|_| "rust-callback-body-operators")?;
    let mut output = Vec::new();
    let mut previous = 0;
    let mut changed = 0;
    while !reader.eof() {
        let start = usize::try_from(reader.original_position())
            .map_err(|_| "rust-callback-body-position")?;
        let operator = reader.read().map_err(|_| "rust-callback-body-operator")?;
        let end = usize::try_from(reader.original_position())
            .map_err(|_| "rust-callback-body-position")?;
        if let Operator::Call { function_index }
        | Operator::ReturnCall { function_index }
        | Operator::RefFunc { function_index } = operator
        {
            if targets.iter().any(|row| row.function == function_index) {
                return Err("rust-callback-original-direct-or-ref-bypass");
            }
        }
        if let Some((index, site)) = sites
            .iter()
            .enumerate()
            .find(|(_, row)| row.function == function && row.offset == start)
        {
            let Operator::CallIndirect {
                type_index,
                table_index,
            } = operator
            else {
                return Err("rust-callback-owner-site-not-indirect");
            };
            if table_index != 0
                || module.types.get(type_index as usize).copied()
                    != Some(module.signature(targets[site.target].function)?)
            {
                return Err("rust-callback-owner-site-type");
            }
            output.extend_from_slice(&body[previous..start]);
            output.push(0x10);
            unsigned(first_helper + index as u32, &mut output);
            previous = end;
            changed += 1;
        }
    }
    if changed != sites.iter().filter(|row| row.function == function).count() {
        return Err("rust-callback-owner-site-not-found");
    }
    output.extend_from_slice(&body[previous..]);
    Ok(output)
}

pub(crate) fn seal_original_callbacks(input: &[u8]) -> Result<Vec<u8>, &'static str> {
    let proof = verify(input)?;
    let module = Original::parse(input)?;
    let (targets, sites) = callback_plan(&module, &proof)?;
    let first_trap = module.functions.len() as u32;
    let first_helper = first_trap + targets.len() as u32;
    if first_helper + sites.len() as u32 > MAX_FUNCTIONS {
        return Err("rust-callback-function-bound");
    }
    let mut types = Vec::new();
    let mut functions = Vec::new();
    let mut bodies = Vec::new();
    for target in targets {
        let mut ty = Vec::new();
        unsigned(module.functions[target.function as usize], &mut ty);
        functions.push(ty);
        bodies.push(vec![0, 0, 0x0b]);
    }
    for site in sites {
        let target = targets[site.target];
        let signature = module.signature(target.function)?;
        let mut ty = vec![0x60];
        unsigned(signature.params.len() as u32 + 1, &mut ty);
        ty.extend_from_slice(signature.params);
        ty.push(0x7f);
        unsigned(signature.results.len() as u32, &mut ty);
        ty.extend_from_slice(signature.results);
        let mut function_type = Vec::new();
        unsigned(
            module.types.len() as u32 + types.len() as u32,
            &mut function_type,
        );
        types.push(ty);
        functions.push(function_type);
        bodies.push(dispatch_helper(
            target,
            signature,
            module.functions[target.function as usize],
            site.fallback,
        )?);
    }
    let mut code = Vec::new();
    unsigned(module.bodies.len() as u32 + bodies.len() as u32, &mut code);
    for (index, body) in module.bodies.iter().enumerate() {
        let changed = sealed_body(
            body,
            module.imports.len() as u32 + index as u32,
            &module,
            &targets,
            &sites,
            first_helper,
        )?;
        unsigned(changed.len() as u32, &mut code);
        code.extend_from_slice(&changed);
    }
    for body in bodies {
        unsigned(body.len() as u32, &mut code);
        code.extend_from_slice(&body);
    }
    let mut raw = BinaryReader::new(&input[8..], 8);
    let mut output = input[..8].to_vec();
    while !raw.eof() {
        let id = byte(&mut raw)?;
        let size = count(&mut raw, MAX_BYTES)?;
        let payload = raw
            .read_bytes(size)
            .map_err(|_| "rust-callback-section-payload")?;
        let rewritten;
        let payload: &[u8] = match id {
            1 => {
                rewritten = vector(payload, &types)?;
                &rewritten
            }
            3 => {
                rewritten = vector(payload, &functions)?;
                &rewritten
            }
            9 => {
                rewritten = sealed_elements(payload, &targets, first_trap)?;
                &rewritten
            }
            10 => &code,
            _ => payload,
        };
        output.push(id);
        unsigned(payload.len() as u32, &mut output);
        output.extend_from_slice(payload);
        if output.len() > MAX_BYTES {
            return Err("rust-callback-derived-byte-bound");
        }
    }
    audit_sealed_callbacks(&output, &targets, &sites, first_helper)?;
    Ok(output)
}

fn audit_sealed_callbacks(
    input: &[u8],
    targets: &[CallbackTarget; 5],
    sites: &[CallbackSite; 6],
    first_helper: u32,
) -> Result<(), &'static str> {
    let module = Original::parse(input)?;
    if module
        .table
        .iter()
        .any(|function| targets.iter().any(|row| row.function == *function))
        || module
            .exports
            .iter()
            .any(|row| row.kind == 0 && targets.iter().any(|target| target.function == row.index))
    {
        return Err("rust-callback-derived-table-or-export-leak");
    }
    let mut owner_counts = [0; 6];
    let mut target_counts = [0; 6];
    for (index, body) in module.bodies.iter().enumerate() {
        let function = module.imports.len() as u32 + index as u32;
        let parsed = wasmparser::FunctionBody::new(BinaryReader::new(body, 0));
        let mut reader = parsed
            .get_operators_reader()
            .map_err(|_| "rust-callback-audit-operators")?;
        while !reader.eof() {
            let operator = reader.read().map_err(|_| "rust-callback-audit-operator")?;
            if let Operator::Call { function_index }
            | Operator::ReturnCall { function_index }
            | Operator::RefFunc { function_index } = operator
            {
                if let Some(index) = (function.checked_sub(first_helper))
                    .filter(|index| (*index as usize) < sites.len())
                {
                    if targets
                        .iter()
                        .any(|target| target.function == function_index)
                    {
                        if !matches!(operator, Operator::Call { .. })
                            || targets[sites[index as usize].target].function != function_index
                        {
                            return Err("rust-callback-derived-helper-target-bypass");
                        }
                        target_counts[index as usize] += 1;
                    }
                } else if targets
                    .iter()
                    .any(|target| target.function == function_index)
                {
                    return Err("rust-callback-derived-direct-target-bypass");
                }
                if let Some(index) = function_index
                    .checked_sub(first_helper)
                    .filter(|index| (*index as usize) < sites.len())
                {
                    if !matches!(operator, Operator::Call { .. })
                        || function != sites[index as usize].function
                    {
                        return Err("rust-callback-derived-helper-caller-bypass");
                    }
                    owner_counts[index as usize] += 1;
                }
            }
        }
    }
    if owner_counts != [1; 6] || target_counts != [1; 6] {
        return Err("rust-callback-derived-six-owner-dispatch-closure");
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum Flow {
    Other,
    Trap,
    Block,
    Loop,
    If,
    Else,
    End,
    Return,
    Constant(i32),
    Branch(u32),
    BranchIf(u32),
    BranchTable { start: usize, count: usize },
}

fn branch_target(
    index: usize,
    depth: u32,
    parents: &[i32],
    ends: &[usize],
    flow: &[Flow],
    work: &mut usize,
) -> Result<usize, &'static str> {
    let mut label = parents[index];
    for _ in 0..depth {
        *work += 1;
        if *work > MAX_OPERATORS as usize || label < 0 {
            return Err("rust-result-branch-work-or-depth");
        }
        label = parents[label as usize];
    }
    if label < 0 {
        return Err("rust-result-function-label-branch-not-qualified");
    }
    let label = label as usize;
    Ok(if matches!(flow[label], Flow::Loop) {
        label + 1
    } else {
        ends[label] + 1
    })
}

fn static_return_area(body: &[u8]) -> Result<u32, &'static str> {
    let parsed = wasmparser::FunctionBody::new(BinaryReader::new(body, 0));
    let mut reader = parsed
        .get_operators_reader()
        .map_err(|_| "rust-result-public-operators")?;
    let mut flow = Vec::new();
    let mut branches = Vec::new();
    while !reader.eof() {
        if flow.len() >= 4096 {
            return Err("rust-result-public-operator-bound");
        }
        flow.push(
            match reader.read().map_err(|_| "rust-result-public-operator")? {
                Operator::Unreachable => Flow::Trap,
                Operator::Block { .. } => Flow::Block,
                Operator::Loop { .. } => Flow::Loop,
                Operator::If { .. } => Flow::If,
                Operator::Else => Flow::Else,
                Operator::End => Flow::End,
                Operator::Return => Flow::Return,
                Operator::I32Const { value } => Flow::Constant(value),
                Operator::Br { relative_depth } => Flow::Branch(relative_depth),
                Operator::BrIf { relative_depth } => Flow::BranchIf(relative_depth),
                Operator::BrTable { targets } => {
                    let start = branches.len();
                    if start + targets.len() as usize + 1 > MAX_OPERATORS as usize {
                        return Err("rust-result-branch-target-bound");
                    }
                    for target in targets.targets() {
                        branches.push(target.map_err(|_| "rust-result-branch-target")?);
                    }
                    branches.push(targets.default());
                    Flow::BranchTable {
                        start,
                        count: branches.len() - start,
                    }
                }
                Operator::ReturnCall { .. }
                | Operator::ReturnCallIndirect { .. }
                | Operator::ReturnCallRef { .. } => {
                    return Err("rust-result-tail-call-not-qualified");
                }
                _ => Flow::Other,
            },
        );
    }
    if flow.is_empty() {
        return Err("rust-result-empty-public-body");
    }
    let mut parents = vec![-1; flow.len()];
    let mut ends = vec![usize::MAX; flow.len()];
    let mut alternatives = vec![usize::MAX; flow.len()];
    let mut labels = vec![-1];
    let mut final_end = None;
    for (index, operator) in flow.iter().enumerate() {
        parents[index] = *labels
            .last()
            .ok_or("rust-result-control-after-function-end")?;
        match operator {
            Flow::Block | Flow::Loop | Flow::If => {
                if labels.len() >= 257 {
                    return Err("rust-result-control-depth");
                }
                labels.push(index as i32);
            }
            Flow::Else => {
                let label = parents[index];
                if label < 0
                    || !matches!(flow[label as usize], Flow::If)
                    || alternatives[label as usize] != usize::MAX
                {
                    return Err("rust-result-else-shape");
                }
                alternatives[label as usize] = index;
            }
            Flow::End => {
                let label = labels.pop().ok_or("rust-result-control-end")?;
                if label < 0 {
                    if index + 1 != flow.len() {
                        return Err("rust-result-trailing-function-operators");
                    }
                    final_end = Some(index);
                } else {
                    ends[label as usize] = index;
                }
            }
            _ => {}
        }
    }
    let final_end = final_end
        .filter(|_| labels.is_empty())
        .ok_or("rust-result-unclosed-control")?;
    let mut pending = Vec::with_capacity(flow.len());
    pending.push(0);
    let mut scheduled = vec![false; flow.len()];
    scheduled[0] = true;
    let mut head = 0;
    let mut edges = 0;
    let mut branch_work = 0;
    let mut returned = None;
    while head < pending.len() {
        let index = pending[head];
        head += 1;
        let mut enqueue = |target: usize| -> Result<(), &'static str> {
            edges += 1;
            if edges > MAX_OPERATORS as usize || target >= flow.len() {
                return Err("rust-result-control-edge-bound");
            }
            if !scheduled[target] {
                scheduled[target] = true;
                pending.push(target);
            }
            Ok(())
        };
        match flow[index] {
            Flow::Trap => {}
            Flow::Return | Flow::End
                if matches!(flow[index], Flow::Return) || index == final_end =>
            {
                let Some(Flow::Constant(value)) =
                    index.checked_sub(1).and_then(|previous| flow.get(previous))
                else {
                    return Err("rust-result-dynamic-or-unqualified-return");
                };
                if let Some(old) = returned {
                    if old != *value {
                        return Err("rust-result-distinct-static-returns");
                    }
                }
                returned = Some(*value);
            }
            Flow::Branch(depth) => enqueue(branch_target(
                index,
                depth,
                &parents,
                &ends,
                &flow,
                &mut branch_work,
            )?)?,
            Flow::BranchIf(depth) => {
                enqueue(index + 1)?;
                enqueue(branch_target(
                    index,
                    depth,
                    &parents,
                    &ends,
                    &flow,
                    &mut branch_work,
                )?)?;
            }
            Flow::BranchTable { start, count } => {
                for depth in &branches[start..start + count] {
                    enqueue(branch_target(
                        index,
                        *depth,
                        &parents,
                        &ends,
                        &flow,
                        &mut branch_work,
                    )?)?;
                }
            }
            Flow::If => {
                enqueue(index + 1)?;
                enqueue(if alternatives[index] == usize::MAX {
                    ends[index] + 1
                } else {
                    alternatives[index] + 1
                })?;
            }
            Flow::Else => enqueue(ends[parents[index] as usize] + 1)?,
            _ => enqueue(index + 1)?,
        }
    }
    returned
        .map(|value| value as u32)
        .ok_or("rust-result-no-reachable-static-return")
}

fn post_deallocator(body: &[u8]) -> Result<u32, &'static str> {
    let mut raw = BinaryReader::new(body, 0);
    if u32_value(&mut raw)? != 1 || u32_value(&mut raw)? != 1 || byte(&mut raw)? != 0x7f {
        return Err("rust-result-post-local-shape");
    }
    // Whole original WIT result<string,string> post body, including the empty
    // sentinel branch, payload offsets, align1 and one exact allocator call.
    let prefix = [
        2, 0x40, 0x20, 0, 0x28, 2, 8, 0x22, 1, 0x45, 0x0d, 0, 0x20, 0, 0x28, 2, 4, 0x20, 1, 0x41,
        1, 0x10,
    ];
    for wanted in prefix {
        if byte(&mut raw)? != wanted {
            return Err("rust-result-post-whole-body");
        }
    }
    let callee = u32_value(&mut raw)?;
    if byte(&mut raw)? != 0x0b || byte(&mut raw)? != 0x0b || !raw.eof() {
        return Err("rust-result-post-whole-body");
    }
    Ok(callee)
}

pub(crate) fn original_result_guard(
    input: &[u8],
    public: &str,
    post: &str,
) -> Result<super::CanonicalResultGuard, &'static str> {
    // Final host routing must ALSO bind the actual public WIT result type and
    // canonical lift/options. Supplying these names alone grants no routing.
    let proof = verify(input)?;
    let module = Original::parse(input)?;
    let public = module.export(public, 0)?;
    let post = module.export(post, 0)?;
    if public == post
        || module.signature(public)?.results != [0x7f]
        || module.signature(post)?
            != (Signature {
                params: &[0x7f],
                results: &[],
            })
    {
        return Err("rust-result-public-or-post-signature");
    }
    let area = static_return_area(module.body(public)?)?;
    let end = area
        .checked_add(12)
        .ok_or("rust-result-static-area-overflow")?;
    if area == 0 || area & 3 != 0 || end > module.stack_low {
        return Err("rust-result-static-area-original-stack-alias");
    }
    let mut data = 0;
    for (node, begin) in catalogue::NODES.iter().zip(proof.bindings) {
        if node.kind == 1 {
            data += 1;
            let finish = begin
                .checked_add(node.size as u32)
                .ok_or("rust-result-private-data-overflow")?;
            if node.size > 0 && area < finish && begin < end {
                return Err("rust-result-static-area-private-data-alias");
            }
        }
    }
    if data == 0 {
        return Err("rust-result-private-data-missing");
    }
    let deallocator = post_deallocator(module.body(post)?)?;
    if module.signature(deallocator)?
        != (Signature {
            params: &[0x7f, 0x7f, 0x7f],
            results: &[],
        })
        || compiler_shim(module.body(deallocator)?, 3)?
            != Some(source_role(&proof, "13___rdl_dealloc")?)
    {
        return Err("rust-result-original-post-allocator-closure");
    }
    Ok(super::CanonicalResultGuard {
        static_area: area,
        original_heap_low: module.stack_high,
    })
}

/// A source derivation receipt, never a caller-supplied host admission proof.
/// Native consumers recompute this derivation and the actual final component.
#[derive(Debug)]
pub struct RustSourceDerivationReceipt {
    pub original_digest: [u8; 32],
    pub derived_digest: [u8; 32],
    pub catalogue_origin_head: &'static str,
    pub catalogue_origin_recipe: &'static str,
    pub catalogue_body_digest: &'static str,
    pub original_panic_function: u32,
    pub root: super::RootReceipt,
    pub private_callbacks_isolated: bool,
    pub actual_component_graph_authenticated: bool,
    pub canonical_creation_enabled: bool,
    pub standard_runtime_qualified: bool,
}

/// Recompute the complete finite original-object/callback/result/System chain.
/// This does not authenticate WIT or canonical component routing, does not
/// select any engine profile, and cannot enable the closed normal builder.
pub fn derive_source_core(
    input: &[u8],
    public: &str,
    post: &str,
) -> Result<(Vec<u8>, RustSourceDerivationReceipt), &'static str> {
    use sha2::{Digest, Sha256};
    let proof = verify(input)?;
    if proof.stack_high.checked_sub(proof.stack_low) != Some(1024 * 1024 + 65536)
        || proof.memory_bytes as usize > MAX_MEMORY
    {
        return Err("rust-source-original-root-and-system-reservation");
    }
    let raw_panic = source_role(&proof, "_4core9panicking9panic_fmt")?;
    let original = Original::parse(input)?;
    if original.signature(raw_panic)?
        != (Signature {
            params: &[0x7f, 0x7f, 0x7f],
            results: &[],
        })
    {
        return Err("rust-source-authentic-panic-signature");
    }
    let result_guard = original_result_guard(input, public, post)?;
    let sealed = seal_original_callbacks(input)?;
    let (prepared, public_receipt) =
        super::prepare_owned_public_root(&sealed, Sha256::digest(&sealed).into(), public)?;
    let (threaded, thread) =
        super::transform_owned_thread_entry(&prepared, public_receipt.derived_digest)?;
    let panic_function = raw_panic
        .checked_add(u32::from(
            public_receipt.native_import_inserted
                && raw_panic >= public_receipt.native_admission_import,
        ))
        .ok_or("rust-source-panic-function-remap")?;
    let threaded_module = Original::parse(&threaded)?;
    let panic_body_digest = Sha256::digest(threaded_module.body(panic_function)?).into();
    let (rooted, root) = super::transform_owned_guarded_canonical_root_with_system_panic_trap(
        &threaded,
        thread.stack.derived_digest,
        &thread,
        post,
        "cabi_realloc",
        result_guard,
        super::CanonicalSystemPanicTrap {
            function: panic_function,
            body_digest: panic_body_digest,
        },
    )?;
    if root.root_stack_low != proof.stack_low
        || root.root_stack_high != proof.stack_low + 1024 * 1024
        || root.canonical_system_stack_low != Some(root.root_stack_high)
        || root.canonical_system_stack_high != Some(proof.stack_high)
    {
        return Err("rust-source-derived-reservation-drift");
    }
    let (derived, _) = super::transform_owned_thread_admission(&rooted, root.derived_digest)?;
    let derived = super::rust_component::adapt_original_public_wit(&derived)?;
    let derived_digest = Sha256::digest(&derived).into();
    Ok((
        derived,
        RustSourceDerivationReceipt {
            original_digest: Sha256::digest(input).into(),
            derived_digest,
            catalogue_origin_head: catalogue::ORIGIN_HEAD,
            catalogue_origin_recipe: catalogue::ORIGIN_RECIPE,
            catalogue_body_digest: catalogue::BODY_DIGEST,
            original_panic_function: raw_panic,
            root,
            private_callbacks_isolated: true,
            actual_component_graph_authenticated: false,
            canonical_creation_enabled: false,
            standard_runtime_qualified: false,
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    const ORIGINAL: &[u8] = include_bytes!("rust_catalogue/reviewed-original-core.wasm");
    const PUBLIC: &str = "examples:greeting/api@1.0.0#greet";
    const POST: &str = "cabi_post_examples:greeting/api@1.0.0#greet";

    fn body_start(input: &[u8], selected: u32, imported: usize) -> usize {
        let mut function = imported as u32;
        for payload in Parser::new(0).parse_all(input) {
            if let Payload::CodeSectionEntry(body) = payload.unwrap() {
                if function == selected {
                    return body.range().start as usize;
                }
                function += 1;
            }
        }
        panic!("reviewed body missing");
    }
    fn replace_body(input: &[u8], selected: u32, replacement: &[u8]) -> Vec<u8> {
        let original = Original::parse(input).unwrap();
        let mut module = BinaryReader::new(&input[8..], 8);
        let mut output = input[..8].to_vec();
        while !module.eof() {
            let id = byte(&mut module).unwrap();
            let size = count(&mut module, MAX_BYTES).unwrap();
            let data = module.read_bytes(size).unwrap();
            let mut code = Vec::new();
            if id == 10 {
                unsigned(original.bodies.len() as u32, &mut code);
                for (index, body) in original.bodies.iter().enumerate() {
                    let body = if index + original.imports.len() == selected as usize {
                        replacement
                    } else {
                        body
                    };
                    unsigned(body.len() as u32, &mut code);
                    code.extend_from_slice(body);
                }
            }
            let data: &[u8] = if id == 10 { &code } else { data };
            output.push(id);
            unsigned(data.len() as u32, &mut output);
            output.extend_from_slice(data);
        }
        output
    }

    #[test]
    fn rust_original_catalogue_checks_complete_bodies_and_every_real_global_import_referent() {
        let proof = verify(ORIGINAL).unwrap();
        assert!(!proof.bindings.contains(&UNBOUND));
        assert_eq!(
            (proof.stack_low, proof.stack_high, proof.memory_bytes),
            (27552, 1141664, 1179648)
        );
        let module = Original::parse(ORIGINAL).unwrap();
        let selected = source_role(&proof, "runtime13executor_root12progress_all").unwrap();
        let node = catalogue::NODES
            .iter()
            .zip(proof.bindings)
            .find(|(node, index)| node.kind == 0 && *index == selected)
            .unwrap()
            .0;
        let body = module.body(selected).unwrap();
        let start = body_start(ORIGINAL, selected, module.imports.len());
        let parsed = wasmparser::FunctionBody::new(BinaryReader::new(body, 0));
        let mut reader = parsed.get_operators_reader().unwrap();
        let mut changed = None;
        while !reader.eof() {
            let offset = usize::try_from(reader.original_position()).unwrap();
            if matches!(reader.read().unwrap(), Operator::I32Const { value: 0..=31 })
                && !node.references.iter().any(|reference| {
                    reference.offset <= offset + 1
                        && offset + 1 < reference.offset + reference.extent
                })
            {
                let mut raw = ORIGINAL.to_vec();
                raw[start + offset + 1] ^= 1;
                changed = Some(raw);
                break;
            }
        }
        assert_eq!(
            verify(&changed.unwrap()).unwrap_err(),
            "rust-original-full-body-or-signature"
        );
        let mut changed = None;
        for (node, index) in catalogue::NODES.iter().zip(proof.bindings) {
            if node.kind != 0 {
                continue;
            }
            let body = module.body(index).unwrap();
            for reference in node.references {
                if reference.kind == 7
                    && reference.offset > 0
                    && body[reference.offset - 1] == 0x23
                    && relocation(
                        &body[reference.offset..reference.offset + reference.extent],
                        reference,
                    )
                    .unwrap()
                        == 0
                {
                    let mut raw = ORIGINAL.to_vec();
                    raw[body_start(ORIGINAL, index, module.imports.len()) + reference.offset] ^= 1;
                    changed = Some(raw);
                    break;
                }
            }
            if changed.is_some() {
                break;
            }
        }
        assert_eq!(
            verify(&changed.unwrap()).unwrap_err(),
            "rust-original-global-or-table-reference"
        );
        let mut raw = ORIGINAL.to_vec();
        let import = raw
            .windows(8)
            .position(|bytes| bytes == b"register")
            .unwrap();
        raw[import] = b'x';
        assert_eq!(
            verify(&raw).unwrap_err(),
            "rust-original-exact-import-reference"
        );
    }

    #[test]
    fn rust_original_derivation_closes_private_owner_dispatch_result_area_and_system_failure() {
        use sha2::{Digest, Sha256};
        let proof = verify(ORIGINAL).unwrap();
        let module = Original::parse(ORIGINAL).unwrap();
        let (targets, sites) = callback_plan(&module, &proof).unwrap();
        assert_eq!(sites.iter().filter(|site| site.fallback).count(), 1);
        let sealed = seal_original_callbacks(ORIGINAL).unwrap();
        // Exact independently retained Python production derivation from the
        // authenticated 9d0e11d event. This is an emission comparison, not execution.
        assert_eq!(
            Sha256::digest(&sealed)
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>(),
            "85e67b8fe9ad9a888b3543b26f63261f906e70a03caec9d2c4ca5f0bf4a7cfa8"
        );
        let sealed_module = Original::parse(&sealed).unwrap();
        for (index, function) in module.table.iter().enumerate() {
            if let Some(target) = targets.iter().find(|target| target.slot as usize == index) {
                assert_ne!(sealed_module.table[index], target.function);
                assert_eq!(
                    sealed_module.body(sealed_module.table[index]).unwrap(),
                    [0, 0, 0x0b]
                );
            } else {
                assert_eq!(sealed_module.table[index], *function);
            }
        }
        let post = module.export(POST, 0).unwrap();
        let mut direct = vec![0, 0x20, 0, 0x10];
        unsigned(targets[1].function, &mut direct);
        direct.push(0x0b);
        let bypass = replace_body(ORIGINAL, post, &direct);
        assert_eq!(
            seal_original_callbacks(&bypass).unwrap_err(),
            "rust-callback-original-direct-or-ref-bypass"
        );
        let target_type = module.functions[targets[1].function as usize];
        let mut indirect = vec![0, 0x20, 0, 0x41];
        signed(targets[1].slot as i32, &mut indirect);
        indirect.push(0x11);
        unsigned(target_type, &mut indirect);
        indirect.extend_from_slice(&[0, 0x0b]);
        let ordinary = replace_body(ORIGINAL, post, &indirect);
        let ordinary = seal_original_callbacks(&ordinary).unwrap();
        let ordinary = Original::parse(&ordinary).unwrap();
        assert_eq!(
            ordinary
                .body(ordinary.table[targets[1].slot as usize])
                .unwrap(),
            [0, 0, 0x0b]
        );
        let (derived, receipt) = derive_source_core(ORIGINAL, PUBLIC, POST).unwrap();
        Validator::new().validate_all(&derived).unwrap();
        assert_eq!(
            Sha256::digest(&derived)
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>(),
            "261f4cd27a9f8229793ed6e5521986e8e3c0249eec800363394b1591292e8b57"
        );
        assert_eq!(receipt.original_panic_function, 527);
        assert_eq!(receipt.root.canonical_system_panic_trap, Some(528));
        assert_eq!(receipt.root.canonical_system_stack_high, Some(1141664));
        assert_eq!(
            receipt.root.root_stack_high - receipt.root.root_stack_low,
            1024 * 1024
        );
        assert!(
            receipt.root.canonical_result_guard_installed && receipt.private_callbacks_isolated
        );
        assert!(
            !receipt.actual_component_graph_authenticated
                && !receipt.canonical_creation_enabled
                && !receipt.standard_runtime_qualified
        );
    }
}
