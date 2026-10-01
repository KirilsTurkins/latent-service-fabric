//! Namespace closure invalidates accepted provider grants under the same rules
//! fence that their last prewrite check uses. It is metadata only.
use super::{identity, AuthorityError, EffectAuthorityOwner, EffectScope, MutexGuard, State};

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct NamespaceScope {
    tenant: String,
    namespace: String,
    incarnation: u64,
}
impl NamespaceScope {
    pub(super) fn from_effect(scope: &EffectScope) -> Self {
        Self {
            tenant: scope.tenant.clone(),
            namespace: scope.namespace.clone(),
            incarnation: scope.incarnation,
        }
    }
    fn matches(&self, scope: &EffectScope) -> bool {
        self.tenant == scope.tenant
            && self.namespace == scope.namespace
            && self.incarnation == scope.incarnation
    }
}

/// Affine final management metadata fence. The caller already holds its
/// original current policy and namespace lifecycle fences. Its acceptance
/// callback is the original bounded native request gate, without I/O or await.
/// An accepted closure remains sticky through uncertain durable completion.
pub struct NamespaceEffectCloseFence<'a> {
    state: MutexGuard<'a, State>,
    scope: NamespaceScope,
    generation: u64,
}
impl EffectAuthorityOwner {
    pub fn prepare_namespace_close(
        &self,
        tenant: &str,
        namespace: &str,
        incarnation: u64,
    ) -> Result<NamespaceEffectCloseFence<'_>, AuthorityError> {
        if !identity(tenant) || !identity(namespace) || incarnation == 0 {
            return Err(AuthorityError::Invalid);
        }
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        let scope = NamespaceScope {
            tenant: tenant.to_owned(),
            namespace: namespace.to_owned(),
            incarnation,
        };
        if !state.closed_namespaces.contains(&scope)
            && state.closed_namespaces.len() >= self.0.maximum_rules
        {
            return Err(AuthorityError::Capacity);
        }
        let generation = state
            .generation
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        Ok(NamespaceEffectCloseFence {
            state,
            scope,
            generation,
        })
    }
}
impl NamespaceEffectCloseFence<'_> {
    pub fn accept<R, E>(mut self, accept: impl FnOnce() -> Result<R, E>) -> Result<R, E> {
        let result = accept()?;
        for (scope, rule) in &mut self.state.rules {
            if self.scope.matches(scope) {
                rule.enabled = false;
            }
        }
        self.state.closed_namespaces.insert(self.scope);
        self.state.generation = self.generation;
        Ok(result)
    }
}
