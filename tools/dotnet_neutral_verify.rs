//! Frozen diagnostic comparison; no component instantiation or runtime profile.
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    io::{Read, Write},
};
use wasmparser::{
    BinaryReader, FunctionBody, Operator, Parser, Payload, ValType, Validator, WasmFeatures,
};

const ORIGINAL: &str = "3ab0ae8b54c5ed0469b3f9ea105fd566f308e314bdf3aeeb4529b9ed4085f20a";
const DERIVED: &str = "f48d42c7c966aa6e87bd2e01f5a90379d2c7b5e6e2e84de26e4581b4391d3f80";
const OLD_CORE: &str = "d3e8dab0c62188465bcdbab9a6a0a3845887190dd44affd48e54acfe6db5bff6";
const NEW_CORE: &str = "6d5c4b64685e15f063cd01ca0cedb470827d1fbd214e267f5887dcc51bd8ebff";
const COMPONENT: &[u8] = b"\0asm\x0d\0\x01\0";
const CORE: &[u8] = b"\0asm\x01\0\0\0";
const GET: &[u8] = &[0, 0x23, 0x80, 0x80, 0x80, 0x80, 0, 0x0b];
const SET: &[u8] = &[0, 0x20, 0, 0x24, 0x80, 0x80, 0x80, 0x80, 0, 0x0b];
const GET_OLD: &[u8] = &[0x23, 0x80, 0x80, 0x80, 0x80, 0];
const SET_OLD: &[u8] = &[0x24, 0x80, 0x80, 0x80, 0x80, 0];
const GET_CALL: &[u8] = &[0x10, 0xdf, 0xd3, 0x80, 0x80, 0];
const SET_CALL: &[u8] = &[0x10, 0xe0, 0xd3, 0x80, 0x80, 0];
type R<T> = Result<T, &'static str>;

fn digest(data: &[u8]) -> String {
    Sha256::digest(data)
        .iter()
        .map(|x| format!("{x:02x}"))
        .collect()
}
struct Cursor<'a> {
    data: &'a [u8],
    at: usize,
}
impl<'a> Cursor<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self { data, at: 0 }
    }
    fn byte(&mut self) -> R<u8> {
        let b = *self.data.get(self.at).ok_or("truncated")?;
        self.at += 1;
        Ok(b)
    }
    fn u32(&mut self) -> R<u32> {
        let mut value = 0u32;
        for index in 0..5 {
            let b = self.byte()?;
            if index == 4 && b & 0xf0 != 0 {
                return Err("uleb-overflow");
            }
            value |= u32::from(b & 0x7f) << (index * 7);
            if b & 0x80 == 0 {
                if index > 0 && b == 0 {
                    return Err("uleb-noncanonical");
                }
                return Ok(value);
            }
        }
        Err("uleb-overflow")
    }
    fn take(&mut self, n: usize) -> R<&'a [u8]> {
        let end = self.at.checked_add(n).ok_or("length-overflow")?;
        let value = self.data.get(self.at..end).ok_or("truncated")?;
        self.at = end;
        Ok(value)
    }
    fn done(&self) -> bool {
        self.at == self.data.len()
    }
}
#[derive(Default)]
struct Stats {
    containers: usize,
    sections: usize,
    cores: usize,
    target: usize,
    functions: usize,
    ops: usize,
    gets: usize,
    sets: usize,
}

fn sections<'a>(input: &'a [u8], header: &[u8]) -> R<Vec<(u8, &'a [u8])>> {
    if !input.starts_with(header) {
        return Err("header");
    }
    let mut cursor = Cursor::new(&input[header.len()..]);
    let mut result = Vec::new();
    while !cursor.done() {
        if result.len() >= 1100 {
            return Err("section-bound");
        }
        let kind = cursor.byte()?;
        let len = cursor.u32()? as usize;
        result.push((kind, cursor.take(len)?));
    }
    Ok(result)
}
fn compare_components(old: &[u8], new: &[u8], depth: usize, stats: &mut Stats) -> R<()> {
    if depth > 3 || stats.containers >= 32 {
        return Err("component-bound");
    }
    stats.containers += 1;
    let left = sections(old, COMPONENT)?;
    let right = sections(new, COMPONENT)?;
    stats.sections = stats
        .sections
        .checked_add(left.len())
        .ok_or("section-overflow")?;
    if stats.sections > 1100 || left.len() != right.len() {
        return Err("component-sections");
    }
    for ((kind, a), (other, b)) in left.into_iter().zip(right) {
        if kind != other {
            return Err("component-section-kind");
        }
        match kind {
            1 => {
                stats.cores += 1;
                if stats.cores > 12 {
                    return Err("core-bound");
                }
                if digest(a) == OLD_CORE {
                    if digest(b) != NEW_CORE || stats.target != 0 {
                        return Err("selected-core");
                    }
                    stats.target += 1;
                    compare_cores(a, b, stats)?;
                } else if a != b {
                    return Err("other-core-changed");
                }
            }
            4 => compare_components(a, b, depth + 1, stats)?,
            _ if a != b => return Err("component-section-changed"),
            _ => {}
        }
    }
    Ok(())
}
fn compare_function_types(a: &[u8], b: &[u8]) -> R<()> {
    let mut old = Cursor::new(a);
    let mut new = Cursor::new(b);
    if old.u32()? != 10670 || new.u32()? != 10672 {
        return Err("function-count");
    }
    let x = &a[old.at..];
    let y = &b[new.at..];
    if y.len() != x.len() + 2 || !y.starts_with(x) || &y[x.len()..] != [9, 0] {
        return Err("function-types");
    }
    Ok(())
}
fn code_body<'a>(cursor: &mut Cursor<'a>) -> R<&'a [u8]> {
    let size = cursor.u32()? as usize;
    if size > 32768 {
        return Err("body-bound");
    }
    cursor.take(size)
}
fn compare_body(a: &[u8], b: &[u8], stats: &mut Stats) -> R<()> {
    if a.len() != b.len() {
        return Err("body-length");
    }
    let first = FunctionBody::new(BinaryReader::new(a, 0));
    let second = FunctionBody::new(BinaryReader::new(b, 0));
    let mut left = first
        .get_operators_reader()
        .map_err(|_| "original-locals")?;
    let mut right = second
        .get_operators_reader()
        .map_err(|_| "derived-locals")?;
    let mut last = usize::try_from(left.original_position()).map_err(|_| "offset")?;
    if last != usize::try_from(right.original_position()).map_err(|_| "offset")?
        || a.get(..last) != b.get(..last)
    {
        return Err("locals-changed");
    }
    while !left.eof() {
        if right.eof() || stats.ops >= 1250000 {
            return Err("instruction-bound");
        }
        let original = left.read().map_err(|_| "original-operator")?;
        let changed = right.read().map_err(|_| "derived-operator")?;
        let end = usize::try_from(left.original_position()).map_err(|_| "offset")?;
        if end != usize::try_from(right.original_position()).map_err(|_| "offset")? {
            return Err("operator-size");
        }
        let x = a.get(last..end).ok_or("operator-range")?;
        let y = b.get(last..end).ok_or("operator-range")?;
        match original {
            Operator::GlobalGet { global_index: 0 } => {
                if x != GET_OLD
                    || y != GET_CALL
                    || !matches!(
                        changed,
                        Operator::Call {
                            function_index: 10719
                        }
                    )
                {
                    return Err("stack-get");
                }
                stats.gets += 1;
            }
            Operator::GlobalSet { global_index: 0 } => {
                if x != SET_OLD
                    || y != SET_CALL
                    || !matches!(
                        changed,
                        Operator::Call {
                            function_index: 10720
                        }
                    )
                {
                    return Err("stack-set");
                }
                stats.sets += 1;
            }
            Operator::Call { function_index }
            | Operator::ReturnCall { function_index }
            | Operator::RefFunc { function_index }
                if function_index >= 10719 =>
            {
                return Err("future-reference");
            }
            _ if x != y => return Err("other-operator-changed"),
            _ => {}
        }
        last = end;
        stats.ops += 1;
    }
    if !right.eof() || last != a.len() {
        return Err("operator-tail");
    }
    Ok(())
}
fn compare_code(a: &[u8], b: &[u8], stats: &mut Stats) -> R<()> {
    let mut old = Cursor::new(a);
    let mut new = Cursor::new(b);
    if old.u32()? != 10670 || new.u32()? != 10672 {
        return Err("code-count");
    }
    for _ in 0..10670 {
        if stats.functions >= 12000 {
            return Err("function-bound");
        }
        compare_body(code_body(&mut old)?, code_body(&mut new)?, stats)?;
        stats.functions += 1;
    }
    if !old.done() || code_body(&mut new)? != GET || code_body(&mut new)? != SET || !new.done() {
        return Err("helper-body");
    }
    Ok(())
}
fn inspect_imports(data: &[u8]) -> R<()> {
    let mut c = Cursor::new(data);
    if c.u32()? != 49 {
        return Err("import-count");
    }
    for _ in 0..49 {
        let n = c.u32()? as usize;
        c.take(n)?;
        let n = c.u32()? as usize;
        c.take(n)?;
        if c.byte()? != 0 {
            return Err("nonfunction-import");
        }
        c.u32()?;
    }
    if !c.done() {
        return Err("import-tail");
    }
    Ok(())
}
fn inspect_original(core: &[u8]) -> R<()> {
    let mut types = false;
    let mut globals = false;
    for payload in Parser::new(0).parse_all(core) {
        match payload.map_err(|_| "core-parse")? {
            Payload::TypeSection(reader) => {
                for (index, ty) in reader.into_iter_err_on_gc_types().enumerate() {
                    let ty = ty.map_err(|_| "core-type")?;
                    if index == 0 && (ty.params() != [ValType::I32] || !ty.results().is_empty()) {
                        return Err("setter-type");
                    }
                    if index == 9 {
                        if !ty.params().is_empty() || ty.results() != [ValType::I32] {
                            return Err("getter-type");
                        }
                        types = true;
                    }
                }
            }
            Payload::GlobalSection(reader) => {
                if reader.count() != 15 {
                    return Err("global-count");
                }
                let global = reader
                    .into_iter()
                    .next()
                    .ok_or("global-missing")?
                    .map_err(|_| "global")?;
                if global.ty.content_type != ValType::I32 || !global.ty.mutable || global.ty.shared
                {
                    return Err("global-type");
                }
                let mut ops = global.init_expr.get_operators_reader();
                if !matches!(ops.read(), Ok(Operator::I32Const { value: 2326704 }))
                    || !matches!(ops.read(), Ok(Operator::End))
                    || !ops.eof()
                {
                    return Err("global-initializer");
                }
                globals = true;
            }
            _ => {}
        }
    }
    if !types || !globals {
        return Err("core-structure-missing");
    }
    Ok(())
}
fn compare_cores(a: &[u8], b: &[u8], stats: &mut Stats) -> R<()> {
    if a.len() != 7293062 || b.len() != 7293084 {
        return Err("core-size");
    }
    inspect_original(a)?;
    let old = sections(a, CORE)?;
    let new = sections(b, CORE)?;
    if old.len() != new.len() {
        return Err("core-sections");
    }
    let (mut imports, mut functions, mut code) = (false, false, false);
    for ((kind, x), (other, y)) in old.into_iter().zip(new) {
        if kind != other {
            return Err("core-section-kind");
        }
        match kind {
            2 if !imports => {
                if x != y {
                    return Err("imports-changed");
                }
                inspect_imports(x)?;
                imports = true;
            }
            3 if !functions => {
                compare_function_types(x, y)?;
                functions = true;
            }
            10 if !code => {
                compare_code(x, y, stats)?;
                code = true;
            }
            2 | 3 | 10 => return Err("duplicate-core-section"),
            _ if x != y => return Err("core-section-changed"),
            _ => {}
        }
    }
    if !imports || !functions || !code {
        return Err("core-section-missing");
    }
    Ok(())
}
fn verify(old: &[u8], new: &[u8]) -> R<()> {
    if old.len() != 7542795
        || new.len() != 7542817
        || digest(old) != ORIGINAL
        || digest(new) != DERIVED
    {
        return Err("fixed-component-identity");
    }
    let mut stats = Stats::default();
    compare_components(old, new, 0, &mut stats)?;
    if (
        stats.containers,
        stats.sections,
        stats.cores,
        stats.target,
        stats.functions,
        stats.ops,
        stats.gets,
        stats.sets,
    ) != (31, 1053, 11, 1, 10670, 1159801, 1131, 2412)
    {
        return Err("observed-counts");
    }
    Validator::new_with_features(WasmFeatures::all())
        .validate_all(old)
        .map_err(|_| "original-validation")?;
    Validator::new_with_features(WasmFeatures::all())
        .validate_all(new)
        .map_err(|_| "derived-validation")?;
    Ok(())
}
fn read(path: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut raw = Vec::new();
    fs::File::open(path)?
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut raw)?;
    if raw.len() > 8 * 1024 * 1024 {
        return Err("input-size".into());
    }
    Ok(raw)
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        return Err("usage: dotnet-neutral-verify ORIGINAL DERIVED RECEIPT".into());
    }
    let original = read(&args[1])?;
    let derived = read(&args[2])?;
    verify(&original, &derived)?;
    let receipt = concat!(
        "{\"schemaVersion\":\"latent.dotnet.neutral-stack-verifier.v1\",",
        "\"original\":\"sha256:3ab0ae8b54c5ed0469b3f9ea105fd566f308e314bdf3aeeb4529b9ed4085f20a\",",
        "\"derived\":\"sha256:f48d42c7c966aa6e87bd2e01f5a90379d2c7b5e6e2e84de26e4581b4391d3f80\",",
        "\"globalGets\":1131,\"globalSets\":2412,\"permissiveValidatorPassed\":true,",
        "\"exactEngineProfileQualified\":false,\"guestExecution\":false,\"productionProfile\":false}\n"
    );
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[3])?
        .write_all(receipt.as_bytes())?;
    println!("frozen sample comparison and permissive validation passed; no guest executed");
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("neutral diagnostic failed: {error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn matching_get_and_set_must_use_exact_helpers() {
        let old = [&[0][..], GET_OLD, SET_OLD, &[0x0b]].concat();
        let new = [&[0][..], GET_CALL, SET_CALL, &[0x0b]].concat();
        let mut stats = Stats::default();
        assert!(compare_body(&old, &new, &mut stats).is_ok());
        assert_eq!((stats.gets, stats.sets), (1, 1));
        let mut wrong = new.clone();
        wrong[2] = 0xe0;
        assert!(compare_body(&old, &wrong, &mut Stats::default()).is_err());
        assert!(compare_body(&old, &new[..new.len() - 1], &mut Stats::default()).is_err());
    }
    fn uleb(mut n: u32) -> Vec<u8> {
        let mut out = Vec::new();
        loop {
            let b = (n & 0x7f) as u8;
            n >>= 7;
            out.push(if n == 0 { b } else { b | 0x80 });
            if n == 0 {
                return out;
            }
        }
    }

    #[test]
    fn missing_changed_or_extra_helpers_fail_closed() {
        let mut old = uleb(10670);
        for _ in 0..10670 {
            old.extend_from_slice(&[2, 0, 0x0b]);
        }
        let mut new = uleb(10672);
        new.extend_from_slice(&old[uleb(10670).len()..]);
        new.push(GET.len() as u8);
        new.extend_from_slice(GET);
        new.push(SET.len() as u8);
        new.extend_from_slice(SET);
        assert!(compare_code(&old, &new, &mut Stats::default()).is_ok());
        let mut wrong = new.clone();
        let last = wrong.len() - 2;
        wrong[last] ^= 1;
        assert!(compare_code(&old, &wrong, &mut Stats::default()).is_err());
        assert!(compare_code(&old, &new[..new.len() - 1], &mut Stats::default()).is_err());
        let mut extra = new.clone();
        extra.push(0);
        assert!(compare_code(&old, &extra, &mut Stats::default()).is_err());
    }

    #[test]
    fn type_and_other_core_changes_are_refused() {
        let mut original = uleb(10670);
        original.extend(vec![0; 10670]);
        let mut changed = uleb(10672);
        changed.extend_from_slice(&original[uleb(10670).len()..]);
        changed.extend_from_slice(&[9, 0]);
        assert!(compare_function_types(&original, &changed).is_ok());
        *changed.last_mut().unwrap() = 1;
        assert!(compare_function_types(&original, &changed).is_err());
        let mut a = COMPONENT.to_vec();
        a.extend_from_slice(&[1, 2, 7, 8]);
        let mut b = a.clone();
        *b.last_mut().unwrap() = 9;
        assert!(compare_components(&a, &b, 0, &mut Stats::default()).is_err());
        b.push(0);
        assert!(compare_components(&a, &b, 0, &mut Stats::default()).is_err());
    }

    #[test]
    fn decoder_refuses_noncanonical_or_overlong_sections() {
        assert!(Cursor::new(&[0x80, 0]).u32().is_err());
        assert!(Cursor::new(&[0xff, 0xff, 0xff, 0xff, 0x10]).u32().is_err());
        assert!(sections(b"\0asm\x0d\0\x01\0\x01\x02\x00", COMPONENT).is_err());
        assert!(verify(b"wrong", b"wrong").is_err());
    }
}
