fn principal_owns(principal: &InvocationPrincipal, owner: Option<&TenantId>) -> bool {
    principal.kind == PrincipalKind::Administrator || principal.tenant.as_ref() == owner
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

fn platform_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn principal(tenant: &str) -> InvocationPrincipal {
    InvocationPrincipal {
        subject: format!("user-{tenant}"),
        kind: PrincipalKind::User,
        tenant: Some(TenantId(tenant.to_owned())),
        service: None,
        claims: Metadata::from([("role".to_owned(), "developer".to_owned())]),
    }
}

fn authenticated<T>(tenant: &str, message: T) -> tonic::Request<T> {
    AuthenticatedInvocationContext::new(principal(tenant)).request(message)
}

fn budget() -> proto::ResourceBudget {
    proto::ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 1_024,
        child_calls: 2,
        outbound_requests: 3,
        state_read_bytes: 4,
        state_write_bytes: 5,
        blob_read_bytes: 6,
        blob_write_bytes: 7,
        log_bytes: 8,
        effect_count: 9,
        wall_time_limit_millis: Some(500),
    }
}

fn request() -> proto::InvokeRequest {
    proto::InvokeRequest {
        activation_id: None,
        parent_activation_id: None,
        root_activation_id: None,
        target: Some(proto::InvocationTarget {
            tenant: "tenant-a".to_owned(),
            service: "echo".to_owned(),
            contract: "examples:echo/api@0.1.0".to_owned(),
            function: "echo".to_owned(),
            route: Some("stable".to_owned()),
        }),
        payload: b"hello".to_vec(),
        media_type: "text/plain".to_owned(),
        deadline_unix_millis: Some(1_500),
        priority: 7,
        idempotency_key: Some("idempotency-1".to_owned()),
        budget: Some(budget()),
        metadata: HashMap::from([("request".to_owned(), "test".to_owned())]),
    }
}

fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 11,
        peak_memory_bytes: 12,
        wall_time_micros: 13,
        child_calls: 14,
        outbound_requests: 15,
        state_read_bytes: 16,
        state_write_bytes: 17,
        blob_read_bytes: 18,
        blob_write_bytes: 19,
        log_bytes: 20,
        effect_count: 21,
    }
}

fn success() -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: b"hello".to_vec(),
        output_media_type: "text/plain".to_owned(),
        consumption: consumption(),
        committed_state_version: Some("state-v1".to_owned()),
        effect_ids: vec!["effect-1".to_owned()],
        metadata: Metadata::from([("guest".to_owned(), "ok".to_owned())]),
    })
}

fn declared_error() -> ActivationOutcome {
    ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "invalid-name".to_owned(),
            message: "name is required".to_owned(),
            payload: br#"{"field":"name"}"#.to_vec(),
            media_type: "application/json".to_owned(),
            metadata: Metadata::from([("field".to_owned(), "name".to_owned())]),
        },
        consumption: consumption(),
    }
}

fn response(outcome: ActivationOutcome) -> InvocationResponse {
    InvocationResponse {
        receipt: InvocationReceipt {
            activation_id: ActivationId("activation-roundtrip".to_owned()),
            revision_id: RevisionId("revision-1".to_owned()),
            release_digest: ReleaseDigest(
                "sha256:1111111111111111111111111111111111111111111111111111111111111111"
                    .to_owned(),
            ),
            route_generation: RouteGeneration(42),
        },
        outcome,
    }
}

fn domain_request() -> InvocationRequest {
    InvocationRequest {
        requested_activation_id: Some(ActivationId("activation-requested".to_owned())),
        parent_activation_id: Some(ActivationId("activation-parent".to_owned())),
        root_activation_id: Some(ActivationId("activation-root".to_owned())),
        target: InvocationTarget {
            tenant: TenantId("tenant-a".to_owned()),
            service: ServiceId("echo".to_owned()),
            contract: ContractId("examples:echo/api@0.1.0".to_owned()),
            function: FunctionId("echo".to_owned()),
            route: Some("stable".to_owned()),
        },
        payload: b"hello".to_vec(),
        media_type: "text/plain".to_owned(),
        deadline_unix_millis: Some(1_500),
        priority: 7,
        idempotency_key: Some(latent_core::IdempotencyKey("idempotency-1".to_owned())),
        budget: budget_from_proto(budget()),
        metadata: Metadata::from([("request".to_owned(), "test".to_owned())]),
    }
}

fn adapter(
    runtime: Arc<FakeRuntime>,
    limits: InvocationLimits,
) -> InvocationServiceAdapter<FakeRuntime, FixedClock, LocalPrincipalPolicy> {
    InvocationServiceAdapter::with_components(
        runtime,
        limits,
        Arc::new(FixedClock(1_000)),
        Arc::new(LocalPrincipalPolicy),
    )
}
