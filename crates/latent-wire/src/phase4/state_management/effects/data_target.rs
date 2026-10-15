use super::{Access, Error, Inner, OwnedPolicyDecision};
use latent_commit::atomic::CommandRecord;
use latent_policy::capability::RecoveryScopeKind;

/// Original row data, independent of the real current administrator actor.
pub(super) struct DataTarget {
    pub kind: RecoveryScopeKind,
    pub scope: String,
}

pub(super) struct BoundTarget {
    pub target: DataTarget,
    pub read: OwnedPolicyDecision,
}

impl DataTarget {
    pub(super) fn original(
        inner: &Inner,
        access: &Access,
        record: &CommandRecord,
    ) -> Result<Self, Error> {
        let source = record.source();
        let key = record.key();
        let namespace = &access.namespace.binding;
        if key.namespace != namespace.namespace.0
            || key.incarnation != namespace.incarnation.to_string()
            || source.state_schema != namespace.state_schema
            || !inner.bindings.iter().any(|binding| {
                binding.recovery == Some(RecoveryScopeKind::OriginalCaller)
                    && binding.publication.id.as_str() == source.publication
                    && binding
                        .publication
                        .scope
                        .tenant()
                        .is_some_and(|tenant| tenant.0 == key.tenant)
                    && binding.component.0 == source.component_digest
                    && binding.component.0 == source.release_digest
                    && binding.state_schema == source.state_schema
                    && binding.namespace.0 == key.namespace
                    && binding.incarnation.to_string() == key.incarnation
            })
        {
            return Err(Error::NotFound);
        }
        let digest = key
            .recovery_scope
            .strip_prefix("recovery:sha256:")
            .ok_or(Error::NotFound)?;
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(Error::NotFound);
        }
        Ok(Self {
            kind: RecoveryScopeKind::OriginalCaller,
            scope: key.recovery_scope.clone(),
        })
    }
}
