use super::{
    super::{observation::Work, persistence, DirectoryDeploymentRepository, PublishedCatalog},
    PreparedTriggerOperation,
};
use crate::http_routes::{
    conflict, TriggerOperationAction, TriggerOperationCommit, TriggerRead, TriggerTargetIdentity,
};
use latent_artifacts::{ReleaseUseEligibility, ReleaseUseRecheck};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use std::sync::Arc;

impl DirectoryDeploymentRepository {
    pub fn commit_trigger_operation(
        &self,
        prepared: PreparedTriggerOperation,
    ) -> Result<TriggerRead<TriggerOperationCommit>, PlatformError> {
        if !Arc::ptr_eq(&prepared.owner, &self.rollout_work) {
            return Err(super::super::error(
                PlatformErrorCode::PermissionDenied,
                "http-trigger-owner-mismatch",
            ));
        }
        let durability = if prepared.replayed {
            let _writer = self.writer.lock().map_err(|_| super::unavailable())?;
            let current = self.read_publication();
            if !current.confirmed {
                return Err(super::unavailable());
            }
            if current
                .http
                .find(&prepared.receipt.tenant, &prepared.receipt.operation_id)
                != Some(&prepared.receipt)
            {
                return Err(conflict());
            }
            Ok(())
        } else if prepared.receipt.action == TriggerOperationAction::Apply {
            let target = prepared.receipt.target_identity().ok_or_else(conflict)?;
            match target {
                TriggerTargetIdentity::Application {
                    publication,
                    component,
                    ..
                } => {
                    let eligibility = prepared
                        .previous
                        .routes
                        .eligibility_for(&component, Some(&publication.id))
                        .ok_or_else(conflict)?;
                    eligibility.authorize_tenant(&TenantId(prepared.receipt.tenant.clone()))?;
                    if let Some(owner) = &self.lifecycle {
                        eligibility.check_for_lifecycle(owner)?;
                    }
                    if let Some(authority) = &self.admission {
                        eligibility.check_for_authority(authority)?;
                    }
                    let mut outcome = None;
                    ReleaseUseEligibility::with_all_current(
                        std::slice::from_ref(eligibility),
                        &mut |checker| {
                            outcome = Some(self.commit_trigger_inner(&prepared, Some(checker))?);
                            Ok(())
                        },
                    )?;
                    outcome.ok_or_else(super::unavailable)?
                }
                TriggerTargetIdentity::StaticWeb { publication, .. } => {
                    let tenant = TenantId(prepared.receipt.tenant.clone());
                    if publication.scope.tenant() != Some(&tenant) {
                        return Err(conflict());
                    }
                    let selection = prepared.static_selection.as_ref().ok_or_else(conflict)?;
                    if selection.publication() != &publication {
                        return Err(conflict());
                    }
                    let mut outcome = None;
                    selection.with_current(&tenant, &mut |_checker| {
                        // WebSelection keeps the web lifecycle fence held for this
                        // synchronous durable acceptance boundary.
                        outcome = Some(self.commit_trigger_inner(&prepared, None)?);
                        Ok(())
                    })?;
                    outcome.ok_or_else(super::unavailable)?
                }
            }
        } else {
            // Removing stale/revoked targets is permitted; no release grant is created.
            self.commit_trigger_inner(&prepared, None)?
        };
        Ok(TriggerRead::new(
            TriggerOperationCommit {
                receipt: prepared.receipt,
                trigger: prepared.apply_result,
                replayed: prepared.replayed,
                durability,
            },
            prepared.reply,
        ))
    }
    fn commit_trigger_inner(
        &self,
        prepared: &PreparedTriggerOperation,
        checker: Option<&dyn ReleaseUseRecheck>,
    ) -> Result<Result<(), PlatformError>, PlatformError> {
        let _writer = self.writer.lock().map_err(|_| super::unavailable())?;
        let current = self.read_publication();
        if !current.confirmed {
            return Err(super::unavailable());
        }
        if current.transaction != prepared.previous.transaction
            || current.routes.generation != prepared.previous.routes.generation
            || current
                .http
                .find(&prepared.receipt.tenant, &prepared.receipt.operation_id)
                .is_some()
        {
            return Err(conflict());
        }
        persistence::stage(&self.root, &prepared.bytes, &mut Work::default())?;
        #[cfg(test)]
        if self
            .fail_before_rename
            .swap(false, std::sync::atomic::Ordering::SeqCst)
        {
            return Err(super::unavailable());
        }
        if let Some(checker) = checker {
            checker.check()?;
        }
        persistence::replace(&self.root)?;
        let durable = self.sync_parent();
        let currentness = checker.map_or(Ok(()), ReleaseUseRecheck::check);
        let next = PublishedCatalog {
            transaction: prepared.receipt.state_version,
            routes: Arc::clone(&current.routes),
            rollouts: Arc::clone(&current.rollouts),
            operations: Arc::clone(&current.operations),
            http: Arc::clone(&prepared.next),
            confirmed: durable.is_ok(),
        };
        let old = {
            let mut selected = self
                .current
                .write()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            std::mem::replace(&mut *selected, next)
        };
        drop(old);
        Ok(durable.and(currentness))
    }
}
