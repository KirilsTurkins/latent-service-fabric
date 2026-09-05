impl InvocationRuntime for FakeRuntime {
    fn invoke<'a>(
        &'a self,
        command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'a, Result<InvocationResponse, PlatformError>> {
        let activation_id = self.assigned_activation_id(&command);
        let receipt = self.receipt(activation_id.clone());
        let owner = command.principal.tenant.clone();
        {
            let mut state = lock(&self.state);
            state.owners.insert(activation_id.clone(), owner);
            state
                .tokens
                .insert(activation_id.clone(), cancellation.clone());
            state.invocations.push(command);
        }
        self.registered.notify_waiters();
        self.registered.notify_one();

        Box::pin(async move {
            if self.pending.load(Ordering::Acquire)
                && !self.released.load(Ordering::Acquire)
            {
                let released = self.release.notified();
                if !self.released.load(Ordering::Acquire) {
                    tokio::select! {
                        () = released => {},
                        () = cancellation.cancelled() => {
                            return Err(platform_error(
                                PlatformErrorCode::Cancelled,
                                "fake runtime observed cancellation",
                            ));
                        },
                    }
                }
            }
            let response = InvocationResponse {
                receipt,
                outcome: lock(&self.outcome).clone(),
            };
            self.publish_terminal(&response);
            Ok(response)
        })
    }

    fn cancel<'a>(
        &'a self,
        command: CancellationCommand,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        Box::pin(async move {
            let disposition = *lock(&self.cancellation_disposition);
            let mut state = lock(&self.state);
            let Some(owner) = state.owners.get(&command.activation_id) else {
                return Ok(CancelDisposition::NotFound);
            };
            if !principal_owns(&command.principal, owner.as_ref()) {
                return Err(platform_error(
                    PlatformErrorCode::PermissionDenied,
                    "foreign activation cancellation was denied",
                ));
            }
            state.cancellations.push(command);
            Ok(disposition)
        })
    }

    fn get_activation<'a>(
        &'a self,
        query: StatusQuery,
    ) -> BoxFuture<'a, Result<Option<ActivationStatus>, PlatformError>> {
        Box::pin(async move {
            let state = lock(&self.state);
            let Some(owner) = state.owners.get(&query.activation_id) else {
                return Ok(None);
            };
            if !principal_owns(&query.principal, owner.as_ref()) {
                return Err(platform_error(
                    PlatformErrorCode::PermissionDenied,
                    "foreign activation status was denied",
                ));
            }
            Ok(state.statuses.get(&query.activation_id).cloned())
        })
    }
}
