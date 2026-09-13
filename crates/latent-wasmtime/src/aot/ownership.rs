//! Affine reservations outlive cancellation and the bytes/process they cover.

use super::{exhausted, invalid, AOT_OUTPUT_METADATA_BYTES};
use latent_core::PlatformError;
use std::sync::{Arc, Mutex};

/// Aggregate producer bounds. These are owned byte allowances, not RSS metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotResourceLimits {
    pub maximum_jobs: usize,
    pub maximum_input_bytes: usize,
    pub maximum_document_bytes: usize,
    pub maximum_native_bytes: usize,
    pub maximum_outputs: usize,
}
impl Default for AotResourceLimits {
    fn default() -> Self {
        Self {
            maximum_jobs: 2,
            maximum_input_bytes: 128 * 1024 * 1024,
            maximum_document_bytes: 128 * 1024 * 1024,
            maximum_native_bytes: 256 * 1024 * 1024,
            maximum_outputs: 4,
        }
    }
}
impl AotResourceLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if !(1..=16).contains(&self.maximum_jobs)
            || !(1..=512 * 1024 * 1024).contains(&self.maximum_input_bytes)
            || !(1..=512 * 1024 * 1024).contains(&self.maximum_document_bytes)
            || !(1..=1024 * 1024 * 1024).contains(&self.maximum_native_bytes)
            || !(1..=64).contains(&self.maximum_outputs)
        {
            return Err(invalid());
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct AotResourceSnapshot {
    pub jobs: usize,
    pub input_bytes: usize,
    pub document_bytes: usize,
    pub native_bytes: usize,
    pub output_metadata_bytes: usize,
    pub output_owners: usize,
}

pub(crate) struct Budget {
    limits: AotResourceLimits,
    used: Mutex<AotResourceSnapshot>,
}
impl Budget {
    pub(crate) fn new(limits: AotResourceLimits) -> Result<Arc<Self>, PlatformError> {
        Ok(Arc::new(Self {
            limits: limits.validate()?,
            used: Mutex::default(),
        }))
    }
    pub(crate) fn snapshot(&self) -> AotResourceSnapshot {
        *self
            .used
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
    pub(crate) fn reserve(
        self: &Arc<Self>,
        input: usize,
        documents: usize,
        output: usize,
    ) -> Result<(WorkPermit, OutputPermit), PlatformError> {
        let mut used = self
            .used
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let next = AotResourceSnapshot {
            jobs: used.jobs.checked_add(1).ok_or_else(exhausted)?,
            input_bytes: used.input_bytes.checked_add(input).ok_or_else(exhausted)?,
            document_bytes: used
                .document_bytes
                .checked_add(documents)
                .ok_or_else(exhausted)?,
            native_bytes: used
                .native_bytes
                .checked_add(output)
                .ok_or_else(exhausted)?,
            output_metadata_bytes: used
                .output_metadata_bytes
                .checked_add(AOT_OUTPUT_METADATA_BYTES)
                .ok_or_else(exhausted)?,
            output_owners: used.output_owners.checked_add(1).ok_or_else(exhausted)?,
        };
        if next.jobs > self.limits.maximum_jobs
            || next.input_bytes > self.limits.maximum_input_bytes
            || next.document_bytes > self.limits.maximum_document_bytes
            || next.native_bytes > self.limits.maximum_native_bytes
            || next.output_owners > self.limits.maximum_outputs
        {
            return Err(exhausted());
        }
        *used = next;
        Ok((
            WorkPermit {
                budget: Arc::clone(self),
                input,
                documents,
            },
            OutputPermit {
                budget: Arc::clone(self),
                native: output,
            },
        ))
    }
}

/// Declared after source/input owners so refunds happen after those owners drop.
pub(crate) struct WorkPermit {
    budget: Arc<Budget>,
    input: usize,
    documents: usize,
}
impl Drop for WorkPermit {
    fn drop(&mut self) {
        let mut used = self
            .budget
            .used
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        used.jobs -= 1;
        used.input_bytes -= self.input;
        used.document_bytes -= self.documents;
    }
}

/// No Clone or public constructor. Native bytes must drop before this owner.
pub(crate) struct OutputPermit {
    budget: Arc<Budget>,
    native: usize,
}
impl OutputPermit {
    pub(crate) fn reserved_bytes(&self) -> usize {
        self.native
    }
}
impl Drop for OutputPermit {
    fn drop(&mut self) {
        let mut used = self
            .budget
            .used
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        used.native_bytes -= self.native;
        used.output_metadata_bytes -= AOT_OUTPUT_METADATA_BYTES;
        used.output_owners -= 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retained_output_and_metadata_outlive_completed_work_and_cap_tiny_outputs() {
        let budget = Budget::new(AotResourceLimits {
            maximum_outputs: 1,
            ..Default::default()
        })
        .unwrap();
        let (work, output) = budget.reserve(8, 128, 1).unwrap();
        assert_eq!(budget.snapshot().jobs, 1);
        drop(work);
        assert_eq!(budget.snapshot().jobs, 0);
        assert_eq!(budget.snapshot().native_bytes, 1);
        assert_eq!(
            budget.snapshot().output_metadata_bytes,
            AOT_OUTPUT_METADATA_BYTES
        );
        assert!(budget.reserve(8, 128, 1).is_err());
        drop(output);
        assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
    }
    #[test]
    fn failed_reservations_are_atomic() {
        let budget = Budget::new(AotResourceLimits {
            maximum_input_bytes: 1,
            ..Default::default()
        })
        .unwrap();
        assert!(budget.reserve(2, 1, 1).is_err());
        assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
        assert!(budget.reserve(usize::MAX, usize::MAX, usize::MAX).is_err());
        assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
    }
}
