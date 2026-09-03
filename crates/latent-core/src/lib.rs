//! Shared identifiers, budgets, lifecycle values, identities, errors, and async types.

#![forbid(unsafe_code)]

pub mod budget;
pub mod error;
pub mod identity;
pub mod ids;
pub mod lifecycle;

pub use budget::{BudgetConsumption, ResourceBudget};
pub use error::{DeclaredError, ErrorDetail, PlatformError, PlatformErrorCode};
pub use identity::{InvocationPrincipal, PrincipalKind};
pub use ids::*;
pub use lifecycle::{ActivationPhase, ActivationTerminalState, CancelDisposition};

use std::future::Future;
use std::pin::Pin;

/// Heap-allocated asynchronous result used by object-safe architectural traits.
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Opaque binary payload crossing an architectural boundary.
pub type Payload = Vec<u8>;

/// Extensible key/value metadata carried across subsystem boundaries.
pub type Metadata = std::collections::BTreeMap<String, String>;
