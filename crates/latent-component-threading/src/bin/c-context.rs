//! Explicit C compiler mechanism utility; never enables an engine profile.
use latent_component_threading::{MAX_BYTES, c_context::transform_c_context};
use std::{
    fs,
    io::{Read, Write},
    path::Path,
};
fn hex(raw: &[u8; 32]) -> String {
    raw.iter().map(|x| format!("{x:02x}")).collect()
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).take(4).collect();
    if args.len() != 3 {
        return Err("usage: c-context INPUT sha256:DIGEST FRESH_OUTPUT".into());
    }
    let digest = args[1].strip_prefix("sha256:").ok_or("preimage-format")?;
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
    let mut raw = Vec::new();
    fs::File::open(&args[0])?
        .take((MAX_BYTES + 1) as u64)
        .read_to_end(&mut raw)?;
    if raw.len() > MAX_BYTES {
        return Err("input-byte-bound".into());
    }
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
