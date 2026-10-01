//! Native protected operator inspection. No guest or request-selected decoder
//! can supply authority through this module.
mod diagnostic;
pub(super) mod failure;

pub use diagnostic::TransactionStoreDiagnosis;
