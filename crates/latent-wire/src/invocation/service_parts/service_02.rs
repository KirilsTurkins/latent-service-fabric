impl Default for InvocationLimits {
    fn default() -> Self {
        Self {
            max_message_bytes: 4 * 1024 * 1024,
            max_payload_bytes: 2 * 1024 * 1024,
            max_metadata_entries: 64,
            max_metadata_bytes: 32 * 1024,
            max_string_bytes: 4 * 1024,
            max_id_bytes: 256,
            max_cancel_reason_bytes: 2 * 1024,
            max_timeout_millis: 5 * 60 * 1000,
            max_cpu_fuel: 10_000_000_000,
            max_memory_bytes: 1024 * 1024 * 1024,
            max_child_calls: 10_000,
            max_outbound_requests: 10_000,
            max_state_read_bytes: 1024 * 1024 * 1024,
            max_state_write_bytes: 1024 * 1024 * 1024,
            max_blob_read_bytes: 4 * 1024 * 1024 * 1024,
            max_blob_write_bytes: 4 * 1024 * 1024 * 1024,
            max_log_bytes: 64 * 1024 * 1024,
            max_effect_count: 100_000,
            max_platform_error_details: 16,
            max_platform_error_fields: 32,
            max_platform_error_message_bytes: 2 * 1024,
        }
    }
}

/// Listener-independent implementation of the generated invocation service.
pub struct InvocationServiceAdapter<R, C = SystemClock, P = LocalPrincipalPolicy> {
    runtime: Arc<R>,
    limits: InvocationLimits,
    clock: Arc<C>,
    principals: Arc<P>,
}

impl<R, C, P> Clone for InvocationServiceAdapter<R, C, P> {
    fn clone(&self) -> Self {
        Self {
            runtime: Arc::clone(&self.runtime),
            limits: self.limits.clone(),
            clock: Arc::clone(&self.clock),
            principals: Arc::clone(&self.principals),
        }
    }
}

impl<R> InvocationServiceAdapter<R> {
    #[must_use]
    pub fn new(runtime: Arc<R>, limits: InvocationLimits) -> Self {
        Self {
            runtime,
            limits,
            clock: Arc::new(SystemClock),
            principals: Arc::new(LocalPrincipalPolicy),
        }
    }
}

impl<R, C, P> InvocationServiceAdapter<R, C, P> {
    #[must_use]
    pub fn with_components(
        runtime: Arc<R>,
        limits: InvocationLimits,
        clock: Arc<C>,
        principals: Arc<P>,
    ) -> Self {
        Self {
            runtime,
            limits,
            clock,
            principals,
        }
    }

    #[must_use]
    pub fn limits(&self) -> &InvocationLimits {
        &self.limits
    }

    /// Wraps the adapter in the generated Tonic server and applies symmetric
    /// encoded request/response limits.
    #[must_use]
    pub fn into_server(self) -> InvocationServiceServer<Self> {
        let max_message_bytes = self.limits.max_message_bytes;
        InvocationServiceServer::new(self)
            .max_decoding_message_size(max_message_bytes)
            .max_encoding_message_size(max_message_bytes)
    }
}

#[tonic::async_trait]
impl<R, C, P> InvocationService for InvocationServiceAdapter<R, C, P>
where
    R: InvocationRuntime + 'static,
    C: Clock + 'static,
    P: PrincipalPolicy + 'static,
{
    async fn invoke(
        &self,
        request: Request<proto::InvokeRequest>,
    ) -> Result<Response<proto::InvokeResponse>, Status> {
        let context = authenticated_context(&request)?;
        self.principals
            .authenticate(context.principal())
            .map_err(platform_status)?;

        let now_unix_millis = self.clock.now_unix_millis();
        let deadline = validation::deadline_plan(
            &request,
            context.transport_deadline_unix_millis(),
            now_unix_millis,
            &self.limits,
        )?;
        let command = validation::validate_invoke(
            request.into_inner(),
            context.principal().clone(),
            deadline.effective_unix_millis,
            &self.limits,
            self.principals.as_ref(),
        )?;

        let cancellation = InvocationCancellation::new();
        let mut guard = CancellationOnDrop::new(cancellation.clone());
        let invocation = self.runtime.invoke(command, cancellation.clone());
        let result = if let Some(delay) = deadline.delay {
            tokio::select! {
                biased;
                result = invocation => result,
                () = tokio::time::sleep(delay) => {
                    cancellation.cancel();
                    guard.disarm();
                    return Err(Status::deadline_exceeded(
                        "the invocation deadline was exceeded",
                    ));
                }
            }
        } else {
            invocation.await
        };
        guard.disarm();

        let response = result.map_err(platform_status)?;
        validation::validate_runtime_response(&response, &self.limits)?;
        let response = conversion::public_invocation_response_to_proto(response, &self.limits);
        ensure_encoded_size(&response, self.limits.max_message_bytes, "invocation response")?;
        Ok(Response::new(response))
    }

    async fn cancel(
        &self,
        request: Request<proto::CancelRequest>,
    ) -> Result<Response<proto::CancelResponse>, Status> {
        let context = authenticated_context(&request)?;
        self.principals
            .authenticate(context.principal())
            .map_err(platform_status)?;
        let request = validation::validate_cancel(request.into_inner(), &self.limits)?;
        let disposition = self
            .runtime
            .cancel(CancellationCommand {
                principal: context.principal().clone(),
                activation_id: ActivationId(request.activation_id),
                reason: request.reason,
            })
            .await
            .map_err(platform_status)?;
        let response = cancel_disposition_to_proto(disposition);
        ensure_encoded_size(&response, self.limits.max_message_bytes, "cancel response")?;
        Ok(Response::new(response))
    }

    async fn get_activation(
        &self,
        request: Request<proto::GetActivationRequest>,
    ) -> Result<Response<proto::ActivationStatus>, Status> {
        let context = authenticated_context(&request)?;
        self.principals
            .authenticate(context.principal())
            .map_err(platform_status)?;
        let activation_id = validation::validate_status_query(request.into_inner(), &self.limits)?;
        let status = self
            .runtime
            .get_activation(StatusQuery {
                principal: context.principal().clone(),
                activation_id: activation_id.clone(),
            })
            .await
            .map_err(platform_status)?
            .ok_or_else(|| Status::not_found("the requested activation was not found"))?;
        validation::validate_runtime_status(&status, &activation_id, &self.limits)?;
        let response = conversion::public_activation_status_to_proto(status, &self.limits);
        ensure_encoded_size(&response, self.limits.max_message_bytes, "activation status")?;
        Ok(Response::new(response))
    }
}

struct CancellationOnDrop {
    cancellation: InvocationCancellation,
    armed: bool,
}

impl CancellationOnDrop {
    fn new(cancellation: InvocationCancellation) -> Self {
        Self {
            cancellation,
            armed: true,
        }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for CancellationOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.cancellation.cancel();
        }
    }
}

fn authenticated_context<T>(
    request: &Request<T>,
) -> Result<AuthenticatedInvocationContext, Status> {
    request
        .extensions()
        .get::<AuthenticatedInvocationContext>()
        .cloned()
        .ok_or_else(|| Status::unauthenticated("authentication is required"))
}

fn ensure_encoded_size<M: Message>(
    message: &M,
    maximum: usize,
    description: &str,
) -> Result<(), Status> {
    if message.encoded_len() > maximum {
        Err(Status::resource_exhausted(format!(
            "{description} exceeds the configured message limit"
        )))
    } else {
        Ok(())
    }
}

fn platform_status(error: PlatformError) -> Status {
    Status::new(tonic_code(error.code), public_platform_message(error.code))
}