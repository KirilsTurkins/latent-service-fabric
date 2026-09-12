use super::super::{
    observation::Work, persistence, DirectoryDeploymentRepository, PublishedCatalog,
};
use super::{prepare, PreparedRolloutMutation};
use crate::rollouts::{conflict, error, Result, RolloutCommitResult};
use latent_artifacts::ReleaseUseRecheck;
use latent_core::PlatformErrorCode;
use std::sync::Arc;
impl DirectoryDeploymentRepository {
    #[expect(
        clippy::needless_pass_by_value,
        reason = "consume the affine prepared owner and release its permits on every exit"
    )]
    pub fn commit_rollout(&self, prepared: PreparedRolloutMutation) -> Result<RolloutCommitResult> {
        if !Arc::ptr_eq(&prepared.owner, &self.rollout_work) {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "rollout-preparation-owner-mismatch",
            ));
        }
        if prepared.replayed {
            let _writer = self
                .writer
                .lock()
                .map_err(|_| error(PlatformErrorCode::Unavailable, "rollout-owner-unavailable"))?;
            let current = self.read_publication();
            if !current.confirmed {
                return Err(error(
                    PlatformErrorCode::Unavailable,
                    "rollout-durability-uncertain",
                ));
            }
            let actual = current
                .rollouts
                .receipt(
                    &prepared.receipt.tenant,
                    &prepared.receipt.rollout_id,
                    &prepared.receipt.operation_id,
                )
                .ok_or_else(conflict)?;
            if actual != &prepared.receipt || actual.request_digest != prepared.request_digest {
                return Err(conflict());
            }
            return Ok(RolloutCommitResult {
                receipt: actual.clone(),
                replayed: true,
                durability: Ok(()),
            });
        }
        if prepared.state_only {
            return self.commit_rollout_inner(&prepared, None);
        }
        prepared
            .next_routes
            .check_admission_mode(self.admission.as_ref(), self.lifecycle.as_ref())?;
        let mut output = None;
        prepared
            .next_routes
            .with_current_admission(&mut |checker| {
                output = Some(self.commit_rollout_inner(&prepared, checker)?);
                Ok(())
            })?;
        output.ok_or_else(|| error(PlatformErrorCode::Internal, "rollout-commit-missing"))
    }
    fn commit_rollout_inner(
        &self,
        prepared: &PreparedRolloutMutation,
        checker: Option<&dyn ReleaseUseRecheck>,
    ) -> Result<RolloutCommitResult> {
        let _writer = self
            .writer
            .lock()
            .map_err(|_| error(PlatformErrorCode::Unavailable, "rollout-owner-unavailable"))?;
        let current = self.read_publication();
        if current.transaction != prepared.previous.transaction
            || current.routes.generation != prepared.previous.routes.generation
        {
            return Err(conflict());
        }
        let receipt = &prepared.receipt;
        let old = current.rollouts.row(&receipt.tenant, &receipt.rollout_id);
        if old.map_or(0, |r| r.status.revision) != receipt.expected_revision {
            return Err(conflict());
        }
        if prepared.state_only {
            if !Arc::ptr_eq(&prepared.next_routes, &current.routes) {
                return Err(conflict());
            }
        } else {
            let row = prepared
                .next_table
                .row(&receipt.tenant, &receipt.rollout_id)
                .ok_or_else(conflict)?;
            let actual = prepare::cohort(&current.routes, &receipt.tenant, &row.status.service)?;
            let expected = prepare::cohort(
                &prepared.previous.routes,
                &receipt.tenant,
                &row.status.service,
            )?;
            if actual != expected {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "rollout-cohort-conflict",
                ));
            }
        }
        persistence::stage(&self.root, &prepared.bytes, &mut Work::default())?;
        #[cfg(test)]
        if self
            .fail_before_rename
            .swap(false, std::sync::atomic::Ordering::SeqCst)
        {
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
            transaction: receipt.state_version,
            routes: Arc::clone(&prepared.next_routes),
            rollouts: Arc::clone(&prepared.next_table),
            confirmed: durable.is_ok(),
        };
        let old = {
            let mut selected = self
                .current
                .write()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let old = std::mem::replace(&mut *selected, next);
            self.generation.store(
                receipt.route_generation.0,
                std::sync::atomic::Ordering::Release,
            );
            old
        };
        drop(old);
        Ok(RolloutCommitResult {
            receipt: receipt.clone(),
            replayed: false,
            durability: durable.and(currentness),
        })
    }
    pub fn confirm_rollout_durability(&self) -> Result<()> {
        let _writer = self
            .writer
            .lock()
            .map_err(|_| error(PlatformErrorCode::Unavailable, "rollout-owner-unavailable"))?;
        self.sync_parent()?;
        self.current
            .write()
            .map_err(|_| error(PlatformErrorCode::Unavailable, "rollout-owner-unavailable"))?
            .confirmed = true;
        Ok(())
    }
}
