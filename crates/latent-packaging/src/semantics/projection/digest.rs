//! The maintained echo builder hashes recursively sorted compact UTF-8 JSON,
//! excluding only the current object's digest (child digests remain included).

use std::io::{self, Write};

use latent_core::PlatformError;
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::{exhausted, invalid};

pub(super) fn validate(bytes: &[u8]) -> Result<(), PlatformError> {
    // Input came from the bounded metadata codec, including its nesting ceiling.
    let document: Value =
        serde_json::from_slice(bytes).map_err(|_| invalid("invalid-contract-digest-document"))?;
    let contracts = document["contracts"]
        .as_array()
        .ok_or_else(|| invalid("invalid-contract-digest-document"))?;
    for contract in contracts {
        let interfaces = contract["interfaces"]
            .as_array()
            .ok_or_else(|| invalid("invalid-contract-digest-document"))?;
        for interface in interfaces {
            check(interface, bytes.len())?;
        }
        check(contract, bytes.len())?;
    }
    Ok(())
}

fn check(value: &Value, maximum: usize) -> Result<(), PlatformError> {
    if value["digest"].as_str() != Some(calculate(value, maximum)?.as_str()) {
        return Err(invalid("contract-metadata-digest-mismatch"));
    }
    Ok(())
}

pub(super) fn calculate(value: &Value, maximum: usize) -> Result<String, PlatformError> {
    let mut output = HashWriter {
        hash: Sha256::new(),
        written: 0,
        maximum,
    };
    canonical(value, &mut output, true).map_err(|_| exhausted("contract-digest-byte-limit"))?;
    Ok(format!("sha256:{:x}", output.hash.finalize()))
}

fn canonical(value: &Value, output: &mut HashWriter, skip_digest: bool) -> io::Result<()> {
    match value {
        Value::Object(object) => {
            output.write_all(b"{")?;
            let mut keys = object
                .keys()
                .filter(|key| !skip_digest || key.as_str() != "digest")
                .collect::<Vec<_>>();
            keys.sort_unstable();
            for (index, key) in keys.into_iter().enumerate() {
                if index > 0 {
                    output.write_all(b",")?;
                }
                serde_json::to_writer(&mut *output, key).map_err(io::Error::other)?;
                output.write_all(b":")?;
                canonical(&object[key], output, false)?;
            }
            output.write_all(b"}")
        }
        Value::Array(array) => {
            output.write_all(b"[")?;
            for (index, value) in array.iter().enumerate() {
                if index > 0 {
                    output.write_all(b",")?;
                }
                canonical(value, output, false)?;
            }
            output.write_all(b"]")
        }
        _ => serde_json::to_writer(output, value).map_err(io::Error::other),
    }
}

struct HashWriter {
    hash: Sha256,
    written: usize,
    maximum: usize,
}

impl Write for HashWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.written = self
            .written
            .checked_add(bytes.len())
            .filter(|size| *size <= self.maximum)
            .ok_or_else(|| io::Error::other("contract digest limit"))?;
        self.hash.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
