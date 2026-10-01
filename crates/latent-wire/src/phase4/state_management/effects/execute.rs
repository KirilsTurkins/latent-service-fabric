use super::{
    audit, c, capacity, contract, input, invalid, io_error, lookup, native, projection,
    protected_error, response, state_audit, state_authorization, unsupported, Access, Arc,
    AuthenticatedInvocationContext, EffectManagementAuthorization, Inner, Instant,
    ManagementDecision, NamespaceRead, Outcome, OwnedPhase4Response, PlatformError,
    StateManagementReservation,
};
use latent_effects::runtime::{RetainedEffectManagement, RetainedEffectManagementJob};

pub(super) async fn run(
    inner: Arc<Inner>,
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    namespace: state_authorization::Access,
    node: Arc<dyn ManagementDecision>,
    deadline: Instant,
    permit: Arc<dyn StateManagementReservation>,
) -> Result<OwnedPhase4Response, PlatformError> {
    let port = inner.dispatcher.clone().ok_or_else(unsupported)?;
    let access = Arc::new(Access::read(
        inner, namespace, &context, node, &request, deadline, permit,
    )?);
    access.before_lookup().map_err(native)?;
    let mut pending = audit::begin(&access, &context, &request).await?;
    let mut prepared = match lookup::prepare(Arc::clone(&access), request.clone()).await {
        Ok(value) => value,
        Err(error) => {
            let finish = pending.finish(
                latent_audit::AuditOperationResult::Rejected,
                latent_audit::AuditReason::Rejected,
                None,
                false,
            );
            let _ = state_audit::ack(finish).await;
            return Err(error);
        }
    };
    // Replay/read from coherent durable originals before action permission or
    // expiry checks. Current operator and data-read authority still fence it.
    if let Some(outcome) = replay(&request, &mut prepared) {
        let finish = audit::finish(pending, Ok(&outcome));
        return complete(access, prepared.namespace, &request, finish, outcome).await;
    }
    let planning = matches!(request, contract::Request::PlanEffectMutation(_));
    access.seal_action(&context, &request, planning)?;
    pending.started()?;
    let retained_bytes = u64::try_from(request.encoded_len())
        .ok()
        .and_then(|bytes| bytes.checked_mul(4))
        .and_then(|bytes| bytes.checked_add(65536))
        .ok_or_else(capacity)?;
    let retained = audit::Completion::new(pending);
    let authorization: Arc<dyn EffectManagementAuthorization> = access.clone();
    let job = if planning {
        port.plan_effect_retained(
            prepared.request,
            authorization,
            retained,
            retained_bytes,
            |outcome, retained| retained.finish(outcome),
        )
    } else {
        port.mutate_effect_retained(
            prepared.plan.ok_or_else(invalid)?,
            authorization,
            retained,
            retained_bytes,
            |outcome, retained| retained.finish(outcome),
        )
    }
    .map_err(native)?;
    let RetainedEffectManagement {
        outcome,
        namespace,
        mut retained,
        ..
    } = wait(job).await?;
    let finish = retained.finish.take().ok_or_else(invalid)?;
    match outcome {
        Ok(outcome) => {
            complete(
                access,
                namespace.ok_or_else(invalid)?,
                &request,
                finish,
                outcome,
            )
            .await
        }
        Err(error) => {
            let _ = state_audit::ack(finish).await;
            Err(native(error))
        }
    }
}
fn replay(request: &contract::Request, prepared: &mut lookup::Prepared) -> Option<Outcome> {
    match request {
        contract::Request::PlanEffectMutation(_) => {
            prepared.plan.take().map(|plan| Outcome::Plan {
                plan,
                replayed: true,
            })
        }
        contract::Request::MutateState(_) => {
            prepared.receipt.take().map(|receipt| Outcome::Mutation {
                receipt,
                replayed: true,
            })
        }
        contract::Request::GetStateOperationReceipt(_) => {
            Some(Outcome::Receipt(prepared.receipt.take()))
        }
        _ => None,
    }
}
async fn wait(
    job: RetainedEffectManagementJob<audit::Completion>,
) -> Result<RetainedEffectManagement<audit::Completion>, PlatformError> {
    job.await.map_err(io_error)?.map_err(protected_error)
}
async fn complete(
    access: Arc<Access>,
    namespace: NamespaceRead,
    request: &contract::Request,
    finish: state_audit::Finish,
    outcome: Outcome,
) -> Result<OwnedPhase4Response, PlatformError> {
    let original = input::original(request)?;
    let ack = state_audit::ack(finish).await;
    let response = match outcome {
        Outcome::Plan { plan, replayed } => c::PlanEffectMutationResponse {
            plan: Some(projection::plan(&plan, original)?),
            replayed,
            audit_ack: Some(ack),
        }
        .into(),
        Outcome::Mutation { receipt, replayed } => c::MutateStateResponse {
            receipt: Some(projection::receipt(&receipt, original)?),
            replayed,
            audit_ack: Some(ack),
        }
        .into(),
        Outcome::Receipt(receipt) => c::GetStateOperationReceiptResponse {
            receipt: receipt
                .as_ref()
                .map(|receipt| projection::receipt(receipt, original))
                .transpose()?,
            namespace_receipt: None,
            audit_ack: Some(ack),
        }
        .into(),
    };
    response::owned(access, namespace, response)
}
