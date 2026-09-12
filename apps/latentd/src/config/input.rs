use std::fs::File;
use std::io::Read;
use std::path::Path;

use latent_core::PlatformError;

use super::{invalid, NodeConfig};

const MAXIMUM_CONFIG_BYTES: u64 = 64 * 1024;

pub(super) fn load(path: &Path) -> Result<NodeConfig, PlatformError> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|_| invalid("configurationPath"))?
            .join(path)
    };
    let mut bytes = Vec::new();
    File::open(&absolute)
        .map_err(|_| invalid("configurationFile"))?
        .take(MAXIMUM_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| invalid("configurationFile"))?;
    if bytes.len() as u64 > MAXIMUM_CONFIG_BYTES {
        return Err(invalid("configurationSize"));
    }
    let mut config = decode(&bytes)?;
    if let super::SupplyChainConfig::Enforced { policy_file, .. } = &mut config.supply_chain {
        if policy_file.as_os_str().is_empty() {
            return Err(invalid("supplyChain.policyFile"));
        }
        if policy_file.is_relative() {
            let parent = absolute
                .parent()
                .ok_or_else(|| invalid("configurationPath"))?
                .canonicalize()
                .map_err(|_| invalid("configurationPath"))?;
            *policy_file = parent.join(&*policy_file);
        }
    }
    if config.data_directory.as_os_str().is_empty() {
        return Err(invalid("dataDirectory"));
    }
    if config.data_directory.is_relative() {
        let parent = absolute
            .parent()
            .ok_or_else(|| invalid("configurationPath"))?;
        // Only the already-existing configuration parent is canonicalized.
        // Catalog roots and the data directory are created later by startup.
        let parent = parent
            .canonicalize()
            .map_err(|_| invalid("configurationPath"))?;
        config.data_directory = parent.join(&config.data_directory);
    }
    Ok(config)
}

pub(super) fn decode(bytes: &[u8]) -> Result<NodeConfig, PlatformError> {
    if bytes.len() as u64 > MAXIMUM_CONFIG_BYTES {
        return Err(invalid("configurationSize"));
    }
    // Bound nesting and structural tokens before Serde allocates containers.
    // Serde then checks syntax, duplicate fields and every unknown field.
    let mut depth = 0_u32;
    let mut structures = 0_u32;
    let mut quoted = false;
    let mut escaped = false;
    for byte in bytes {
        if quoted {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                quoted = false;
            }
        } else {
            match byte {
                b'"' => quoted = true,
                b'{' | b'[' => {
                    depth += 1;
                    structures += 1;
                }
                b'}' | b']' => {
                    depth = depth.checked_sub(1).ok_or_else(|| invalid("document"))?;
                }
                b',' | b':' => structures += 1,
                _ => {}
            }
        }
        if depth > 16 || structures > 4096 {
            return Err(invalid("configurationStructure"));
        }
    }
    serde_json::from_slice(bytes).map_err(|_| invalid("document"))
}
