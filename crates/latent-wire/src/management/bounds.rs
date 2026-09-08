use std::collections::HashMap;
use std::mem::size_of;

use latent_core::Metadata;
use tonic::Status;

use super::{proto, ManagementLimits};

pub(super) fn exhausted() -> Status {
    Status::resource_exhausted("management data exceeds configured limits")
}

pub(super) fn identifier(value: &str, maximum: usize) -> Result<(), Status> {
    if value.len() > maximum {
        return Err(exhausted());
    }
    if value.is_empty()
        || value
            .chars()
            .any(|ch| ch.is_control() || ch.is_whitespace())
    {
        return Err(Status::invalid_argument("invalid management identifier"));
    }
    Ok(())
}

/// Conservative retained allocation accounting before traversing or cloning data.
pub(super) struct RequestBudget {
    remaining: usize,
}

impl RequestBudget {
    pub(super) fn new<T>(limits: &ManagementLimits) -> Result<Self, Status> {
        Self::with_limit::<T>(limits.max_request_bytes)
    }

    pub(super) fn for_response<T>(limits: &ManagementLimits) -> Result<Self, Status> {
        Self::with_limit::<T>(limits.max_response_bytes)
    }

    fn with_limit<T>(maximum: usize) -> Result<Self, Status> {
        let mut value = Self { remaining: maximum };
        value.allocation::<T>(1)?;
        Ok(value)
    }

    fn charge(&mut self, bytes: usize) -> Result<(), Status> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(exhausted)?;
        Ok(())
    }

    pub(super) fn allocation<T>(&mut self, capacity: usize) -> Result<(), Status> {
        self.charge(capacity.checked_mul(size_of::<T>()).ok_or_else(exhausted)?)
    }

    pub(super) fn string(&mut self, value: &String, maximum: usize) -> Result<(), Status> {
        if value.capacity() > maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity())
    }

    pub(super) fn optional_string(
        &mut self,
        value: Option<&String>,
        maximum: usize,
    ) -> Result<(), Status> {
        value.map_or(Ok(()), |value| self.string(value, maximum))
    }

    pub(super) fn bytes(&mut self, value: &Vec<u8>, maximum: usize) -> Result<(), Status> {
        if value.capacity() > maximum {
            return Err(exhausted());
        }
        self.charge(value.capacity())
    }

    pub(super) fn sequence<T>(&mut self, values: &Vec<T>, maximum: usize) -> Result<(), Status> {
        if values.len() > maximum {
            return Err(exhausted());
        }
        self.allocation::<T>(values.capacity())
    }

    pub(super) fn metadata(
        &mut self,
        values: &HashMap<String, String>,
        limits: &ManagementLimits,
    ) -> Result<(), Status> {
        if values.len() > limits.max_metadata_entries {
            return Err(exhausted());
        }
        // Include sparse buckets and control bytes before visiting entries.
        self.charge(values.capacity().checked_mul(128).ok_or_else(exhausted)?)?;
        // Also reserve conservative sparse nodes for the domain-map destination.
        self.charge(values.len().checked_mul(4096).ok_or_else(exhausted)?)?;
        self.metadata_strings(values.iter(), limits)
    }

    pub(super) fn btree_metadata(
        &mut self,
        values: &Metadata,
        limits: &ManagementLimits,
    ) -> Result<(), Status> {
        if values.len() > limits.max_metadata_entries {
            return Err(exhausted());
        }
        self.charge(values.len().checked_mul(4096).ok_or_else(exhausted)?)?;
        self.metadata_strings(values.iter(), limits)
    }

    fn metadata_strings<'a>(
        &mut self,
        values: impl Iterator<Item = (&'a String, &'a String)>,
        limits: &ManagementLimits,
    ) -> Result<(), Status> {
        let mut remaining = limits.max_metadata_bytes;
        for (key, value) in values {
            self.string(key, limits.max_string_bytes)?;
            self.string(value, limits.max_string_bytes)?;
            remaining = remaining
                .checked_sub(key.capacity())
                .and_then(|n| n.checked_sub(value.capacity()))
                .ok_or_else(exhausted)?;
        }
        Ok(())
    }

    pub(super) fn page(
        &mut self,
        page: Option<&proto::PageRequest>,
        limits: &ManagementLimits,
    ) -> Result<u32, Status> {
        let Some(page) = page else {
            return Ok(limits.default_page_size);
        };
        if let Some(token) = &page.page_token {
            self.string(token, limits.max_page_token_bytes)?;
            identifier(token, limits.max_page_token_bytes)?;
        }
        let size = if page.page_size == 0 {
            limits.default_page_size
        } else {
            page.page_size
        };
        if size > limits.max_page_size {
            return Err(exhausted());
        }
        Ok(size)
    }
}
