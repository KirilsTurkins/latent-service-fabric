use std::collections::BTreeSet;
use std::net::SocketAddr;

use crate::error::Failure;

use super::{invalid, model::Document, InputLimits};

pub(super) fn document(document: &Document) -> Result<(), Failure> {
    if document.format_version != 1 || document.profiles.is_empty() || document.profiles.len() > 16
    {
        return Err(invalid());
    }
    let mut names = BTreeSet::new();
    for profile in &document.profiles {
        name(&profile.name)?;
        if !names.insert(profile.name.as_str()) {
            return Err(invalid());
        }
        endpoint(&profile.endpoint)?;
        tenant(&profile.tenant)?;
        if !(32..=256).contains(&profile.token.len())
            || !profile
                .token
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
        {
            return Err(invalid());
        }
        timeout(profile.connect_timeout_millis)?;
        timeout(profile.rpc_timeout_millis)?;
        limits(profile.limits)?;
    }
    if document
        .default_profile
        .as_ref()
        .is_some_and(|value| !names.contains(value.as_str()))
    {
        return Err(invalid());
    }
    Ok(())
}

pub(super) fn endpoint(value: &str) -> Result<(), Failure> {
    if value.len() > 256 {
        return Err(invalid());
    }
    value
        .strip_prefix("http://")
        .and_then(|value| value.parse::<SocketAddr>().ok())
        .filter(|address| address.ip().is_loopback() && address.port() != 0)
        .ok_or_else(invalid)?;
    Ok(())
}

pub(super) fn tenant(value: &str) -> Result<(), Failure> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || bytes.len() > 128
        || !bytes[0].is_ascii_alphanumeric()
        || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        || !bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(byte))
    {
        return Err(invalid());
    }
    Ok(())
}

pub(super) fn timeout(value: u64) -> Result<(), Failure> {
    if !(1..=300_000).contains(&value) {
        return Err(invalid());
    }
    Ok(())
}

fn name(value: &str) -> Result<(), Failure> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
    {
        return Err(invalid());
    }
    Ok(())
}

fn limits(value: InputLimits) -> Result<(), Failure> {
    if !(1..=64 * 1024 * 1024).contains(&value.maximum_component_bytes)
        || !(1..=1024 * 1024).contains(&value.maximum_payload_bytes)
        || !(1..=16 * 1024 * 1024).contains(&value.maximum_response_bytes)
    {
        return Err(invalid());
    }
    Ok(())
}
