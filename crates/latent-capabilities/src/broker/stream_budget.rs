//! Total transfer authorization is separate from refundable resident buffers.
use super::{capacity, invalid, PlatformError};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CapabilityStreamBudget {
    input: u64,
    output: u64,
}
impl CapabilityStreamBudget {
    pub fn new(input: u64, output: u64) -> Result<Self, PlatformError> {
        // Leave room for the independent inline metadata/window allowance within
        // the policy language's 64 MiB maximum operation byte ceilings.
        const MAXIMUM: u64 = 63 * 1024 * 1024;
        if (input == 0 && output == 0) || input > MAXIMUM || output > MAXIMUM {
            return Err(invalid());
        }
        Ok(Self { input, output })
    }
    #[must_use]
    pub const fn input_bytes(self) -> u64 {
        self.input
    }
    #[must_use]
    pub const fn output_bytes(self) -> u64 {
        self.output
    }
}
pub(super) fn policy_bytes(
    input: usize,
    output: usize,
    stream: Option<CapabilityStreamBudget>,
) -> Result<(u64, u64), PlatformError> {
    Ok((
        (input as u64)
            .checked_add(stream.map_or(0, CapabilityStreamBudget::input_bytes))
            .ok_or_else(capacity)?,
        (output as u64)
            .checked_add(stream.map_or(0, CapabilityStreamBudget::output_bytes))
            .ok_or_else(capacity)?,
    ))
}
