//! Bounded original-core proof data for an explicitly selected C profile.
//!
//! The section is untrusted input, never a selector or an authentication marker.
//! Every consumer recomputes the full C derivation and actual component graph.
use super::*;
use std::borrow::Cow;
use wasm_encoder::{CustomSection, Encode, Section};

pub const C_PREIMAGE_SECTION: &str = "latent-c-original-core-v1";
pub const MAX_C_PREIMAGE_BYTES: usize = 1024 * 1024;
pub const MAX_C_RECOMPUTED_IMAGE_BYTES: usize = 2 * 1024 * 1024;
// Owned working allowance, not an RSS measurement. The C-only preflight below
// limits every input to the finite shape used by this calculation. Sixteen
// 2MiB byte-image units cover simultaneously retained reencoder capacity,
// intermediate cores, old/new snapshots, section copies and the TLS image.
// Eight MiB separately covers bounded signature/graph/edge containers, and
// eight MiB covers the pinned validator's bounded scalar/control/local state.
// Original component storage is charged IN ADDITION to this work allowance.
pub const C_VERIFICATION_WORK_BYTES: usize =
    16 * MAX_C_RECOMPUTED_IMAGE_BYTES + 8 * 1024 * 1024 + 8 * 1024 * 1024;
// Aggregate work is finite, but aggregate count alone cannot bound a value
// stack: one permitted scalar call can return32 values. Limit each body BEFORE
// typed decoding/validation. The pinned validator reuses one operand arena
// across bodies. At8B/cell, <=4MiB new operand backing may coexist with
// <=2MiB old backing during growth: <=6MiB transient, plus <=2MiB for
// bounded numeric metadata/locals/control in the ORIGINAL8MiB envelope.
// Other scalar/container limits and the separate65,536-edge bound remain.
const MAX_ORIGINAL_OPERATORS: u64 = 32 * 1024;
const MAX_DERIVED_OPERATORS: u64 = 64 * 1024;
const MAX_FUNCTION_OPERATORS: u64 = 8 * 1024;
const MAGIC: &[u8; 8] = b"LSFCPR01";
const HEADER_BYTES: usize = 20;
const MAX_PUBLIC_BYTES: usize = 512;

struct Original<'a> {
    core: &'a [u8],
    public: &'a str,
}

fn finite_i32_offset(raw: &mut wasmparser::BinaryReader<'_>) -> Result<(), &'static str> {
    if !matches!(raw.read_u8(), Ok(0x41)) {
        return Err("c-preimage-finite-offset");
    }
    raw.read_var_i32().map_err(|_| "c-preimage-finite-offset")?;
    if !matches!(raw.read_u8(), Ok(0x0b)) {
        return Err("c-preimage-finite-offset");
    }
    Ok(())
}

fn bounded_core(input: &[u8], original: bool) -> Result<u64, &'static str> {
    if input.len() > MAX_C_RECOMPUTED_IMAGE_BYTES {
        return Err("c-preimage-finite-core-byte-bound");
    }
    let mut functions = 0u32;
    let mut operators = 0;
    let mut globals = 0u32;
    let mut imports = 0u32;
    let mut locals = 0u64;
    for (ordinal, payload) in Parser::new(0).parse_all(input).enumerate() {
        if ordinal >= 512 {
            return Err("c-preimage-finite-core-section-bound");
        }
        match payload.map_err(|_| "c-preimage-finite-core-parse")? {
            Payload::TypeSection(reader) => {
                if reader.count() > 160 {
                    return Err("c-preimage-finite-type-count");
                }
                // Read the closed numeric encoding directly before FuncType
                // decoding could allocate a declared GC group or parameter Vec.
                let range = reader.range();
                let mut raw = wasmparser::BinaryReader::new(
                    input
                        .get(range.start as usize..range.end as usize)
                        .ok_or("c-preimage-finite-type-range")?,
                    range.start,
                );
                let count = raw
                    .read_var_u32()
                    .map_err(|_| "c-preimage-finite-type-count")?;
                for _ in 0..count {
                    if raw.read_u8().map_err(|_| "c-preimage-finite-scalar-type")? != 0x60 {
                        return Err("c-preimage-finite-scalar-type");
                    }
                    let mut width = 0;
                    for _ in 0..2 {
                        let count = raw
                            .read_var_u32()
                            .map_err(|_| "c-preimage-finite-scalar-signature")?;
                        width += u64::from(count);
                        if width > 32 {
                            return Err("c-preimage-finite-scalar-signature");
                        }
                        for _ in 0..count {
                            if !matches!(raw.read_u8(), Ok(0x7c..=0x7f)) {
                                return Err("c-preimage-finite-scalar-type");
                            }
                        }
                    }
                }
                if !raw.eof() {
                    return Err("c-preimage-finite-type-trailing");
                }
            }
            Payload::ImportSection(reader) => {
                if reader.count() > 64 {
                    return Err("c-preimage-finite-import-count");
                }
                for import in reader.into_imports() {
                    imports += 1;
                    if imports > 64 {
                        return Err("c-preimage-finite-import-count");
                    }
                    let import = import.map_err(|_| "c-preimage-finite-import")?;
                    if import.module.len() > 512 || import.name.len() > 512 {
                        return Err("c-preimage-finite-import-name");
                    }
                    if matches!(import.ty, TypeRef::Func(_) | TypeRef::FuncExact(_)) {
                        functions = functions
                            .checked_add(1)
                            .ok_or("c-preimage-finite-function-count")?;
                    }
                }
            }
            Payload::FunctionSection(reader) => {
                functions = functions
                    .checked_add(reader.count())
                    .ok_or("c-preimage-finite-function-count")?
            }
            Payload::TableSection(reader) => {
                if reader.count() > 8 {
                    return Err("c-preimage-finite-table-count");
                }
                let range = reader.range();
                let mut raw = wasmparser::BinaryReader::new(
                    input
                        .get(range.start as usize..range.end as usize)
                        .ok_or("c-preimage-finite-table-range")?,
                    range.start,
                );
                let count = raw
                    .read_var_u32()
                    .map_err(|_| "c-preimage-finite-table-count")?;
                for _ in 0..count {
                    // Ordinary funcref tables only: no allocating initializer
                    // ConstExpr reader or indexed/recursive reference types.
                    if !matches!(raw.read_u8(), Ok(0x70)) {
                        return Err("c-preimage-finite-table-type");
                    }
                    let flags = raw
                        .read_u8()
                        .map_err(|_| "c-preimage-finite-table-limits")?;
                    if flags > 1 {
                        return Err("c-preimage-finite-table-limits");
                    }
                    raw.read_var_u32()
                        .map_err(|_| "c-preimage-finite-table-limits")?;
                    if flags == 1 {
                        raw.read_var_u32()
                            .map_err(|_| "c-preimage-finite-table-limits")?;
                    }
                }
                if !raw.eof() {
                    return Err("c-preimage-finite-table-trailing");
                }
            }
            Payload::MemorySection(reader) if reader.count() > 8 => {
                return Err("c-preimage-finite-memory-count");
            }
            Payload::TagSection(_) => return Err("c-preimage-finite-numeric-control-only"),
            Payload::GlobalSection(reader) => {
                globals = globals
                    .checked_add(reader.count())
                    .ok_or("c-preimage-finite-global-count")?;
                if globals > 256 {
                    return Err("c-preimage-finite-global-count");
                }
                let range = reader.range();
                let mut raw = wasmparser::BinaryReader::new(
                    input
                        .get(range.start as usize..range.end as usize)
                        .ok_or("c-preimage-finite-global-range")?,
                    range.start,
                );
                let count = raw
                    .read_var_u32()
                    .map_err(|_| "c-preimage-finite-global-count")?;
                for _ in 0..count {
                    if !matches!(raw.read_u8(), Ok(0x7c..=0x7f))
                        || !matches!(raw.read_u8(), Ok(0 | 1))
                    {
                        return Err("c-preimage-finite-global-type");
                    }
                    match raw
                        .read_u8()
                        .map_err(|_| "c-preimage-finite-global-constant")?
                    {
                        0x41 => {
                            raw.read_var_i32()
                                .map_err(|_| "c-preimage-finite-global-constant")?;
                        }
                        0x42 => {
                            raw.read_var_i64()
                                .map_err(|_| "c-preimage-finite-global-constant")?;
                        }
                        0x43 => {
                            raw.read_bytes(4)
                                .map_err(|_| "c-preimage-finite-global-constant")?;
                        }
                        0x44 => {
                            raw.read_bytes(8)
                                .map_err(|_| "c-preimage-finite-global-constant")?;
                        }
                        _ => return Err("c-preimage-finite-global-constant"),
                    }
                    if raw.read_u8().map_err(|_| "c-preimage-finite-global-end")? != 0x0b {
                        return Err("c-preimage-finite-global-end");
                    }
                }
                if !raw.eof() {
                    return Err("c-preimage-finite-global-trailing");
                }
            }
            Payload::ExportSection(reader) => {
                if reader.count() > 128 {
                    return Err("c-preimage-finite-export-count");
                }
                for export in reader {
                    if export.map_err(|_| "c-preimage-finite-export")?.name.len() > 512 {
                        return Err("c-preimage-finite-export-name");
                    }
                }
            }
            Payload::DataSection(reader) => {
                if reader.count() > 256 {
                    return Err("c-preimage-finite-data-count");
                }
                // Do not let a typed ConstExpr reader allocate exception/GC
                // state before enforcing the finite constant-offset encoding.
                let range = reader.range();
                let mut raw = wasmparser::BinaryReader::new(
                    input
                        .get(range.start as usize..range.end as usize)
                        .ok_or("c-preimage-finite-data-range")?,
                    range.start,
                );
                let count = raw
                    .read_var_u32()
                    .map_err(|_| "c-preimage-finite-data-count")?;
                for _ in 0..count {
                    match raw
                        .read_var_u32()
                        .map_err(|_| "c-preimage-finite-data-flags")?
                    {
                        0 => finite_i32_offset(&mut raw)?,
                        1 => {}
                        2 => {
                            raw.read_var_u32()
                                .map_err(|_| "c-preimage-finite-data-memory")?;
                            finite_i32_offset(&mut raw)?;
                        }
                        _ => return Err("c-preimage-finite-data-flags"),
                    }
                    let bytes = raw
                        .read_var_u32()
                        .map_err(|_| "c-preimage-finite-data-bytes")?;
                    raw.read_bytes(bytes as usize)
                        .map_err(|_| "c-preimage-finite-data-bytes")?;
                }
                if !raw.eof() {
                    return Err("c-preimage-finite-data-trailing");
                }
            }
            Payload::ElementSection(reader) => {
                if reader.count() > 256 {
                    return Err("c-preimage-finite-element-count");
                }
                let range = reader.range();
                let mut raw = wasmparser::BinaryReader::new(
                    input
                        .get(range.start as usize..range.end as usize)
                        .ok_or("c-preimage-finite-element-range")?,
                    range.start,
                );
                let groups = raw
                    .read_var_u32()
                    .map_err(|_| "c-preimage-finite-element-count")?;
                for _ in 0..groups {
                    let flags = raw
                        .read_var_u32()
                        .map_err(|_| "c-preimage-finite-element-flags")?;
                    match flags {
                        0 => finite_i32_offset(&mut raw)?,
                        1 | 3 => {}
                        2 => {
                            raw.read_var_u32()
                                .map_err(|_| "c-preimage-finite-element-table")?;
                            finite_i32_offset(&mut raw)?;
                        }
                        _ => return Err("c-preimage-finite-function-elements-only"),
                    }
                    if flags != 0 && !matches!(raw.read_u8(), Ok(0)) {
                        return Err("c-preimage-finite-element-kind");
                    }
                    let count = raw
                        .read_var_u32()
                        .map_err(|_| "c-preimage-finite-element-items")?;
                    if count > 256 {
                        return Err("c-preimage-finite-element-items");
                    }
                    for _ in 0..count {
                        raw.read_var_u32()
                            .map_err(|_| "c-preimage-finite-element-function")?;
                    }
                }
                if !raw.eof() {
                    return Err("c-preimage-finite-element-trailing");
                }
            }
            Payload::CodeSectionEntry(body) => {
                let mut depth = 0u32;
                let mut function_operators = 0u64;
                let declarations = body
                    .get_locals_reader()
                    .map_err(|_| "c-preimage-finite-locals")?;
                if declarations.get_count() > 256 {
                    return Err("c-preimage-finite-local-groups");
                }
                for declaration in declarations {
                    let (count, ty) = declaration.map_err(|_| "c-preimage-finite-local")?;
                    if !matches!(
                        ty,
                        wasmparser::ValType::I32
                            | wasmparser::ValType::I64
                            | wasmparser::ValType::F32
                            | wasmparser::ValType::F64
                    ) {
                        return Err("c-preimage-finite-local-type");
                    }
                    locals = locals
                        .checked_add(u64::from(count))
                        .ok_or("c-preimage-finite-local-overflow")?;
                    if locals > 4096 {
                        return Err("c-preimage-finite-local-count");
                    }
                }
                let mut reader = body
                    .get_operators_reader()
                    .map_err(|_| "c-preimage-finite-code")?;
                while !reader.eof() {
                    // Reject allocation-bearing exception/GC forms before the
                    // typed operator reader constructs catch/type arrays.
                    let opcode = reader
                        .get_binary_reader()
                        .read_u8()
                        .map_err(|_| "c-preimage-finite-opcode")?;
                    if matches!(opcode, 0x06..=0x0a | 0x18 | 0x19 | 0x1c | 0x1f | 0xe0..=0xe6 | 0xfb | 0xfd | 0xfe)
                    {
                        return Err("c-preimage-finite-numeric-control-only");
                    }
                    if opcode == 0x0e {
                        let mut raw = reader.get_binary_reader();
                        raw.read_u8().map_err(|_| "c-preimage-finite-opcode")?;
                        if raw
                            .read_var_u32()
                            .map_err(|_| "c-preimage-finite-branch-table")?
                            > 256
                        {
                            return Err("c-preimage-finite-branch-table");
                        }
                    }
                    function_operators += 1;
                    if function_operators > MAX_FUNCTION_OPERATORS {
                        return Err("c-preimage-finite-function-operator-count");
                    }
                    operators += 1;
                    if operators
                        > if original {
                            MAX_ORIGINAL_OPERATORS
                        } else {
                            MAX_DERIVED_OPERATORS
                        }
                    {
                        return Err("c-preimage-finite-operator-count");
                    }
                    match reader.read().map_err(|_| "c-preimage-finite-operator")? {
                        Operator::Block { .. } | Operator::Loop { .. } | Operator::If { .. } => {
                            depth += 1;
                            if depth > 256 {
                                return Err("c-preimage-finite-control-depth");
                            }
                        }
                        Operator::End => depth = depth.saturating_sub(1),
                        Operator::BrTable { targets } if targets.len() > 256 => {
                            return Err("c-preimage-finite-branch-table");
                        }
                        _ => {}
                    }
                }
            }
            _ => {}
        }
        if functions > if original { 256 } else { 280 } || globals > 256 {
            return Err("c-preimage-finite-function-or-global-count");
        }
    }
    Ok(operators)
}

// This is a conservative byte envelope, not a type decoder or a rewriting pass.
// Every unsigned count is either one byte (<128), or a suffix of a maximal
// high-bit run ending in a low byte. The value of that whole run is at least
// the suffix value, so this also bounds every preallocating reader's count.
// Signed valtypes use their ordinary one-byte tags. Larger signed encodings,
// indices and non-ASCII names may be refused by this first finite profile.
// Component structural encodings contain no floating-point literals; f32/f64
// are type tags. Core modules and custom payloads are deliberately excluded.
fn finite_type_encoding(bytes: &[u8]) -> Result<(), &'static str> {
    let mut position = 0;
    while position < bytes.len() {
        if bytes[position] & 0x80 == 0 {
            position += 1;
            continue;
        }
        let mut value = 0u64;
        let mut shift = 0;
        loop {
            let byte = *bytes
                .get(position)
                .ok_or("c-preimage-finite-type-integer-envelope")?;
            position += 1;
            value |= u64::from(byte & 0x7f) << shift;
            if value > 256 {
                return Err("c-preimage-finite-type-integer-envelope");
            }
            if byte & 0x80 == 0 {
                break;
            }
            shift += 7;
            if shift >= 35 {
                return Err("c-preimage-finite-type-integer-envelope");
            }
        }
    }
    Ok(())
}

// Framing must precede Parser: its component-start payload eagerly collects
// arguments, and later instance readers collect attacker-declared vectors.
// Borrow two component containers; never follow or scan core/custom payloads.
fn finite_component_leaves(component: &[u8]) -> Result<(), &'static str> {
    let mut containers = [Some(component), None];
    let mut sections = 0usize;
    let mut children = 0usize;
    for depth in 0..containers.len() {
        let Some(bytes) = containers[depth] else {
            break;
        };
        if bytes.get(..8) != Some(b"\0asm\x0d\0\x01\0") {
            return Err("c-preimage-finite-component-framing");
        }
        let mut raw = wasmparser::BinaryReader::new(&bytes[8..], 0);
        while !raw.eof() {
            sections += 1;
            if sections > 4096 {
                return Err("c-preimage-finite-component-rows");
            }
            let id = raw
                .read_u8()
                .map_err(|_| "c-preimage-finite-component-framing")?;
            let size = raw
                .read_var_u32()
                .map_err(|_| "c-preimage-finite-component-framing")?;
            let payload = raw
                .read_bytes(size as usize)
                .map_err(|_| "c-preimage-finite-component-framing")?;
            match id {
                0 | 1 => {} // Custom payload or an independently bounded core.
                4 => {
                    children += 1;
                    if depth != 0 || children > 1 {
                        return Err("c-preimage-finite-nested-component-count");
                    }
                    containers[1] = Some(payload);
                }
                2 | 3 | 5..=11 => {
                    if payload.len() > 64 * 1024 {
                        return Err("c-preimage-finite-component-structure-bytes");
                    }
                    if matches!(id, 3 | 7) {
                        finite_type_encoding(payload)?;
                    } else {
                        finite_type_encoding(payload)
                            .map_err(|_| "c-preimage-finite-structural-integer-envelope")?;
                    }
                }
                _ => return Err("c-preimage-finite-component-framing"),
            }
        }
    }
    Ok(())
}

// This runs only AFTER the caller admits C_VERIFICATION_WORK_BYTES. It rejects
// expansive shapes before invoking any full Validator or recomputing a core.
fn finite_preflight(component: &[u8], original: &[u8]) -> Result<(), &'static str> {
    finite_component_leaves(component)?;
    let accesses = bounded_core(original, true)?;
    let mut modules = 0;
    let mut rows = 0;
    let mut depth = 0usize;
    let mut encodings = [true; 2];
    let mut is_component = true;
    let mut components = 0;
    let mut instances = 0u32;
    let mut component_instances = 0u32;
    let mut aliases = 0u32;
    let mut canonical = 0u32;
    let mut type_prefixes = 0usize;
    let mut type_bytes = 0usize;
    for payload in Parser::new(0).parse_all(component) {
        let payload = payload.map_err(|_| "c-preimage-finite-component")?;
        rows += 1;
        if rows > 4096 {
            return Err("c-preimage-finite-component-rows");
        }
        if let Payload::ModuleSection {
            unchecked_range, ..
        } = &payload
        {
            modules += 1;
            if modules > 4 {
                return Err("c-preimage-finite-module-count");
            }
            let start = usize::try_from(unchecked_range.start)
                .map_err(|_| "c-preimage-finite-core-range")?;
            let end =
                usize::try_from(unchecked_range.end).map_err(|_| "c-preimage-finite-core-range")?;
            bounded_core(
                component
                    .get(start..end)
                    .ok_or("c-preimage-finite-core-range")?,
                false,
            )?;
        }
        if matches!(payload, Payload::ComponentSection { .. }) {
            components += 1;
            if components > 1 {
                return Err("c-preimage-finite-nested-component-count");
            }
        }
        if is_component {
            match &payload {
                Payload::InstanceSection(reader) => {
                    instances = instances
                        .checked_add(reader.count())
                        .ok_or("c-preimage-finite-instances")?
                }
                Payload::ComponentInstanceSection(reader) => {
                    component_instances = component_instances
                        .checked_add(reader.count())
                        .ok_or("c-preimage-finite-instances")?
                }
                Payload::ComponentAliasSection(reader) => {
                    aliases = aliases
                        .checked_add(reader.count())
                        .ok_or("c-preimage-finite-aliases")?
                }
                Payload::ComponentCanonicalSection(reader) => {
                    canonical = canonical
                        .checked_add(reader.count())
                        .ok_or("c-preimage-finite-canonical")?
                }
                Payload::CoreTypeSection(_) | Payload::ComponentTypeSection(_) => {
                    let (_, range) = payload.as_section().ok_or("c-preimage-finite-type-range")?;
                    let start =
                        usize::try_from(range.start).map_err(|_| "c-preimage-finite-type-range")?;
                    let end =
                        usize::try_from(range.end).map_err(|_| "c-preimage-finite-type-range")?;
                    let bytes = component
                        .get(start..end)
                        .ok_or("c-preimage-finite-type-range")?;
                    type_bytes = type_bytes
                        .checked_add(bytes.len())
                        .ok_or("c-preimage-finite-type-encoding-bytes")?;
                    if type_bytes > 16 * 1024 {
                        return Err("c-preimage-finite-type-encoding-bytes");
                    }
                    finite_type_encoding(bytes)?;
                    // A conservative raw-byte ceiling BEFORE recursive typed
                    // decoding. Every nested component/instance/module type
                    // necessarily consumes one of these prefixes. Counting
                    // coincident string/index bytes too can only refuse a
                    // wider encoding; it cannot undercount actual nesting.
                    type_prefixes += bytes
                        .iter()
                        .filter(|b| matches!(**b, 0x41 | 0x42 | 0x50))
                        .count();
                }
                _ => {}
            }
            if instances > 32
                || component_instances > 32
                || aliases > 512
                || canonical > 256
                || type_prefixes > 16
            {
                return Err("c-preimage-finite-component-container-bound");
            }
        }
        if is_component
            && !matches!(
                payload,
                Payload::ModuleSection { .. } | Payload::ComponentSection { .. }
            )
            && let Some((id, range)) = payload.as_section()
            && id != 0
            && id != 1
            && range.end - range.start > 64 * 1024
        {
            return Err("c-preimage-finite-component-structure-bytes");
        }
        match payload {
            Payload::ModuleSection { .. } | Payload::ComponentSection { .. } => {
                if depth == encodings.len() {
                    return Err("c-preimage-finite-encoding-depth");
                }
                encodings[depth] = is_component;
                depth += 1;
                is_component = matches!(payload, Payload::ComponentSection { .. });
            }
            Payload::End(_) if depth != 0 => {
                depth -= 1;
                is_component = encodings[depth];
            }
            _ => {}
        }
    }
    let (_, extent) = c_context::original_template_layout(original)?;
    if extent > 128 * 1024
        || original
            .len()
            .checked_add(extent as usize)
            .and_then(|n| n.checked_add(accesses as usize * 16))
            .and_then(|n| n.checked_add(128 * 1024))
            .is_none_or(|n| n > MAX_C_RECOMPUTED_IMAGE_BYTES)
    {
        return Err("c-preimage-finite-derived-image-bound");
    }
    Ok(())
}

fn public_name(public: &str) -> Result<(), &'static str> {
    if public.is_empty() || public.len() > MAX_PUBLIC_BYTES || public.chars().any(char::is_control)
    {
        return Err("c-preimage-public-name");
    }
    Ok(())
}

fn decode(input: &[u8]) -> Result<Original<'_>, &'static str> {
    if !(HEADER_BYTES..=MAX_C_PREIMAGE_BYTES).contains(&input.len()) {
        return Err("c-preimage-payload-bound");
    }
    if input.get(..8) != Some(MAGIC) {
        return Err("c-preimage-magic");
    }
    let read = |start| u32::from_le_bytes(input[start..start + 4].try_into().unwrap());
    if read(8) != 1 {
        return Err("c-preimage-version");
    }
    let name_bytes = usize::try_from(read(12)).map_err(|_| "c-preimage-public-bound")?;
    let core_bytes = usize::try_from(read(16)).map_err(|_| "c-preimage-core-bound")?;
    let core_start = HEADER_BYTES
        .checked_add(name_bytes)
        .ok_or("c-preimage-length-overflow")?;
    if name_bytes > MAX_PUBLIC_BYTES
        || core_start.checked_add(core_bytes) != Some(input.len())
        || core_bytes < 8
    {
        return Err("c-preimage-exact-lengths");
    }
    let public = std::str::from_utf8(
        input
            .get(HEADER_BYTES..core_start)
            .ok_or("c-preimage-public-bound")?,
    )
    .map_err(|_| "c-preimage-public-utf8")?;
    public_name(public)?;
    let core = input.get(core_start..).ok_or("c-preimage-core-bound")?;
    if core.get(..8) != Some(b"\0asm\x01\0\0\0") {
        return Err("c-preimage-original-core-encoding");
    }
    Ok(Original { core, public })
}

fn encode(core: &[u8], public: &str) -> Result<Vec<u8>, &'static str> {
    let total = check_original_envelope(core, public)?;
    let name_bytes = u32::try_from(public.len()).map_err(|_| "c-preimage-public-bound")?;
    let core_bytes = u32::try_from(core.len()).map_err(|_| "c-preimage-core-bound")?;
    let mut payload = Vec::with_capacity(total);
    payload.extend_from_slice(MAGIC);
    payload.extend_from_slice(&1u32.to_le_bytes());
    payload.extend_from_slice(&name_bytes.to_le_bytes());
    payload.extend_from_slice(&core_bytes.to_le_bytes());
    payload.extend_from_slice(public.as_bytes());
    payload.extend_from_slice(core);
    Ok(payload)
}

/// Bound the original compiler input before deriving any copied core image.
pub fn check_original_envelope(core: &[u8], public: &str) -> Result<usize, &'static str> {
    public_name(public)?;
    let total = HEADER_BYTES
        .checked_add(public.len())
        .and_then(|n| n.checked_add(core.len()))
        .ok_or("c-preimage-length-overflow")?;
    if total > MAX_C_PREIMAGE_BYTES || core.get(..8) != Some(b"\0asm\x01\0\0\0") {
        return Err("c-preimage-original-core-bound");
    }
    Ok(total)
}

fn top_level_payload(input: &[u8]) -> Result<Option<&[u8]>, &'static str> {
    if input.len() > MAX_BYTES {
        return Err("c-preimage-component-bound");
    }
    if input.get(..8) != Some(b"\0asm\r\0\x01\0") {
        return Err("c-preimage-component-required");
    }
    finite_component_leaves(input)?;
    let mut depth = 0u32;
    let mut found = None;
    for (index, payload) in Parser::new(0).parse_all(input).enumerate() {
        if index >= 65536 {
            return Err("c-preimage-parser-work-bound");
        }
        let payload = payload.map_err(|_| "c-preimage-component-parse")?;
        if index == 0
            && !matches!(
                payload,
                Payload::Version {
                    encoding: Encoding::Component,
                    ..
                }
            )
        {
            return Err("c-preimage-component-required");
        }
        match payload {
            Payload::ModuleSection { .. } | Payload::ComponentSection { .. } => {
                depth = depth.checked_add(1).ok_or("c-preimage-depth-overflow")?;
                if depth > 16 {
                    return Err("c-preimage-component-depth");
                }
            }
            Payload::End(_) if depth != 0 => depth -= 1,
            Payload::CustomSection(section)
                if depth == 0 && section.name() == C_PREIMAGE_SECTION =>
            {
                if found.is_some() {
                    return Err("c-preimage-duplicate-top-level");
                }
                decode(section.data())?;
                found = Some(section.data());
            }
            _ => {}
        }
    }
    Ok(found)
}

/// The compiler attaches full proof data only after verifying the ordinary
/// encoded component. This does not select a host profile or create a child.
pub fn attach_c_original_core(
    original: &[u8],
    component: &[u8],
    public: &str,
) -> Result<Vec<u8>, &'static str> {
    if top_level_payload(component)?.is_some() {
        return Err("c-preimage-already-present");
    }
    let payload = encode(original, public)?;
    let capacity = component
        .len()
        .checked_add(C_PREIMAGE_SECTION.len() + 16)
        .and_then(|n| n.checked_add(payload.len()))
        .filter(|n| *n <= MAX_BYTES)
        .ok_or("c-preimage-component-bound")?;
    verify_c_component_routing(original, component, public)?;
    let mut output = Vec::with_capacity(capacity);
    output.extend_from_slice(component);
    let section = CustomSection {
        name: Cow::Borrowed(C_PREIMAGE_SECTION),
        data: Cow::Borrowed(&payload),
    };
    output.push(Section::id(&section));
    section.encode(&mut output);
    // The normal graph, all source derivations and the complete final digest
    // must also agree with the exact component that will be packaged.
    verify_embedded_c_original_core(&output)?;
    Ok(output)
}

/// An operator-selected C profile calls this before compilation, native loading
/// and instantiation. Missing/forged proof fails; presence provides no authority.
pub fn verify_embedded_c_original_core(
    component: &[u8],
) -> Result<CComponentRoutingReceipt, &'static str> {
    let payload = top_level_payload(component)?.ok_or("c-preimage-top-level-required")?;
    let original = decode(payload)?;
    finite_preflight(component, original.core)?;
    verify_c_component_routing(original.core, component, original.public)
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_encoder::{ConstExpr, DataSection};

    fn component(payloads: &[&[u8]]) -> Vec<u8> {
        let mut component = wasm_encoder::Component::new();
        for payload in payloads {
            component.section(&CustomSection {
                name: Cow::Borrowed(C_PREIMAGE_SECTION),
                data: Cow::Borrowed(payload),
            });
        }
        component.finish()
    }

    #[test]
    fn c_finite_preflight_refuses_expansive_signatures_locals_and_control_before_validator() {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([ValType::I32; 33], []);
        module.section(&types);
        assert_eq!(
            bounded_core(&module.finish(), true).unwrap_err(),
            "c-preimage-finite-scalar-signature"
        );
        for (locals, depth, expected) in [
            (4097, 0, "c-preimage-finite-local-count"),
            (0, 257, "c-preimage-finite-control-depth"),
        ] {
            let mut module = Module::new();
            let mut types = TypeSection::new();
            types.ty().function([], []);
            module.section(&types);
            let mut functions = FunctionSection::new();
            functions.function(0);
            module.section(&functions);
            let mut code = CodeSection::new();
            let mut function = Function::new([(locals, ValType::I32)]);
            for _ in 0..depth {
                function.instruction(&Instruction::Block(BlockType::Empty));
            }
            for _ in 0..=depth {
                function.instruction(&Instruction::End);
            }
            code.function(&function);
            module.section(&code);
            assert_eq!(bounded_core(&module.finish(), true).unwrap_err(), expected);
        }
        for opcode in [0x1c, 0x1f, 0xe3, 0xe4, 0xe5] {
            let mut module = Module::new();
            let mut types = TypeSection::new();
            types.ty().function([], []);
            module.section(&types);
            let mut functions = FunctionSection::new();
            functions.function(0);
            module.section(&functions);
            let mut code = CodeSection::new();
            let mut function = Function::new([]);
            // The immediate is deliberately truncated. The profile refusal
            // must precede the pinned reader's allocating immediate decoder.
            function.raw([opcode]);
            code.function(&function);
            module.section(&code);
            assert_eq!(
                bounded_core(&module.finish(), true).unwrap_err(),
                "c-preimage-finite-numeric-control-only"
            );
        }
        let mut module = Module::new();
        let mut data = DataSection::new();
        data.active(0, &ConstExpr::raw([0x41, 1, 0x41, 2, 0x6a]), [0]);
        module.section(&data);
        assert_eq!(
            bounded_core(&module.finish(), true).unwrap_err(),
            "c-preimage-finite-offset"
        );
        let mut module = Module::new();
        let mut elements = wasm_encoder::ElementSection::new();
        elements.raw(&[0, 0x41, 1, 0x41, 2, 0x6a, 0x0b, 0]);
        module.section(&elements);
        assert_eq!(
            bounded_core(&module.finish(), true).unwrap_err(),
            "c-preimage-finite-offset"
        );

        // Preserve the original48MiB payer. Test both boundaries independently:
        // many small bodies may use the useful total, never one giant arena.
        assert_eq!(C_VERIFICATION_WORK_BYTES, 48 * 1024 * 1024);
        fn operator_core(counts: &[u64]) -> Vec<u8> {
            let mut module = Module::new();
            let mut types = TypeSection::new();
            types.ty().function([], []);
            module.section(&types);
            let mut functions = FunctionSection::new();
            let mut code = CodeSection::new();
            for &count in counts {
                assert!(count != 0);
                functions.function(0);
                let mut function = Function::new([]);
                for _ in 1..count {
                    function.instruction(&Instruction::Nop);
                }
                function.instruction(&Instruction::End);
                code.function(&function);
            }
            module.section(&functions);
            module.section(&code);
            module.finish()
        }
        assert_eq!(
            bounded_core(&operator_core(&[MAX_FUNCTION_OPERATORS]), true),
            Ok(MAX_FUNCTION_OPERATORS)
        );
        assert_eq!(
            bounded_core(&operator_core(&[MAX_FUNCTION_OPERATORS + 1]), true),
            Err("c-preimage-finite-function-operator-count")
        );
        for (original, total) in [
            (true, MAX_ORIGINAL_OPERATORS),
            (false, MAX_DERIVED_OPERATORS),
        ] {
            let mut counts =
                vec![MAX_FUNCTION_OPERATORS; (total / MAX_FUNCTION_OPERATORS) as usize];
            assert_eq!(bounded_core(&operator_core(&counts), original), Ok(total));
            counts.push(1);
            assert_eq!(
                bounded_core(&operator_core(&counts), original),
                Err("c-preimage-finite-operator-count")
            );
        }
        // Worst allowed scalar call width: no unjustified one-value/op model.
        let mut wide = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32; 32]);
        types.ty().function([], []);
        wide.section(&types);
        let mut imports = wasm_encoder::ImportSection::new();
        imports.import("fixed", "wide", wasm_encoder::EntityType::Function(0));
        wide.section(&imports);
        let mut functions = FunctionSection::new();
        functions.function(1);
        wide.section(&functions);
        let mut code = CodeSection::new();
        let mut function = Function::new([]);
        for _ in 0..MAX_FUNCTION_OPERATORS - 2 {
            function.instruction(&Instruction::Call(0));
        }
        function.instruction(&Instruction::Unreachable);
        function.instruction(&Instruction::End);
        code.function(&function);
        wide.section(&code);
        let wide = wide.finish();
        assert_eq!(bounded_core(&wide, true), Ok(MAX_FUNCTION_OPERATORS));
        // Actual pinned validator allocation path, not execution/instantiation.
        Validator::new().validate_all(&wide).unwrap();
    }

    #[test]
    fn c_finite_type_envelope_accepts_original_generator_tags_and_refuses_declared_allocation_counts()
     {
        // Exact type-section payloads from authenticated ordinary889 component
        // f040342f89261b8afe5de18668c5c479ef599907a5203f85945d147b383acff2.
        // This is historical generator-shape data, not the unretained C9a5 core.
        for encoded in [
            "01420f016d08047461736b136d616e616765642d69646c652d776f726b6572086578656375746f720b7175657565642d776f726b04776169740574696d657206726573756c74066e617469766504000a6f776e65722d6b696e640300000172020a67656e65726174696f6e7702696477040005746f6b656e030002016d070b756e617661696c61626c65117065726d697373696f6e2d64656e696564127265736f757263652d6578686175737465640963616e63656c6c656408646561646c696e650d696e76616c69642d73746174650d696e76616c69642d746f6b656e0400056572726f72030004016b03016a01030105014002046b696e64010c636f6e74696e756174696f6e06000704000872656769737465720108016a000105014001056f776e65720300090400047061726b010a04000477616b65010a040006736574746c65010a",
            "0142070203020101040005746f6b656e03000002030201020400056572726f72030002016a0001030140010c636f6e74696e756174696f6e01000404000573746172740105",
            "0160017f00",
            "026a017301734001046e616d65730004",
            "026a017301734001046e616d65730000",
            "026a017301734001046e616d65730002",
        ] {
            let bytes: Vec<u8> = encoded
                .as_bytes()
                .chunks_exact(2)
                .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
                .collect();
            finite_type_encoding(&bytes).unwrap();
        }
        // Primitive signed valtype tags and an unsigned256 remain intact.
        finite_type_encoding(&[0x7f, 0x7e, 0x7d, 0x7c, 0x80, 0x02]).unwrap();
        for bytes in [
            vec![0x81, 0x02],
            vec![0x80],
            vec![0x80; 6],
            vec![0x01, 0x42, 0xc0, 0x84, 0x3d], // one instance, forged1,000,000 decls
            vec![0x01, 0x40, 0xc0, 0x84, 0x3d], // forged function parameter count
            vec![0xc3, 0xa9, 0x00],
        ] {
            // unsupported wider UTF8 envelope
            assert_eq!(
                finite_type_encoding(&bytes).unwrap_err(),
                "c-preimage-finite-type-integer-envelope"
            );
        }
    }

    #[test]
    fn c_finite_component_preflight_accepts_one_generator_child_and_refuses_siblings_or_deeper_children()
     {
        let original = c_root::tests::fixture(69632, false, false);
        let child = wasm_encoder::Component::new();
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::NestedComponentSection(&child));
        finite_preflight(&outer.clone().finish(), &original).unwrap();
        outer.section(&wasm_encoder::NestedComponentSection(&child));
        assert_eq!(
            finite_preflight(&outer.finish(), &original).unwrap_err(),
            "c-preimage-finite-nested-component-count"
        );
        let mut middle = wasm_encoder::Component::new();
        middle.section(&wasm_encoder::NestedComponentSection(&child));
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::NestedComponentSection(&middle));
        assert_eq!(
            finite_preflight(&outer.finish(), &original).unwrap_err(),
            "c-preimage-finite-nested-component-count"
        );
    }

    #[test]
    fn c_finite_component_preflight_counts_nested_aliases_and_type_storage_before_typed_readers() {
        let original = c_root::tests::fixture(69632, false, false);
        let mut aliases = Vec::new();
        256u32.encode(&mut aliases);
        let mut child = wasm_encoder::Component::new();
        child.section(&wasm_encoder::RawSection {
            id: 6,
            data: &aliases,
        });
        child.section(&wasm_encoder::RawSection { id: 6, data: &[1] });
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::RawSection {
            id: 6,
            data: &aliases,
        });
        outer.section(&wasm_encoder::NestedComponentSection(&child));
        assert_eq!(
            finite_preflight(&outer.finish(), &original).unwrap_err(),
            "c-preimage-finite-component-container-bound"
        );
        let first = vec![0; 8192];
        let second = vec![0; 8193];
        let mut child = wasm_encoder::Component::new();
        child.section(&wasm_encoder::RawSection {
            id: 7,
            data: &second,
        });
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::RawSection {
            id: 7,
            data: &first,
        });
        outer.section(&wasm_encoder::NestedComponentSection(&child));
        assert_eq!(
            finite_preflight(&outer.finish(), &original).unwrap_err(),
            "c-preimage-finite-type-encoding-bytes"
        );
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::RawSection {
            id: 7,
            data: &[1, 0x42, 0xc0, 0x84, 0x3d],
        });
        assert_eq!(
            finite_preflight(&outer.finish(), &original).unwrap_err(),
            "c-preimage-finite-type-integer-envelope"
        );
    }

    #[test]
    fn c_finite_structural_leaves_refuse_declared_vectors_before_typed_or_eager_readers() {
        // Each forged vector count fits its pinned wasmparser limit but exceeds
        // this profile's allocation envelope. No vector element need exist.
        for (id, prefix, count) in [
            (2, vec![1, 0, 0], 100_000u32), // Core instantiate arguments.
            (2, vec![1, 1], 100_000),       // Core instance exports.
            (5, vec![1, 0, 0], 100_000),    // Component instantiate arguments.
            (5, vec![1, 1], 100_000),       // Component instance exports.
            (9, vec![0], 1000),             // Eager component-start arguments.
        ] {
            let mut payload = prefix;
            count.encode(&mut payload);
            let mut component = wasm_encoder::Component::new();
            component.section(&wasm_encoder::RawSection { id, data: &payload });
            let bytes = component.finish();
            assert_eq!(
                finite_component_leaves(&bytes).unwrap_err(),
                "c-preimage-finite-structural-integer-envelope"
            );
            // Proof discovery itself must refuse before Parser can construct
            // the eager start's arguments, even without a proof section.
            assert_eq!(
                top_level_payload(&bytes).unwrap_err(),
                "c-preimage-finite-structural-integer-envelope"
            );
        }
        let mut payload = vec![0];
        1000u32.encode(&mut payload);
        let mut child = wasm_encoder::Component::new();
        child.section(&wasm_encoder::RawSection {
            id: 9,
            data: &payload,
        });
        let mut parent = wasm_encoder::Component::new();
        parent.section(&wasm_encoder::NestedComponentSection(&child));
        assert_eq!(
            finite_component_leaves(&parent.finish()).unwrap_err(),
            "c-preimage-finite-structural-integer-envelope"
        );
    }

    #[test]
    fn c_finite_leaf_framing_excludes_core_and_custom_bytes_but_refuses_bad_structural_frames() {
        let opaque = [0xff; 16];
        let mut component = wasm_encoder::Component::new();
        for id in [0, 1] {
            component.section(&wasm_encoder::RawSection { id, data: &opaque });
        }
        // Only the framing pass excludes these payloads. Full core/custom
        // parsing and graph validation remain mandatory afterward.
        finite_component_leaves(&component.finish()).unwrap();
        for tail in [vec![12, 0], vec![5, 4, 1], vec![2, 0x80]] {
            let mut bytes = wasm_encoder::Component::new().finish();
            bytes.extend_from_slice(&tail);
            assert_eq!(
                finite_component_leaves(&bytes).unwrap_err(),
                "c-preimage-finite-component-framing"
            );
        }
        let mut component = wasm_encoder::Component::new();
        component.section(&wasm_encoder::RawSection {
            id: 5,
            data: &[0; 64 * 1024 + 1],
        });
        assert_eq!(
            finite_component_leaves(&component.finish()).unwrap_err(),
            "c-preimage-finite-component-structure-bytes"
        );
    }

    #[test]
    fn c_proof_payload_roundtrips_original_bytes_but_never_grants_routing() {
        let core = Module::new().finish();
        let payload = encode(&core, "examples:threading/api@1.0.0#greet").unwrap();
        let decoded = decode(&payload).unwrap();
        assert_eq!(decoded.core, core);
        assert_eq!(decoded.public, "examples:threading/api@1.0.0#greet");
        let supplied = component(&[&payload]);
        assert_eq!(
            top_level_payload(&supplied).unwrap(),
            Some(payload.as_slice())
        );
        assert!(verify_embedded_c_original_core(&supplied).is_err());
        assert!(attach_c_original_core(&core, &component(&[]), decoded.public).is_err());
    }

    #[test]
    fn c_proof_payload_refuses_version_lengths_trailing_bytes_and_invalid_names() {
        let core = Module::new().finish();
        let original = encode(&core, "run").unwrap();
        for (index, value) in [(0, 0), (8, 2), (12, 0), (16, 0), (HEADER_BYTES, 0xff)] {
            let mut changed = original.clone();
            changed[index] = value;
            assert!(decode(&changed).is_err());
        }
        let mut trailing = original.clone();
        trailing.push(0);
        assert!(decode(&trailing).is_err());
        assert!(encode(&core, "").is_err());
        assert!(encode(&core, "run\n").is_err());
        assert!(encode(&core, &"x".repeat(MAX_PUBLIC_BYTES + 1)).is_err());
        assert!(encode(b"\0asm\r\0\x01\0", "run").is_err());
    }

    #[test]
    fn c_proof_payload_is_bounded_before_copy_and_rejects_duplicate_top_level_data() {
        assert!(decode(&vec![0; MAX_C_PREIMAGE_BYTES + 1]).is_err());
        let mut core = vec![0; MAX_C_PREIMAGE_BYTES];
        core[..8].copy_from_slice(b"\0asm\x01\0\0\0");
        assert!(encode(&core, "run").is_err());
        let payload = encode(&Module::new().finish(), "run").unwrap();
        assert_eq!(
            top_level_payload(&component(&[&payload, &payload])).unwrap_err(),
            "c-preimage-duplicate-top-level"
        );
        assert_eq!(
            top_level_payload(&vec![0; MAX_BYTES + 1]).unwrap_err(),
            "c-preimage-component-bound"
        );
        assert!(top_level_payload(&Module::new().finish()).is_err());
    }

    #[test]
    fn c_proof_nested_core_or_component_metadata_is_never_selected() {
        let payload = encode(&Module::new().finish(), "run").unwrap();
        let mut module = Module::new();
        module.section(&CustomSection {
            name: Cow::Borrowed(C_PREIMAGE_SECTION),
            data: Cow::Borrowed(&payload),
        });
        let mut child = wasm_encoder::Component::new();
        child.section(&CustomSection {
            name: Cow::Borrowed(C_PREIMAGE_SECTION),
            data: Cow::Borrowed(&payload),
        });
        let mut outer = wasm_encoder::Component::new();
        outer.section(&wasm_encoder::ModuleSection(&module));
        outer.section(&wasm_encoder::NestedComponentSection(&child));
        let bytes = outer.finish();
        assert!(top_level_payload(&bytes).unwrap().is_none());
        assert_eq!(
            verify_embedded_c_original_core(&bytes).unwrap_err(),
            "c-preimage-top-level-required"
        );
    }
}
