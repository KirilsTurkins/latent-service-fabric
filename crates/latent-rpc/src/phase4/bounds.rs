use super::{ValidationError, MAX_ID_BYTES};
use std::{collections::HashMap, mem::size_of};

pub(super) struct Budget(usize);
impl Budget {
    pub(super) fn new<T>(maximum: usize) -> Result<Self, ValidationError> {
        let mut value = Self(maximum);
        value.charge(size_of::<T>())?;
        Ok(value)
    }
    pub(super) fn charge(&mut self, bytes: usize) -> Result<(), ValidationError> {
        self.0 = self.0.checked_sub(bytes).ok_or(ValidationError::Capacity)?;
        Ok(())
    }
    pub(super) fn string(&mut self, value: &String, maximum: usize) -> Result<(), ValidationError> {
        if value.len() > maximum {
            return Err(ValidationError::Capacity);
        }
        self.charge(value.capacity())
    }
    pub(super) fn id(&mut self, value: &String) -> Result<(), ValidationError> {
        self.string(value, MAX_ID_BYTES)?;
        if value.is_empty() || value.chars().any(char::is_control) {
            return Err(ValidationError::Shape);
        }
        Ok(())
    }
    pub(super) fn identity(&mut self, value: &String) -> Result<(), ValidationError> {
        self.string(value, MAX_ID_BYTES)?;
        latent_core::transaction_contract::identity(value).map_err(|_| ValidationError::Shape)
    }
    pub(super) fn optional_id(&mut self, value: Option<&String>) -> Result<(), ValidationError> {
        value.map_or(Ok(()), |value| self.id(value))
    }
    pub(super) fn bytes(&mut self, value: &Vec<u8>, maximum: usize) -> Result<(), ValidationError> {
        if value.len() > maximum {
            return Err(ValidationError::Capacity);
        }
        self.charge(value.capacity())
    }
    pub(super) fn opaque(&mut self, value: &Vec<u8>) -> Result<(), ValidationError> {
        self.bytes(value, 256)?;
        if value.is_empty() {
            return Err(ValidationError::Shape);
        }
        Ok(())
    }
    pub(super) fn sequence<T>(
        &mut self,
        values: &Vec<T>,
        maximum: usize,
    ) -> Result<(), ValidationError> {
        if values.len() > maximum {
            return Err(ValidationError::Capacity);
        }
        self.charge(
            values
                .capacity()
                .checked_mul(size_of::<T>())
                .ok_or(ValidationError::Capacity)?,
        )
    }
    pub(super) fn metadata(
        &mut self,
        values: &HashMap<String, String>,
        caller: bool,
    ) -> Result<(), ValidationError> {
        if values.len() > 32 {
            return Err(ValidationError::Capacity);
        }
        self.charge(
            values
                .capacity()
                .checked_mul(128)
                .ok_or(ValidationError::Capacity)?,
        )?;
        let mut remaining: usize = 8192;
        for (key, value) in values {
            self.identity(key)?;
            self.string(value, 1024)?;
            remaining = remaining
                .checked_sub(key.capacity())
                .and_then(|n| n.checked_sub(value.capacity()))
                .ok_or(ValidationError::Capacity)?;
            if key.is_empty()
                || key.chars().any(char::is_control)
                || value.chars().any(char::is_control)
                || (caller
                    && ["latent.auth.", "latent.principal."].iter().any(|prefix| {
                        key.get(..prefix.len())
                            .is_some_and(|part| part.eq_ignore_ascii_case(prefix))
                    }))
            {
                return Err(ValidationError::Shape);
            }
        }
        Ok(())
    }
}

pub(super) fn required<T>(value: Option<&T>) -> Result<&T, ValidationError> {
    value.ok_or(ValidationError::Shape)
}
pub(super) fn decimal(value: &str, positive: bool) -> Result<u64, ValidationError> {
    let parsed = value.parse::<u64>().map_err(|_| ValidationError::Shape)?;
    if parsed.to_string() != value || (positive && parsed == 0) {
        return Err(ValidationError::Shape);
    }
    Ok(parsed)
}
pub(super) fn digest(value: &str) -> Result<(), ValidationError> {
    if !value.starts_with("sha256:")
        || value.len() != 71
        || !value[7..]
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
