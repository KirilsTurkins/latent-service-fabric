//! A historical receipt is not a minimum view for a new invocation or query.
//! This observation comes from the actual stored terminal command and current
//! reviewed namespace history. It grants no access without a live read-result
//! decision for the original publication and caller scope.
use latent_commit::atomic::{command_row_key, CommandRecord, Outcome};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{ReadView, StoreError},
    namespace::{catalog::NamespaceRead, history::NamespaceHistory, NamespaceRecord},
    session::{version::ViewIdentity, StateMode, StateScope},
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewedResultHistory {
    original: CommandRecord,
    namespace: NamespaceRecord,
    current: ViewIdentity,
}

impl ReviewedResultHistory {
    /// The same physical snapshot supplies both the original command row and
    /// current namespace/history. Ready history is published only by the actual
    /// reviewed migration/resume owners; a paused restore cannot use this path.
    /// This observation does not grant publication, result or mutation access.
    pub fn capture(
        view: &ReadView,
        namespace: &NamespaceRead,
        original: &CommandRecord,
    ) -> Result<Self, StoreError> {
        if original.outcome() == Outcome::Pending {
            return Err(StoreError::Unavailable);
        }
        let actual = view
            .get(&command_row_key(original.id()))?
            .ok_or(StoreError::Conflict)?;
        if CommandRecord::decode(&actual).map_err(|_| StoreError::Corrupt)? != *original
            || view.get(&namespace.expectation().key)? != namespace.expectation().value
        {
            return Err(StoreError::Conflict);
        }
        let scope = original_scope(original)?;
        let record = namespace.record();
        if record.tenant != scope.tenant
            || record.id != scope.namespace
            || record.version.incarnation != scope.incarnation
        {
            return Err(StoreError::Conflict);
        }
        latent_state::recovery::require_namespace_ready(
            view,
            &scope.tenant,
            &scope.namespace,
            scope.incarnation,
        )?;
        let (history, bytes) = NamespaceHistory::capture(view, record)?;
        let current = ViewIdentity {
            namespace: record.version,
            epochs: history.epochs,
        };
        let token = original.committed_view_token().ok_or(StoreError::Corrupt)?;
        let old = ViewIdentity::from_token(&scope, token).map_err(|_| StoreError::Corrupt)?;
        if Some(old.namespace) != original.committed_version() {
            return Err(StoreError::Corrupt);
        }
        if record.state_schema == scope.state_schema && current.epochs == old.epochs {
            current
                .require_minimum(&scope, token)
                .map_err(|_| StoreError::Unavailable)?;
        } else if bytes.is_none() {
            // An absent legacy row cannot certify a reviewed history change.
            return Err(StoreError::Unavailable);
        }
        Ok(Self {
            original: original.clone(),
            namespace: record.clone(),
            current,
        })
    }

    pub(super) fn check_selection(
        &self,
        namespace: &NamespaceRead,
        original_schema: &str,
    ) -> Result<(), super::PlatformError> {
        if namespace.record() != &self.namespace
            || self.original.source().state_schema != original_schema
        {
            return Err(super::denied());
        }
        Ok(())
    }

    pub(super) fn original(&self) -> &CommandRecord {
        &self.original
    }

    pub(super) fn rebind(&self, namespace: &NamespaceRead) -> Result<Self, super::PlatformError> {
        let current = namespace.record();
        if current.tenant != self.namespace.tenant
            || current.id != self.namespace.id
            || current.version.incarnation != self.namespace.version.incarnation
            || current.state_schema != self.namespace.state_schema
        {
            return Err(super::denied());
        }
        let mut result = self.clone();
        result.namespace = current.clone();
        result.current.namespace = current.version;
        Ok(result)
    }

    pub(super) fn require_current(
        &self,
        view: &ReadView,
        namespace: &NamespaceRead,
        original: &CommandRecord,
    ) -> Result<(), StoreError> {
        let current = Self::capture(view, namespace, original)?;
        if current.original != self.original
            || current.namespace.state_schema != self.namespace.state_schema
            || current.current.epochs != self.current.epochs
        {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
}

fn original_scope(record: &CommandRecord) -> Result<StateScope, StoreError> {
    let key = record.key();
    Ok(StateScope {
        tenant: TenantId(key.tenant.clone()),
        namespace: StateNamespaceId(key.namespace.clone()),
        incarnation: key.incarnation.parse().map_err(|_| StoreError::Corrupt)?,
        state_schema: record.source().state_schema.clone(),
        entity: key.entity.clone(),
        mode: StateMode::Query,
    })
}
