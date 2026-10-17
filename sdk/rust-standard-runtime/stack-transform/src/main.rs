//! Bounded source-stage CLI. It emits no supported-profile or host permission.
use latent_rust_std_stack_source_transform::{MAX_BYTES, transform_owned_thread_entry,
    transform_owned_root_bootstrap, transform_owned_thread_admission, verify_component_routing};
use std::{fs::{File, OpenOptions}, io::{Read, Write}, path::Path};

fn read(path: &Path) -> Result<Vec<u8>, &'static str> {
    let input = File::open(path).map_err(|_| "rust-shim-input-open")?;
    let mut bytes = Vec::new();
    input.take((MAX_BYTES + 1) as u64).read_to_end(&mut bytes).map_err(|_| "rust-shim-input-read")?;
    if bytes.len() > MAX_BYTES { return Err("rust-shim-input-bound"); }
    Ok(bytes)
}
fn hex(input: &[u8; 32]) -> String { input.iter().map(|byte| format!("{byte:02x}")).collect() }
fn digest(input: &str) -> Result<[u8; 32], &'static str> {
    let input = input.strip_prefix("sha256:").ok_or("rust-shim-preimage-format")?;
    if input.len() != 64 || !input.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("rust-shim-preimage-format");
    }
    let mut output = [0; 32];
    for (i, slot) in output.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&input[i * 2..i * 2 + 2], 16).map_err(|_| "rust-shim-preimage-format")?;
    }
    Ok(output)
}
fn write(path: &Path, data: &[u8]) -> Result<(), &'static str> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path).map_err(|_| "rust-shim-output-not-fresh")?;
    file.write_all(data).map_err(|_| "rust-shim-output-write")
}
fn run(args: &[String]) -> Result<(), &'static str> {
    match args {
        [mode, input, expected, output] if mode == "transform-core" => {
            let bytes = read(Path::new(input))?;
            let (threaded, thread) = transform_owned_thread_entry(&bytes, digest(expected)?)?;
            let (rooted, root) = transform_owned_root_bootstrap(&threaded, thread.stack.derived_digest, &thread)?;
            let (derived, admission) = transform_owned_thread_admission(&rooted, root.derived_digest)?;
            let output = Path::new(output);
            std::fs::create_dir(output).map_err(|_| "rust-shim-output-not-fresh")?;
            write(&output.join("core.wasm"), &derived)?;
            let receipt = format!(concat!("{{\n  \"schemaVersion\":\"latent.rust.owned-core-source-transform.v1\",\n",
                "  \"originalDigest\":\"sha256:{}\",\n  \"derivedDigest\":\"sha256:{}\",\n",
                "  \"rootStackLow\":{},\n  \"rootStackHigh\":{},\n  \"rawCreationImport\":{},\n",
                "  \"fixedAdmissionFunction\":{},\n  \"componentRoutingAuthenticated\":false,\n",
                "  \"canonicalCreationEnabled\":false,\n  \"standardRuntimeQualified\":false\n}}\n"),
                hex(&thread.stack.original_digest), hex(&admission.derived_digest), root.root_stack_low,
                root.root_stack_high, admission.raw_creation_import, admission.admission_function);
            write(&output.join("core-transform.json"), receipt.as_bytes())?;
        },
        [mode, input, output] if mode == "verify-component" => {
            let receipt = verify_component_routing(&read(Path::new(input))?)?;
            let text = format!(concat!("{{\n  \"schemaVersion\":\"latent.rust.component-routing-source-proof.v1\",\n",
                "  \"componentDigest\":\"sha256:{}\",\n  \"mainCoreDigest\":\"sha256:{}\",\n",
                "  \"mainModule\":{},\n  \"shimModule\":{},\n  \"fixupModule\":{},\n",
                "  \"rawCreationSlot\":{},\n  \"nativeAdmissionSlot\":{},\n",
                "  \"componentRoutingAuthenticated\":true,\n  \"canonicalCreationEnabled\":false,\n",
                "  \"standardRuntimeQualified\":false\n}}\n"),
                hex(&receipt.component_digest), hex(&receipt.main_core_digest), receipt.main_module,
                receipt.shim_module, receipt.fixup_module, receipt.raw_creation_slot, receipt.native_admission_slot);
            write(Path::new(output), text.as_bytes())?;
        },
        _ => return Err("rust-shim-usage-transform-core-input-sha256-output-or-verify-component-input-receipt"),
    }
    Ok(())
}
fn main() {
    let args = std::env::args().skip(1).take(6).collect::<Vec<_>>();
    if let Err(reason) = run(&args) { eprintln!("Rust owned shim source stage failed: {reason}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn source_preimage_requires_exact_canonical_sha256_not_a_profile_claim() {
        assert_eq!(digest(&format!("sha256:{}", "00".repeat(32))).unwrap(), [0; 32]);
        for bad in ["supported-profile", "sha256:0", "sha256:../secret", &format!("sha256:{}", "GG".repeat(32))] {
            assert_eq!(digest(bad).unwrap_err(), "rust-shim-preimage-format");
        }
    }
}
