use std::{io::Read, path::Path};

use latent_artifacts::content_digest;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::Result;

// Independent bounded read of the three-deployment benchmark catalog. The
// field order is the v5 checksum contract, not arbitrary Value key ordering.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {
    format_version: u32,
    checksum: String,
    payload: Payload,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Payload {
    generation: u64,
    generated_at_unix_millis: u64,
    deployments: Vec<Value>,
    snapshot: Value,
    object_generations: Vec<ObjectGeneration>,
    publication_pins: Vec<PublicationPin>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PublicationPin {
    id: String,
    publication: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ObjectGeneration {
    id: String,
    generation: u64,
}

pub(super) fn verify(path: &Path, id: &str, release: &str, generation: u64) -> Result<String> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(1_048_577)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 1_048_576 {
        return Err("benchmark persisted catalog byte limit".into());
    }
    let record: Record = serde_json::from_slice(&bytes)?;
    if record.format_version != 5
        || record.payload.generation != generation
        || record.payload.snapshot["generation"] != generation
        || content_digest(&serde_json::to_vec(&record.payload)?).0 != record.checksum
    {
        return Err("benchmark persisted catalog identity mismatch".into());
    }
    let objects: Vec<_> = record
        .payload
        .object_generations
        .iter()
        .filter(|object| object.id == id)
        .collect();
    let deployments: Vec<_> = record
        .payload
        .deployments
        .iter()
        .filter(|deployment| deployment["metadata"]["name"] == id)
        .collect();
    let selected: Vec<_> = record
        .payload
        .publication_pins
        .iter()
        .filter(|pin| pin.id == id)
        .collect();
    if objects.len() != 1
        || objects[0].generation != generation
        || deployments.len() != 1
        || deployments[0]["spec"]["release"] != release
        || selected.len() != 1
        || selected[0]
            .publication
            .parse::<latent_core::PublicationId>()
            .is_err()
    {
        return Err("benchmark persisted object generation mismatch".into());
    }
    Ok(content_digest(&bytes).0)
}
