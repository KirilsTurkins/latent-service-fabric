use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_optimization_workloads::{invoke, MEDIA_TYPE};
use latent_rpc::invocation::v1::{self as proto, invocation_service_server::InvocationService};
use tokio::sync::Semaphore;
use tonic::{Request, Response, Status};

use super::{command::Args, validation};

const REFERENCE_PIN: &str = "native-reference-v1";

#[derive(Clone)]
pub(super) struct NativeService {
    token: Arc<str>,
    tenant: Arc<str>,
    services: Arc<[String]>,
    capacity: Arc<Semaphore>,
    timeout: Duration,
    next_id: Arc<AtomicU64>,
}

impl NativeService {
    pub(super) fn new(args: &Args) -> Self {
        Self {
            token: Arc::from(args.token.as_str()),
            tenant: Arc::from(args.tenant.as_str()),
            services: Arc::from(args.services.clone()),
            capacity: Arc::new(Semaphore::new(args.concurrency)),
            timeout: Duration::from_millis(args.timeout_ms),
            next_id: Arc::new(AtomicU64::new(0)),
        }
    }

    #[cfg(test)]
    pub(super) fn hold_capacity(&self) -> tokio::sync::OwnedSemaphorePermit {
        Arc::clone(&self.capacity).try_acquire_owned().unwrap()
    }
}

#[tonic::async_trait]
impl InvocationService for NativeService {
    async fn invoke(
        &self,
        request: Request<proto::InvokeRequest>,
    ) -> Result<Response<proto::InvokeResponse>, Status> {
        let started = Instant::now();
        let unix_millis = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| Status::internal("native reference clock unavailable"))?
                .as_millis(),
        )
        .map_err(|_| Status::internal("native reference clock unavailable"))?;
        validation::authenticate(&request, &self.token)?;
        validation::request(request.get_ref(), &self.tenant, &self.services)?;
        let deadline = validation::deadline(&request, started, unix_millis, self.timeout)?;
        let request = request.into_inner();
        let id = match request.activation_id {
            Some(id) => id,
            None => {
                let serial = self
                    .next_id
                    .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                        value.checked_add(1)
                    })
                    .map_err(|_| {
                        Status::resource_exhausted("native reference identity exhausted")
                    })?;
                format!("native-activation-{serial}")
            }
        };
        if Instant::now() >= deadline {
            return Ok(Response::new(failure(
                id,
                started,
                "deadline-exceeded",
                "native reference deadline exceeded",
                false,
            )));
        }
        let Ok(_permit) = Arc::clone(&self.capacity).try_acquire_owned() else {
            return Ok(Response::new(failure(
                id,
                started,
                "unavailable",
                "native reference concurrency is full",
                true,
            )));
        };
        let function = &request.target.as_ref().expect("validated target").function;
        // One finitely bounded synchronous call. The response is checked again
        // against the original monotonic deadline; native work is not preempted.
        let result = invoke(function, &request.payload);
        Ok(Response::new(completed(
            id,
            started,
            deadline,
            Instant::now(),
            result,
        )))
    }

    async fn cancel(
        &self,
        request: Request<proto::CancelRequest>,
    ) -> Result<Response<proto::CancelResponse>, Status> {
        validation::authenticate(&request, &self.token)?;
        Err(Status::unimplemented(
            "native reference has no cancellation registry",
        ))
    }

    async fn get_activation(
        &self,
        request: Request<proto::GetActivationRequest>,
    ) -> Result<Response<proto::ActivationStatus>, Status> {
        validation::authenticate(&request, &self.token)?;
        Err(Status::unimplemented(
            "native reference has no activation journal",
        ))
    }
}

pub(super) fn completed(
    id: String,
    started: Instant,
    deadline: Instant,
    finished: Instant,
    result: Result<Vec<u8>, String>,
) -> proto::InvokeResponse {
    if finished >= deadline {
        return failure(
            id,
            started,
            "deadline-exceeded",
            "native reference deadline exceeded",
            false,
        );
    }
    match result {
        Ok(payload) => response(
            id,
            started,
            proto::invoke_response::Result::Success(proto::Success {
                payload,
                media_type: MEDIA_TYPE.to_owned(),
                ..proto::Success::default()
            }),
        ),
        Err(_) => failure(
            id,
            started,
            "invalid-argument",
            "native reference workload rejected",
            false,
        ),
    }
}

fn failure(
    id: String,
    started: Instant,
    code: &str,
    message: &str,
    retryable: bool,
) -> proto::InvokeResponse {
    response(
        id,
        started,
        proto::invoke_response::Result::PlatformFailure(proto::PlatformError {
            code: code.to_owned(),
            message: message.to_owned(),
            retryable,
            detail_items: Vec::new(),
        }),
    )
}

fn response(
    id: String,
    started: Instant,
    result: proto::invoke_response::Result,
) -> proto::InvokeResponse {
    proto::InvokeResponse {
        activation_id: id,
        revision_id: REFERENCE_PIN.to_owned(),
        release_digest: REFERENCE_PIN.to_owned(),
        route_generation: 1,
        result: Some(result),
        consumption: Some(proto::BudgetConsumption {
            wall_time_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
            // Native reference has no Wasm fuel meter or guest-memory limiter.
            // These protobuf zeros represent unavailable measurements, never
            // evidence that native work consumes no CPU or memory.
            ..proto::BudgetConsumption::default()
        }),
    }
}
