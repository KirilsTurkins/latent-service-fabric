//! Explicit owned Rust compiler mechanism; no runtime feature is enabled here.
use latent_component_threading::{
    MAX_BYTES, prepare_owned_public_root, transform_owned_canonical_root_bootstrap,
    transform_owned_root_bootstrap, transform_owned_thread_admission, transform_owned_thread_entry,
    verify_component_routing,
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
fn write(path: &Path, raw: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)?
        .write_all(raw)?;
    Ok(())
}
fn ordinary(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    if args.len() != 7 {
        return Err("usage: rust-context --ordinary-core INPUT sha256:DIGEST PUBLIC_EXPORT POST_RETURN_OR_DASH REALLOC_OR_DASH FRESH_OUTPUT".into());
    }
    let expected = preimage(&args[2])?;
    let raw = read(&args[1])?;
    let (prepared, public) = prepare_owned_public_root(&raw, expected, &args[3])?;
    let (threaded, thread) = transform_owned_thread_entry(&prepared, public.derived_digest)?;
    let (rooted, root) = transform_owned_canonical_root_bootstrap(
        &threaded,
        thread.stack.derived_digest,
        &thread,
        (args[4] != "-").then_some(args[4].as_str()),
        (args[5] != "-").then_some(args[5].as_str()),
    )?;
    let (derived, admission) = transform_owned_thread_admission(&rooted, root.derived_digest)?;
    let number = |value: Option<u32>| value.map_or_else(|| "null".to_owned(), |v| v.to_string());
    let json = format!(
        concat!(
            "{{\n  \"schemaVersion\":\"latent.rust.ordinary-core-source.v1\",\n",
            "  \"originalDigest\":\"sha256:{}\",\n  \"preparedDigest\":\"sha256:{}\",\n",
            "  \"threadDigest\":\"sha256:{}\",\n  \"rootDigest\":\"sha256:{}\",\n",
            "  \"derivedDigest\":\"sha256:{}\",\n  \"publicFunction\":{},\n",
            "  \"nativeAdmissionImportInserted\":{},\n  \"nativeAdmissionImport\":{},\n",
            "  \"postReturnFunction\":{},\n  \"originalPostReturnBody\":{},\n",
            "  \"reallocFunction\":{},\n  \"originalReallocBody\":{},\n",
            "  \"rootStackLow\":{},\n  \"rootStackHigh\":{},\n",
            "  \"canonicalSystemStackLow\":{},\n  \"canonicalSystemStackHigh\":{},\n",
            "  \"canonicalSystemScopeGlobal\":{},\n  \"canonicalSystemClosureFunctions\":{},\n",
            "  \"canonicalResultAreaAuthenticated\":false,\n",
            "  \"privateExecutorGraphAuthenticated\":false,\n",
            "  \"canonicalAbiBodiesAuthenticated\":false,\n",
            "  \"componentRoutingAuthenticated\":false,\n  \"canonicalCreationEnabled\":false,\n",
            "  \"schedulingCheckpointsInstalled\":false,\n  \"standardRuntimeQualified\":false\n}}\n"
        ),
        hex(&public.original_digest),
        hex(&public.derived_digest),
        hex(&thread.stack.derived_digest),
        hex(&root.derived_digest),
        hex(&admission.derived_digest),
        public.derived_public_function,
        public.native_import_inserted,
        public.native_admission_import,
        number(root.post_return_function),
        number(root.original_post_return_body),
        number(root.realloc_function),
        number(root.original_realloc_body),
        root.root_stack_low,
        root.root_stack_high,
        number(root.canonical_system_stack_low),
        number(root.canonical_system_stack_high),
        number(root.canonical_system_scope_global),
        root.canonical_system_closure_functions,
    );
    let output = Path::new(&args[6]);
    fs::create_dir(output)?;
    write(&output.join("core.wasm"), &derived)?;
    write(&output.join("receipt.json"), json.as_bytes())
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).take(8).collect();
    if args.first().is_some_and(|value| value == "--ordinary-core") {
        return ordinary(&args);
    }
    if args.len() != 3 {
        return Err("usage: rust-context INPUT sha256:DIGEST FRESH_OUTPUT | --verify-component INPUT FRESH_RECEIPT".into());
    }
    if args[0] == "--verify-component" {
        let raw = read(&args[1])?;
        let receipt = verify_component_routing(&raw)?;
        let json = format!(
            concat!(
                "{{\n  \"schemaVersion\":\"latent.rust.component-routing-source.v1\",\n",
                "  \"componentDigest\":\"sha256:{}\",\n  \"mainCoreDigest\":\"sha256:{}\",\n",
                "  \"mainModule\":{},\n  \"shimModule\":{},\n  \"fixupModule\":{},\n",
                "  \"rawCreationSlot\":{},\n  \"nativeAdmissionSlot\":{},\n",
                "  \"nativeAdmissionRoutingAuthenticated\":true,\n",
                "  \"privateExecutorGraphAuthenticated\":false,\n  \"canonicalCreationEnabled\":false,\n",
                "  \"standardRuntimeQualified\":false\n}}\n"
            ),
            hex(&receipt.component_digest),
            hex(&receipt.main_core_digest),
            receipt.main_module,
            receipt.shim_module,
            receipt.fixup_module,
            receipt.raw_creation_slot,
            receipt.native_admission_slot
        );
        return write(Path::new(&args[2]), json.as_bytes());
    }
    let expected = preimage(&args[1])?;
    let raw = read(&args[0])?;
    let (threaded, thread) = transform_owned_thread_entry(&raw, expected)?;
    let (rooted, root) =
        transform_owned_root_bootstrap(&threaded, thread.stack.derived_digest, &thread)?;
    let (derived, admission) = transform_owned_thread_admission(&rooted, root.derived_digest)?;
    let json = format!(
        concat!(
            "{{\n  \"schemaVersion\":\"latent.rust.owned-core-source.v1\",\n",
            "  \"originalDigest\":\"sha256:{}\",\n  \"threadDigest\":\"sha256:{}\",\n",
            "  \"rootDigest\":\"sha256:{}\",\n  \"derivedDigest\":\"sha256:{}\",\n",
            "  \"stackGets\":{},\n  \"stackSets\":{},\n  \"entryFunction\":{},\n",
            "  \"originalEntryBody\":{},\n  \"rootFunction\":{},\n  \"originalRootBody\":{},\n",
            "  \"rootStackLow\":{},\n  \"rootStackHigh\":{},\n  \"admissionFunction\":{},\n",
            "  \"remappedCreationReferences\":{},\n  \"componentRoutingAuthenticated\":false,\n",
            "  \"privateExecutorGraphAuthenticated\":false,\n  \"canonicalCreationEnabled\":false,\n",
            "  \"schedulingCheckpointsInstalled\":false,\n  \"standardRuntimeQualified\":false\n}}\n"
        ),
        hex(&thread.stack.original_digest),
        hex(&thread.stack.derived_digest),
        hex(&root.derived_digest),
        hex(&admission.derived_digest),
        thread.stack.transformed_gets,
        thread.stack.transformed_sets,
        thread.entry_function,
        thread.original_rust_body_function,
        root.root_function,
        root.original_rust_body,
        root.root_stack_low,
        root.root_stack_high,
        admission.admission_function,
        admission.remapped_references
    );
    let output = Path::new(&args[2]);
    fs::create_dir(output)?;
    write(&output.join("core.wasm"), &derived)?;
    write(&output.join("receipt.json"), json.as_bytes())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Rust context source mechanism refused: {error}");
        std::process::exit(1);
    }
}
