use super::{prepare, PreparedDeploymentOperation};
use crate::{
    deployment_operations::{
        conflict, error, DeploymentOperationCommit, DeploymentOperationRead, Result,
    },
    deployments::{
        observation::Work, persistence, DirectoryDeploymentRepository, PublishedCatalog,
    },
};
use latent_artifacts::ReleaseUseRecheck;
use latent_core::PlatformErrorCode;
use std::sync::{atomic::Ordering, Arc};
impl DirectoryDeploymentRepository {
    pub fn commit_operation(
        &self,
        prepared: PreparedDeploymentOperation,
    ) -> Result<DeploymentOperationRead<DeploymentOperationCommit>> {
        if !Arc::ptr_eq(&prepared.owner, &self.rollout_work) {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "deployment-operation-owner-mismatch",
            ));
        }
        let durability = if prepared.replayed {
            let _writer = self.writer.lock().map_err(|_| {
                error(
                    PlatformErrorCode::Unavailable,
                    "deployment-owner-unavailable",
                )
            })?;
            let current = self.read_publication();
            if !current.confirmed {
                return Err(prepare::uncertain());
            }
            if current
                .operations
                .find(&prepared.receipt.tenant, &prepared.receipt.operation_id)
                != Some(&prepared.receipt)
            {
                return Err(conflict());
            }
            Ok(())
        } else {
            prepared
                .next_routes
                .check_admission_mode(self.admission.as_ref(), self.lifecycle.as_ref())?;
            let mut outcome = None;
            prepared
                .next_routes
                .with_current_admission(&mut |checker| {
                    outcome = Some(self.commit_operation_inner(&prepared, checker)?);
                    Ok(())
                })?;
            outcome.ok_or_else(|| {
                error(
                    PlatformErrorCode::Internal,
                    "deployment-operation-commit-missing",
                )
            })?
        };
        Ok(DeploymentOperationRead::new(
            DeploymentOperationCommit {
                receipt: prepared.receipt,
                deployment: prepared.apply_result,
                replayed: prepared.replayed,
                durability,
            },
            prepared.reply,
        ))
    }
    fn commit_operation_inner(
        &self,
        prepared: &PreparedDeploymentOperation,
        checker: Option<&dyn ReleaseUseRecheck>,
    ) -> Result<Result<()>> {
        let _writer = self.writer.lock().map_err(|_| {
            error(
                PlatformErrorCode::Unavailable,
                "deployment-owner-unavailable",
            )
        })?;
        let current = self.read_publication();
        if current.transaction != prepared.receipt.expected_state_version
            || current.transaction != prepared.previous.transaction
            || current.routes.generation != prepared.previous.routes.generation
        {
            return Err(prepare::state_conflict());
        }
        if !current.confirmed {
            return Err(prepare::uncertain());
        }
        prepare::check_precondition(
            &current.routes,
            &prepared.receipt.tenant,
            &prepared.receipt.deployment_id,
            prepared.receipt.expected_generation,
            prepared.apply_result.as_ref().map(|v| &v.manifest),
        )?;
        if current
            .operations
            .find(&prepared.receipt.tenant, &prepared.receipt.operation_id)
            .is_some()
        {
            return Err(conflict());
        }
        persistence::stage(&self.root, &prepared.bytes, &mut Work::default())?;
        #[cfg(test)]
        if self.fail_before_rename.swap(false, Ordering::SeqCst) {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "injected-before-rename",
            ));
        }
        if let Some(checker) = checker {
            checker.check()?;
        }
        persistence::replace(&self.root)?;
        let durable = self.sync_parent();
        let currentness = checker.map_or(Ok(()), ReleaseUseRecheck::check);
        let next = PublishedCatalog {
            transaction: prepared.receipt.state_version,
            routes: Arc::clone(&prepared.next_routes),
            rollouts: Arc::clone(&prepared.previous.rollouts),
            operations: Arc::clone(&prepared.next_operations),
            confirmed: durable.is_ok(),
        };
        let old = {
            let mut selected = self
                .current
                .write()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let old = std::mem::replace(&mut *selected, next);
            self.generation
                .store(prepared.receipt.route_generation.0, Ordering::Release);
            old
        };
        drop(old);
        Ok(durable.and(currentness))
    }
}
