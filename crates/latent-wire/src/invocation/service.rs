use super::{
    authentication, conversion, deadline, platform_status, proto, validation, CancellationCommand,
    InvocationCancellation, InvocationLimits, InvocationResponse, InvocationRuntime,
    InvocationService, InvocationServiceServer, InvocationTraceSource, LocalPrincipalPolicy,
    PrincipalPolicy, StatusQuery, SystemInvocationTraceSource,
};
use latent_core::{ActivationClock, BoxFuture, PlatformError, SystemActivationClock};
use prost::Message;
use std::sync::Arc;
use tonic::{Request, Response, Status};

#[derive(Clone)]
pub struct InvocationServiceServices {
    pub clock: Arc<dyn ActivationClock>,
    pub principals: Arc<dyn PrincipalPolicy>,
    pub traces: Arc<dyn InvocationTraceSource>,
}
impl Default for InvocationServiceServices {
    fn default() -> Self {
        Self {
            clock: Arc::new(SystemActivationClock),
            principals: Arc::new(LocalPrincipalPolicy),
            traces: Arc::new(SystemInvocationTraceSource::default()),
        }
    }
}

/// Listener-independent server adapter. Clones share the same lifecycle runtime
/// and identity/clock services; they create no worker or per-service listener.
pub struct InvocationServiceAdapter<R: ?Sized> {
    runtime: Arc<R>,
    limits: InvocationLimits,
    services: InvocationServiceServices,
}
impl<R: ?Sized> Clone for InvocationServiceAdapter<R> {
    fn clone(&self) -> Self {
        Self {
            runtime: Arc::clone(&self.runtime),
            limits: self.limits.clone(),
            services: self.services.clone(),
        }
    }
}
impl<R: InvocationRuntime + ?Sized + 'static> InvocationServiceAdapter<R> {
    pub fn new(runtime: Arc<R>, limits: InvocationLimits) -> Result<Self, PlatformError> {
        Self::with_services(runtime, limits, InvocationServiceServices::default())
    }
    pub fn with_services(
        runtime: Arc<R>,
        limits: InvocationLimits,
        services: InvocationServiceServices,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            runtime,
            limits,
            services,
        })
    }
    #[must_use]
    pub fn limits(&self) -> &InvocationLimits {
        &self.limits
    }
    #[must_use]
    pub fn into_server(self) -> InvocationServiceServer<Self> {
        let maximum = self.limits.max_message_bytes;
        InvocationServiceServer::new(self)
            .max_decoding_message_size(maximum)
            .max_encoding_message_size(maximum)
    }
}

#[tonic::async_trait]
impl<R: InvocationRuntime + ?Sized + 'static> InvocationService for InvocationServiceAdapter<R> {
    async fn invoke(
        &self,
        mut request: Request<proto::InvokeRequest>,
    ) -> Result<Response<proto::InvokeResponse>, Status> {
        let context = authentication::take_context(
            &mut request,
            &self.limits,
            self.services.principals.as_ref(),
        )?;
        let sample = self.services.clock.sample();
        if let (Some(observer), Some(token)) = (
            self.services.clock.deadline_diagnostic_observer(),
            context.deadline_diagnostic_token(),
        ) {
            if let Some(id) = request.get_ref().activation_id.as_deref() {
                let _ = observer.bind(token, id);
            }
            observer.record(
                token,
                latent_core::DeadlineDiagnosticObservation::BodyDecoded {
                    observed_at: sample.monotonic(),
                    request_deadline_unix_millis: request.get_ref().deadline_unix_millis,
                    request_wall_time_limit_millis: request
                        .get_ref()
                        .budget
                        .as_ref()
                        .and_then(|budget| budget.wall_time_limit_millis),
                },
            );
        }
        let deadline = deadline::plan(
            &request,
            context.transport_deadline_unix_millis(),
            context.transport_expires_at(),
            sample,
            &self.limits,
        )?;
        let trace = self.services.traces.next_trace().map_err(platform_status)?;
        authentication::validate_trace(&trace, &self.limits)
            .map_err(|_| Status::internal("invalid invocation trace context"))?;
        let command = validation::validate_invoke(
            request.into_inner(),
            context.into_principal(),
            trace,
            deadline.effective_unix_millis,
            &self.limits,
            self.services.principals.as_ref(),
        )?;
        if deadline
            .expires_at
            .is_some_and(|expiry| self.services.clock.monotonic_now() >= expiry)
        {
            return Err(Status::deadline_exceeded(
                "the invocation deadline has expired",
            ));
        }
        let cancellation = InvocationCancellation::new();
        // Keep the owner outside select: Tokio destroys moved branch futures
        // before invoking a handler, which would lose the deadline drop cause.
        let mut invocation = PendingInvocation {
            future: Some(self.runtime.invoke(command, cancellation.clone())),
            cancellation,
            armed: true,
        };
        let result = if let Some(expires_at) = deadline.expires_at {
            let delay = expires_at.saturating_duration_since(self.services.clock.monotonic_now());
            if delay.is_zero() {
                return Err(invocation.expire());
            }
            tokio::select! {
                biased;
                result = invocation.future.as_mut().expect("owned invocation").as_mut() => result,
                () = tokio::time::sleep(delay) => {
                    return Err(invocation.expire());
                }
            }
        } else {
            invocation
                .future
                .as_mut()
                .expect("owned invocation")
                .as_mut()
                .await
        };
        invocation.armed = false;
        drop(invocation);
        let response = result.map_err(platform_status)?;
        validation::validate_runtime_response(&response, &self.limits)?;
        let response = conversion::public_invocation_response_to_proto(response, &self.limits);
        ensure_encoded_size(&response, self.limits.max_message_bytes)?;
        Ok(Response::new(response))
    }

    async fn cancel(
        &self,
        mut request: Request<proto::CancelRequest>,
    ) -> Result<Response<proto::CancelResponse>, Status> {
        let context = authentication::take_context(
            &mut request,
            &self.limits,
            self.services.principals.as_ref(),
        )?;
        let request = validation::validate_cancel(request.into_inner(), &self.limits)?;
        let disposition = self
            .runtime
            .cancel(CancellationCommand {
                principal: context.into_principal(),
                activation_id: latent_core::ActivationId(request.activation_id),
                reason: request.reason,
            })
            .await
            .map_err(platform_status)?;
        let response = super::cancel_disposition_to_proto(disposition);
        ensure_encoded_size(&response, self.limits.max_message_bytes)?;
        Ok(Response::new(response))
    }

    async fn get_activation(
        &self,
        mut request: Request<proto::GetActivationRequest>,
    ) -> Result<Response<proto::ActivationStatus>, Status> {
        let context = authentication::take_context(
            &mut request,
            &self.limits,
            self.services.principals.as_ref(),
        )?;
        let activation_id = validation::validate_status_query(request.into_inner(), &self.limits)?;
        let status = self
            .runtime
            .get_activation(StatusQuery {
                principal: context.into_principal(),
                activation_id: activation_id.clone(),
            })
            .await
            .map_err(platform_status)?
            .ok_or_else(|| Status::not_found("the requested activation was not found"))?;
        validation::validate_runtime_status(&status, &activation_id, &self.limits)?;
        let response = conversion::public_activation_status_to_proto(status, &self.limits);
        ensure_encoded_size(&response, self.limits.max_message_bytes)?;
        Ok(Response::new(response))
    }
}

struct PendingInvocation<'a> {
    future: Option<BoxFuture<'a, Result<InvocationResponse, PlatformError>>>,
    cancellation: InvocationCancellation,
    armed: bool,
}
impl PendingInvocation<'_> {
    fn expire(mut self) -> Status {
        self.cancellation.expire();
        self.armed = false;
        drop(self);
        Status::deadline_exceeded("the invocation deadline was exceeded")
    }
}
impl Drop for PendingInvocation<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.cancellation.cancel();
        }
        // A custom runtime also observes the interruption cause in its Drop.
        drop(self.future.take());
    }
}
fn ensure_encoded_size<M: Message>(value: &M, maximum: usize) -> Result<(), Status> {
    if value.encoded_len() > maximum {
        Err(Status::resource_exhausted(
            "RPC response exceeds the message limit",
        ))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests;
