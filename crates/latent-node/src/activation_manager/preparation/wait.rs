//! Readiness uses the existing node executor, inside the original stage owner.

pub(super) use crate::CurrentnessReadTimer as Timer;

#[cfg(test)]
mod tests;
