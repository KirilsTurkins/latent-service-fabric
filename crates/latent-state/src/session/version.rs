//! Opaque descriptive view tokens bind schema and recovery history. They are
//! preconditions, never namespace, policy or result-read authority.

use super::{codec, namespace_key, StateError, StateScope};
use crate::{
    embedded::{ExpectedRow, ReadView},
    namespace::{
        history::{history_key, HistoryEpochs, NamespaceHistory},
        NamespaceRecord, NamespaceVersion,
    },
};
use sha2::{Digest, Sha256};

const MAGIC: &[u8] = b"NV\x02";
pub const VIEW_TOKEN_BYTES: usize = 67;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ViewIdentity {
    pub namespace: NamespaceVersion,
    pub epochs: HistoryEpochs,
}

impl ViewIdentity {
    pub fn token(self, scope: &StateScope) -> Result<Vec<u8>, StateError> {
        if self.namespace.incarnation == 0
            || self.namespace.generation == 0
            || self.namespace.incarnation != scope.incarnation
            || self.epochs.validate().is_err()
        {
            return Err(StateError::Invalid);
        }
        for identity in [&scope.tenant.0, &scope.namespace.0] {
            latent_core::transaction_contract::identity(identity)
                .map_err(|_| StateError::Invalid)?;
        }
        if scope.state_schema.len() != 71
            || !scope.state_schema.starts_with("sha256:")
            || !scope.state_schema.as_bytes()[7..]
                .iter()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
            || scope
                .entity
                .as_ref()
                .is_some_and(|entity| latent_core::transaction_contract::identity(entity).is_err())
        {
            return Err(StateError::Invalid);
        }
        let mut token = MAGIC.to_vec();
        token.extend_from_slice(&scope_digest(scope)?);
        for value in [
            self.namespace.incarnation,
            self.namespace.generation,
            self.epochs.schema,
            self.epochs.recovery,
        ] {
            token.extend_from_slice(&value.to_le_bytes());
        }
        Ok(token)
    }

    pub fn from_token(scope: &StateScope, token: &[u8]) -> Result<Self, StateError> {
        if token.len() != VIEW_TOKEN_BYTES
            || !token.starts_with(MAGIC)
            || token[3..35] != scope_digest(scope)?
        {
            return Err(StateError::Invalid);
        }
        let number = |start| -> Result<u64, StateError> {
            Ok(u64::from_le_bytes(
                token[start..start + 8]
                    .try_into()
                    .map_err(|_| StateError::Invalid)?,
            ))
        };
        let identity = Self {
            namespace: NamespaceVersion {
                incarnation: number(35)?,
                generation: number(43)?,
            },
            epochs: HistoryEpochs {
                schema: number(51)?,
                recovery: number(59)?,
            },
        };
        identity.token(scope)?;
        Ok(identity)
    }

    /// A larger generation in another history cannot satisfy an old minimum.
    pub fn require_minimum(self, scope: &StateScope, token: &[u8]) -> Result<(), StateError> {
        self.token(scope)?;
        let expected = Self::from_token(scope, token)?;
        if self.namespace.incarnation != expected.namespace.incarnation
            || self.epochs != expected.epochs
        {
            return Err(StateError::RecoveryRequired);
        }
        if self.namespace.generation < expected.namespace.generation {
            return Err(StateError::Conflict);
        }
        Ok(())
    }
}

/// Captures the same actual namespace/history rows for a coordinator disposition
/// without state writes. Callers still authorize the scope and final commit.
pub fn capture_view_identity(
    view: &ReadView,
    scope: &StateScope,
) -> Result<ViewIdentity, StateError> {
    Ok(capture_view(view, scope)?.identity())
}

/// Exact history observation for a no-state disposition. The coordinator still
/// retains its native view, owns the namespace mutation and rechecks authority.
pub struct CapturedView {
    identity: ViewIdentity,
    history_expectation: ExpectedRow,
}

impl CapturedView {
    #[must_use]
    pub fn identity(&self) -> ViewIdentity {
        self.identity
    }

    #[must_use]
    pub fn history_expectation(&self) -> ExpectedRow {
        self.history_expectation.clone()
    }
}

pub fn capture_view(view: &ReadView, scope: &StateScope) -> Result<CapturedView, StateError> {
    let bytes = view
        .get(&namespace_key(scope)?)?
        .ok_or(StateError::PermissionDenied)?;
    let namespace = NamespaceRecord::decode(&bytes).map_err(|_| StateError::Corrupt)?;
    if namespace.tenant != scope.tenant
        || namespace.id != scope.namespace
        || namespace.version.incarnation != scope.incarnation
        || namespace.state_schema != scope.state_schema
    {
        return Err(StateError::PermissionDenied);
    }
    let (history, history_bytes) = NamespaceHistory::capture(view, &namespace)?;
    Ok(CapturedView {
        identity: ViewIdentity {
            namespace: namespace.version,
            epochs: history.epochs,
        },
        history_expectation: ExpectedRow {
            key: history_key(&scope.tenant, &scope.namespace, scope.incarnation)
                .map_err(|_| StateError::Corrupt)?,
            value: history_bytes,
        },
    })
}

fn scope_digest(scope: &StateScope) -> Result<[u8; 32], StateError> {
    let mut hash = Sha256::new();
    hash.update(b"lsf-namespace-view-v2\0");
    hash.update(codec::key_prefix(scope)?);
    hash.update(scope.state_schema.as_bytes());
    Ok(hash.finalize().into())
}
