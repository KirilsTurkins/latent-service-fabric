//! Native protected operator inspection. No guest or request-selected decoder
//! can supply authority through this module.
mod diagnostic;
pub(super) mod failure;

pub use diagnostic::TransactionStoreDiagnosis;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod assets;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod authority;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod catalog;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod codecs;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod execution;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod operation;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod profile;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod request;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use execution::NativeRecoveryReport;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(in crate::standalone) use operation::{recover as recover_namespace, RecoveryOwners};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use request::NativeRecoveryRequest;
