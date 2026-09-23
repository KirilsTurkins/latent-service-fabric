//! Offline authoring adapter; it establishes no signing or execution authority.
use std::collections::BTreeMap;

use latent_artifacts::package::{encode_wit_lock, PackageLimits};
use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_packaging::{derive_capsule_contracts, SemanticLimits};
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    world: String,
    sources: BTreeMap<String, String>,
}

pub(super) fn derive(path: &str) -> Result<(), Box<dyn std::error::Error>> {
    let request: Request = serde_json::from_slice(&super::read(path, 8 * 1024 * 1024)?)?;
    let sources = request
        .sources
        .iter()
        .map(|(path, source)| (path.clone(), source.as_bytes()))
        .collect();
    let generated = derive_capsule_contracts(&sources, &request.world, SemanticLimits::default())
        .map_err(|error| error.message)?;
    let contracts: Value = serde_json::from_slice(
        &encode_contract_metadata(&generated.contracts, ContractMetadataLimits::default())
            .map_err(|error| error.message)?,
    )?;
    let lock: Value = serde_json::from_slice(
        &encode_wit_lock(&generated.wit_lock, PackageLimits::default())
            .map_err(|error| error.message)?,
    )?;
    println!(
        "{}",
        serde_json::json!({"contracts": contracts, "witLock": lock, "imports": generated.imports})
    );
    Ok(())
}
