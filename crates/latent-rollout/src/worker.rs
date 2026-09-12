mod mutation;
mod size;

use crate::{
    coordinator::{RequestCharge, Shared},
    ticket::{Completion, Control},
    MutationPreview, MutationResult, OwnedResponse, ResponseLease, Result, RolloutFailure,
};
use latent_audit::AuditHandle;
use latent_control_store::{
    rollouts::{
        RolloutId, RolloutOperationLookup, RolloutPage, RolloutPageRequest, RolloutRequest,
        RolloutStatus,
    },
    DirectoryDeploymentRepository,
};
use latent_core::TenantId;
use std::{
    sync::{atomic::Ordering, Arc},
    time::{Duration, Instant},
};
use tokio::sync::{mpsc, oneshot};

pub(crate) type Preflight = Box<dyn for<'a> FnOnce(MutationPreview<'a>) -> Result<()> + Send>;
pub(crate) struct MutationInput {
    pub request: RolloutRequest,
    pub preflight: Preflight,
}
pub(crate) struct Job<I, O> {
    pub input: Option<I>,
    pub reply: Option<oneshot::Sender<Completion<O>>>,
    pub control: Arc<Control>,
    pub expires: Instant,
    pub maximum: usize,
    pub lease: Option<ResponseLease>,
    // Input, queued reply and response ownership are released before this charge.
    pub charge: RequestCharge,
}
pub(crate) enum Command {
    Mutation(Box<Job<MutationInput, MutationResult>>),
    Get(Job<(TenantId, RolloutId), Option<RolloutStatus>>),
    List(Job<RolloutPageRequest, RolloutPage>),
    Operation(Job<(TenantId, RolloutId, String), RolloutOperationLookup>),
}
impl<I, O> Job<I, O> {
    fn check(&self, shared: &Shared) -> Result<()> {
        if shared.closed.load(Ordering::Acquire) {
            return Err(crate::closed());
        }
        self.control.check(self.expires)
    }
    fn finish(mut self, result: Result<O>) {
        self.control.done();
        let result = result
            .map(|value| OwnedResponse {
                value,
                lease: self.lease.take().expect("reserved reply allowance"),
            })
            .map_err(|error| RolloutFailure::new(error, self.control.ack()));
        if let Some(reply) = self.reply.take() {
            let _ = reply.send(result);
        }
    }
}

pub(crate) async fn run(
    repository: Arc<DirectoryDeploymentRepository>,
    audit: AuditHandle,
    mut receiver: mpsc::Receiver<Command>,
    shared: Arc<Shared>,
    startup: oneshot::Sender<Result<()>>,
) {
    let ready = crate::reconcile_rollout_audit(
        &audit,
        &repository,
        Instant::now() + Duration::from_secs(10),
    )
    .await;
    if ready.is_err() {
        shared.failed.store(true, Ordering::Release);
        shared.closed.store(true, Ordering::Release);
        receiver.close();
    } else {
        shared.started.store(true, Ordering::Release);
    }
    let _ = startup.send(ready.map_err(crate::bounded));
    while let Some(command) = receiver.recv().await {
        match command {
            Command::Mutation(job) => mutation::run(&repository, &audit, &shared, *job).await,
            Command::Get(mut job) => {
                job.charge.activate();
                let result = (|| {
                    job.check(&shared)?;
                    let (tenant, id) = job.input.take().expect("owned query");
                    let result = repository.get_rollout(&tenant, &id)?;
                    size::check(&result, job.maximum)?;
                    job.check(&shared)?;
                    Ok(result)
                })();
                job.finish(result);
            }
            Command::List(mut job) => {
                job.charge.activate();
                let result = (|| {
                    job.check(&shared)?;
                    let result =
                        repository.list_rollouts(job.input.take().expect("owned query"))?;
                    size::check(
                        &(&result.rollouts, &result.next_cursor, result.state_version),
                        job.maximum,
                    )?;
                    job.check(&shared)?;
                    Ok(result)
                })();
                job.finish(result);
            }
            Command::Operation(mut job) => {
                job.charge.activate();
                let result = (|| {
                    job.check(&shared)?;
                    let (tenant, id, operation) = job.input.take().expect("owned query");
                    let result = repository.get_rollout_operation(&tenant, &id, &operation)?;
                    match &result {
                        RolloutOperationLookup::Found(receipt) => {
                            size::check(receipt, job.maximum)?;
                        }
                        _ => size::check(&"uncertain", job.maximum)?,
                    }
                    job.check(&shared)?;
                    Ok(result)
                })();
                job.finish(result);
            }
        }
    }
}
