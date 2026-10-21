//! Bounded, language-neutral WIT metadata driver for standalone capsule builds.
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::path::Path;

use latent_artifacts::package::{encode_wit_lock, PackageLimits};
use latent_packaging::{derive_capsule_contracts, SemanticLimits};
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    world: String,
    sources: Vec<Source>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    path: String,
    content: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("capsule contract generation failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args
        .first()
        .is_some_and(|value| value == "--c-thread-derive-v1")
    {
        let [_, input, public, output] = args.as_slice() else {
            return Err(
                "C derivation requires original core, public export and new directory".into(),
            );
        };
        return c_derive(
            Path::new(input),
            public.to_str().ok_or("C export must be UTF-8")?,
            Path::new(output),
        );
    }
    if args
        .first()
        .is_some_and(|value| value == "--c-thread-bind-v1")
    {
        let [_, input, component, public, output] = args.as_slice() else {
            return Err(
                "C proof binding requires original core, component, public export and new file"
                    .into(),
            );
        };
        return c_bind(
            Path::new(input),
            Path::new(component),
            public.to_str().ok_or("C export must be UTF-8")?,
            Path::new(output),
        );
    }
    let [input, output] = args.as_slice() else {
        return Err("usage: capsule_contracts <wit-inputs.json> <new-output-directory>".into());
    };
    let mut bytes = Vec::new();
    std::fs::File::open(input)?
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err("WIT input envelope exceeds byte limit".into());
    }
    let input: Input = serde_json::from_slice(&bytes)?;
    let limits = SemanticLimits::default();
    if input.sources.len() > limits.max_wit_packages {
        return Err("WIT source count exceeds limit".into());
    }
    let mut files = BTreeMap::new();
    for source in &input.sources {
        if files
            .insert(source.path.clone(), source.content.as_bytes())
            .is_some()
        {
            return Err("duplicate WIT source path".into());
        }
    }
    let derived =
        derive_capsule_contracts(&input.world, &files, limits).map_err(|error| error.message)?;
    let lock = encode_wit_lock(derived.wit_lock(), PackageLimits::default())
        .map_err(|error| error.message)?;
    let surface = serde_json::to_vec_pretty(&serde_json::json!({
        "world": derived.wit_lock().world,
        "imports": derived.imports(), "exports": derived.exports(),
    }))?;
    std::fs::create_dir(output)?;
    for (name, contents) in [
        ("contracts.json", derived.contracts()),
        ("wit-lock.json", lock.as_slice()),
        ("surface.json", surface.as_slice()),
    ] {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(Path::new(output).join(name))?;
        file.write_all(contents)?;
    }
    Ok(())
}

fn c_read(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take((latent_component_threading::MAX_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > latent_component_threading::MAX_BYTES {
        return Err("C component exceeds the existing transform byte bound".into());
    }
    Ok(bytes)
}

fn c_write(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?
        .write_all(bytes)?;
    Ok(())
}

fn c_derive(input: &Path, public: &str, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    use sha2::{Digest, Sha256};
    let original = c_read(input)?;
    // Enforce the final transport envelope before any transform allocation.
    latent_component_threading::c_preimage::check_original_envelope(&original, public)?;
    let (derived, proof) = latent_component_threading::c_abi::transform_c_canonical_abi(
        &original,
        Sha256::digest(&original).into(),
        public,
    )?;
    let receipt = serde_json::to_vec_pretty(&serde_json::json!({
        "formatVersion": 1, "profile": "c-context144-sync-cooperative-v1",
        "originalCoreDigest": format!("sha256:{:x}", Sha256::digest(&original)),
        "derivedCoreDigest": format!("sha256:{:x}", Sha256::digest(&derived)),
        "publicExport": public, "rootRecordBytes": proof.root.root_record_bytes,
        "canonicalComponentAuthenticated": false, "standardRuntimeQualified": false,
    }))?;
    std::fs::create_dir(output)?;
    c_write(&output.join("derived.wasm"), &derived)?;
    c_write(&output.join("derivation.json"), &receipt)
}

fn c_bind(
    input: &Path,
    component: &Path,
    public: &str,
    output: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let original = c_read(input)?;
    let component = c_read(component)?;
    let bound = latent_component_threading::c_preimage::attach_c_original_core(
        &original, &component, public,
    )?;
    c_write(output, &bound)
}
