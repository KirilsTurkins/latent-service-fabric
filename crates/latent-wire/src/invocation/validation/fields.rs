use std::collections::HashMap;
use std::mem::size_of;

use latent_core::Metadata;
use tonic::Status;

use super::super::InvocationLimits;

// SystemActivationIdSource emits 44 bytes independently of caller name limits.
pub(super) const GENERATED_ACTIVATION_ID_BYTES: usize = 44;

/// Charges source allocations and conservative destination collection overhead.
/// Encoded bytes are checked separately after bounded structural traversal.
pub(super) struct RetainedBytes(usize);

impl RetainedBytes {
    pub(super) fn new<T>(limits: &InvocationLimits) -> Result<Self, Status> {
        let mut bytes = Self(limits.max_message_bytes);
        bytes.charge(size_of::<T>())?;
        Ok(bytes)
    }

    pub(super) fn charge(&mut self, count: usize) -> Result<(), Status> {
        self.0 = self.0.checked_sub(count).ok_or_else(exhausted)?;
        Ok(())
    }

    pub(super) fn allocation<T>(&mut self, capacity: usize) -> Result<(), Status> {
        self.charge(capacity.checked_mul(size_of::<T>()).ok_or_else(exhausted)?)
    }

    pub(super) fn string(&mut self, value: &String, maximum: usize) -> Result<(), Status> {
        if value.len() > maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity())
    }

    pub(super) fn payload(&mut self, value: &Vec<u8>, maximum: usize) -> Result<(), Status> {
        if value.capacity() > maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity())
    }

    pub(super) fn metadata(
        &mut self,
        metadata: &Metadata,
        limits: &InvocationLimits,
        maximum_entries: usize,
        caller: bool,
    ) -> Result<(), Status> {
        self.metadata_entries(metadata.len(), maximum_entries)?;
        self.metadata_strings(metadata.iter(), limits, caller)
    }

    pub(super) fn hash_metadata(
        &mut self,
        metadata: &HashMap<String, String>,
        limits: &InvocationLimits,
    ) -> Result<(), Status> {
        // A sparse owned HashMap can carry considerable capacity with few rows.
        // 128 bytes per capacity slot covers keys/values, control bytes and load
        // slack; the B-tree destination is charged independently below.
        self.charge(metadata.capacity().checked_mul(128).ok_or_else(exhausted)?)?;
        self.metadata_entries(metadata.len(), limits.max_metadata_entries)?;
        self.metadata_strings(metadata.iter(), limits, true)
    }

    fn metadata_entries(&mut self, count: usize, maximum_entries: usize) -> Result<(), Status> {
        if count > maximum_entries {
            return Err(exhausted());
        }
        // Includes sparse B-tree nodes and the hash-map destination. No map is
        // cloned merely to validate it, and this check precedes the first row.
        self.charge(count.checked_mul(4096).ok_or_else(exhausted)?)?;
        self.charge(size_of::<Metadata>())
    }

    fn metadata_strings<'a>(
        &mut self,
        entries: impl Iterator<Item = (&'a String, &'a String)>,
        limits: &InvocationLimits,
        caller: bool,
    ) -> Result<(), Status> {
        let mut remaining = limits.max_metadata_bytes;
        for (key, value) in entries {
            self.string(key, limits.max_string_bytes)?;
            self.string(value, limits.max_string_bytes)?;
            remaining = remaining
                .checked_sub(key.capacity())
                .and_then(|n| n.checked_sub(value.capacity()))
                .ok_or_else(exhausted)?;
            if caller
                && (key.is_empty()
                    || key.chars().any(char::is_control)
                    || value.chars().any(char::is_control))
            {
                return Err(Status::invalid_argument(
                    "metadata contains an invalid key or control character",
                ));
            }
            if caller && reserved_metadata(key) {
                return Err(Status::invalid_argument(
                    "caller metadata must not contain authentication fields",
                ));
            }
        }
        Ok(())
    }
}

fn reserved_metadata(key: &str) -> bool {
    ["latent.auth.", "latent.principal."].iter().any(|prefix| {
        key.get(..prefix.len())
            .is_some_and(|start| start.eq_ignore_ascii_case(prefix))
    })
}

pub(super) fn identifier(value: &str, maximum: usize) -> Result<(), Status> {
    if value.len() > maximum {
        return Err(exhausted());
    }
    if !valid_identifier(value) {
        return Err(Status::invalid_argument(
            "identifier is empty or contains whitespace or a control character",
        ));
    }
    Ok(())
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty() && !value.chars().any(|c| c.is_whitespace() || c.is_control())
}

pub(super) fn media_type(value: &str, maximum: usize) -> Result<(), Status> {
    if value.len() > maximum {
        return Err(exhausted());
    }
    if value.is_empty() || value.chars().any(char::is_control) {
        return Err(Status::invalid_argument(
            "media type is empty or contains a control character",
        ));
    }
    Ok(())
}

pub(super) fn exhausted() -> Status {
    Status::resource_exhausted("invocation value exceeds the configured boundary limit")
}

pub(super) fn runtime_error(error: Status) -> Status {
    if error.code() == tonic::Code::ResourceExhausted {
        error
    } else {
        Status::internal("the invocation runtime returned an invalid value")
    }
}
