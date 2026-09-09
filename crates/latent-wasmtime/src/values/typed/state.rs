use latent_core::PlatformError;
use serde::de;

use super::{super::limit, node_bytes, ValueCodecLimits};

pub(super) struct State {
    pub(super) limits: ValueCodecLimits,
    pub(super) failure: Option<PlatformError>,
    remaining: usize,
}

impl State {
    pub(super) fn new(limits: ValueCodecLimits) -> Self {
        Self {
            limits,
            failure: None,
            remaining: limits.max_decoded_value_bytes,
        }
    }

    pub(super) fn fail<E: de::Error>(&mut self, failure: PlatformError) -> E {
        if self.failure.is_none() {
            self.failure = Some(failure);
        }
        E::custom("typed component value limit or contract")
    }

    pub(super) fn charge<E: de::Error>(&mut self, bytes: usize) -> Result<(), E> {
        self.remaining = self
            .remaining
            .checked_sub(bytes)
            .ok_or_else(|| self.fail(limit()))?;
        Ok(())
    }

    pub(super) fn node<E: de::Error>(&mut self, depth: usize, prepaid: bool) -> Result<(), E> {
        if depth > self.limits.max_depth {
            return Err(self.fail(limit()));
        }
        if prepaid {
            Ok(())
        } else {
            self.charge(node_bytes())
        }
    }

    pub(super) fn text<E: de::Error>(&mut self, text: &str) -> Result<(), E> {
        if text.len() > self.limits.max_string_bytes {
            return Err(self.fail(limit()));
        }
        let bytes = text
            .len()
            .checked_mul(2)
            .ok_or_else(|| self.fail(limit()))?;
        self.charge(bytes)
    }

    /// Prepay known child nodes before reserving their slots. Child seeds skip
    /// only this charge, retaining the exact successful total. Reserving it here
    /// prevents nested containers reusing the allowance of unparsed siblings.
    pub(super) fn prepay<E: de::Error>(&mut self, width: usize) -> Result<(), E> {
        if width > self.limits.max_collection_items {
            return Err(self.fail(limit()));
        }
        let bytes = width
            .checked_mul(node_bytes())
            .ok_or_else(|| self.fail(limit()))?;
        self.charge(bytes)
    }

    pub(super) fn reserve<T, E: de::Error>(
        &mut self,
        values: &mut Vec<T>,
        additional: usize,
    ) -> Result<(), E> {
        values
            .try_reserve_exact(additional)
            .map_err(|_| self.fail(limit()))
    }

    /// Incremental collections use geometric growth capped by the declared item
    /// limit. No untrusted serde size hint can trigger a speculative allocation.
    pub(super) fn push<T, E: de::Error>(&mut self, values: &mut Vec<T>, value: T) -> Result<(), E> {
        if values.len() >= self.limits.max_collection_items {
            return Err(self.fail(limit()));
        }
        if values.len() == values.capacity() {
            let capacity = values
                .capacity()
                .saturating_mul(2)
                .max(4)
                .min(self.limits.max_collection_items);
            self.reserve(values, capacity - values.len())?;
        }
        values.push(value);
        Ok(())
    }

    pub(super) fn own<E: de::Error>(&mut self, text: &str) -> Result<String, E> {
        let mut result = String::new();
        result
            .try_reserve_exact(text.len())
            .map_err(|_| self.fail(limit()))?;
        result.push_str(text);
        Ok(result)
    }
}
