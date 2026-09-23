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
