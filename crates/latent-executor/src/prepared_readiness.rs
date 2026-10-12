//! Affine immutable readiness acquired before assigning an execution cell.

use std::any::Any;
use std::fmt;

use latent_core::ContractId;

use crate::{PreparedActivation, PreparedComponent};

/// A pin retained while waiting for an execution cell. Backend-specific owners
/// must contain immutable code and bounded reservations, never a running Store.
/// The legacy fallback preserves the original backend's prepared owner intact.
#[must_use = "dropping readiness releases its prepared state and reservations"]
pub struct PreparedReadiness(Ownership);

enum Ownership {
    Legacy(PreparedActivation),
    Backend {
        descriptor: Box<PreparedComponent>,
        imports: Vec<ContractId>,
        ownership: Box<dyn Any + Send + Sync>,
    },
}

impl PreparedReadiness {
    /// Backend extension point. The owner must reclaim its resources on Drop.
    pub fn new<T: Any + Send + Sync>(
        descriptor: PreparedComponent,
        imports: Vec<ContractId>,
        ownership: T,
    ) -> Self {
        Self(Ownership::Backend {
            descriptor: Box::new(descriptor),
            imports,
            ownership: Box::new(ownership),
        })
    }

    #[must_use]
    pub fn descriptor(&self) -> &PreparedComponent {
        match &self.0 {
            Ownership::Legacy(activation) => activation.prepared.descriptor(),
            Ownership::Backend { descriptor, .. } => descriptor,
        }
    }

    #[must_use]
    pub fn imports(&self) -> &[ContractId] {
        match &self.0 {
            Ownership::Legacy(activation) => &activation.imports,
            Ownership::Backend { imports, .. } => imports,
        }
    }

    /// Type mismatch returns the intact affine owner, including its imports.
    pub fn into_parts<T: Any + Send + Sync>(
        self,
    ) -> Result<(PreparedComponent, Vec<ContractId>, T), Self> {
        match self.0 {
            Ownership::Backend {
                descriptor,
                imports,
                ownership,
            } => match ownership.downcast::<T>() {
                Ok(ownership) => Ok((*descriptor, imports, *ownership)),
                Err(ownership) => Err(Self(Ownership::Backend {
                    descriptor,
                    imports,
                    ownership,
                })),
            },
            legacy => Err(Self(legacy)),
        }
    }

    pub(crate) fn from_activation(activation: PreparedActivation) -> Self {
        Self(Ownership::Legacy(activation))
    }

    pub(crate) fn into_activation(self) -> Result<PreparedActivation, Self> {
        match self.0 {
            Ownership::Legacy(activation) => Ok(activation),
            backend => Err(Self(backend)),
        }
    }
}

impl fmt::Debug for PreparedReadiness {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedReadiness")
            .field("descriptor", self.descriptor())
            .field("imports", &self.imports())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests;
