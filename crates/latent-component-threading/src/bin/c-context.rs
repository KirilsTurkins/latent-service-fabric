//! Explicit C compiler mechanism utility; never enables an engine profile.
use latent_component_threading::{
    MAX_BYTES, c_abi::transform_c_canonical_abi, c_context::transform_c_context,
    verify_c_component_routing,
};
use std::{
    fs,
    io::{Read, Write},
    path::Path,
};
fn hex(raw: &[u8; 32]) -> String {
    raw.iter().map(|x| format!("{x:02x}")).collect()
}
fn read(path: &str) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut raw = Vec::new();
    fs::File::open(path)?
        .take((MAX_BYTES + 1) as u64)
        .read_to_end(&mut raw)?;
    if raw.len() > MAX_BYTES {
        return Err("input-byte-bound".into());
    }
    Ok(raw)
}
fn canonical(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let input = read(&args[1])?;
    let output = Path::new(&args[4]);
    if args[0] == "--verify-canonical-component" {
        let component = read(&args[2])?;
        let receipt = verify_c_component_routing(&input, &component, &args[3])?;
        let json = format!(
            concat!(
                "{{\n  \"schemaVersion\":\"latent.c.canonical-component-source.v1\",\n",
                "  \"originalDigest\":\"sha256:{}\",\n  \"componentDigest\":\"sha256:{}\",\n",
                "  \"mainCoreDigest\":\"sha256:{}\",\n  \"mainModule\":{},\n  \"initializeModule\":{},\n",
                "  \"rawCreationSlot\":{},\n  \"nativeAdmissionSlot\":{},\n",
                "  \"actualComponentGraphAuthenticated\":true,\n  \"canonicalCreationEnabled\":false,\n",
                "  \"standardRuntimeQualified\":false\n}}\n"
            ),
            hex(&receipt.original_core_digest),
            hex(&receipt.component_digest),
            hex(&receipt.main_core_digest),
            receipt.main_module,
            receipt.initialize_module,
            receipt.raw_creation_slot,
            receipt.native_admission_slot
        );
        fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(output)?
            .write_all(json.as_bytes())?;
    } else {
        let expected = preimage(&args[2])?;
        let (derived, receipt) = transform_c_canonical_abi(&input, expected, &args[3])?;
        fs::create_dir(output)?;
        fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(output.join("core.wasm"))?
            .write_all(&derived)?;
        let json = format!(
            concat!(
                "{{\n  \"schemaVersion\":\"latent.c.canonical-abi-source.v1\",\n",
                "  \"originalDigest\":\"sha256:{}\",\n  \"derivedDigest\":\"sha256:{}\",\n",
                "  \"initializeWrapper\":{},\n  \"reallocWrapper\":{},\n  \"postReturnWrapper\":{},\n",
                "  \"systemClosureFunctions\":{},\n  \"systemScopeReadsTls\":{},\n",
                "  \"canonicalComponentAuthenticated\":false,\n  \"runtimeProfileQualified\":false\n}}\n"
            ),
            hex(&receipt.original_digest),
            hex(&receipt.derived_digest),
            receipt.initialize_wrapper,
            receipt.realloc_wrapper,
            receipt.post_return_wrapper,
            receipt.system_closure_functions,
            receipt.system_scope_reads_tls
        );
        fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(output.join("receipt.json"))?
            .write_all(json.as_bytes())?;
    }
    Ok(())
}
fn preimage(value: &str) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    let digest = value.strip_prefix("sha256:").ok_or("preimage-format")?;
    if digest.len() != 64
        || !digest
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("preimage-format".into());
    }
    let mut expected = [0; 32];
    for (i, slot) in expected.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&digest[i * 2..i * 2 + 2], 16)?;
    }
    Ok(expected)
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).take(6).collect();
    if args.len() == 5
        && ["--canonical-abi", "--verify-canonical-component"].contains(&args[0].as_str())
    {
        return canonical(&args);
    }
    if args.len() != 3 {
        return Err("usage: c-context INPUT sha256:DIGEST FRESH_OUTPUT".into());
    }
    let expected = preimage(&args[1])?;
    let raw = read(&args[0])?;
    let (derived, receipt) = transform_c_context(&raw, expected)?;
    let output = Path::new(&args[2]);
    fs::create_dir(output)?;
    fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(output.join("core.wasm"))?
        .write_all(&derived)?;
    let json = format!(
        concat!(
            "{{\n  \"schemaVersion\":\"latent.c.context-source-mechanism.v1\",\n",
            "  \"originalDigest\":\"sha256:{}\",\n  \"derivedDigest\":\"sha256:{}\",\n",
            "  \"templateStart\":{},\n  \"templateExtentUpperBound\":{},\n",
            "  \"stackGets\":{},\n  \"stackSets\":{},\n  \"tlsGets\":{},\n",
            "  \"runtimeProfileQualified\":false,\n  \"bootstrapInstalled\":false,\n",
            "  \"schedulingCheckpointsInstalled\":false\n}}\n"
        ),
        hex(&receipt.original_digest),
        hex(&receipt.derived_digest),
        receipt.template_start,
        receipt.template_extent,
        receipt.stack_gets,
        receipt.stack_sets,
        receipt.tls_gets
    );
    fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(output.join("receipt.json"))?
        .write_all(json.as_bytes())?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("C context source mechanism refused: {error}");
        std::process::exit(1);
    }
}
