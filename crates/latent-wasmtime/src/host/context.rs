use super::HostState;
use crate::bindings::latent::context::context;
use latent_core::PrincipalKind;
use std::time::Instant;
use wasmtime::component::{Access, HasSelf};
use wasmtime::AsContext;

impl context::Host for HostState {
    async fn activation_id(&mut self) -> wasmtime::Result<String> {
        let started = Instant::now();
        self.capabilities
            .context("activation-id", self.context.activation_id.0.len())?;
        let value = self.context.activation_id.0.clone();
        self.record_host_call(started);
        Ok(value)
    }

    async fn root_activation_id(&mut self) -> wasmtime::Result<String> {
        let started = Instant::now();
        self.capabilities.context(
            "root-activation-id",
            self.context.root_activation_id.0.len(),
        )?;
        let value = self.context.root_activation_id.0.clone();
        self.record_host_call(started);
        Ok(value)
    }

    async fn parent_activation_id(&mut self) -> wasmtime::Result<Option<String>> {
        let started = Instant::now();
        self.capabilities.context(
            "parent-activation-id",
            self.context
                .parent_activation_id
                .as_ref()
                .map_or(0, |id| id.0.len()),
        )?;
        let value = self
            .context
            .parent_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone());
        self.record_host_call(started);
        Ok(value)
    }

    async fn principal(&mut self) -> wasmtime::Result<context::InvocationPrincipal> {
        let started = Instant::now();
        self.capabilities.context(
            "principal",
            self.context.principal.subject.len()
                + 16
                + self
                    .context
                    .principal
                    .tenant
                    .as_ref()
                    .map_or(0, |t| t.0.len())
                + self
                    .context
                    .principal
                    .service
                    .as_ref()
                    .map_or(0, |s| s.0.len())
                + self
                    .context_policy
                    .claim_bytes(&self.context.principal.claims),
        )?;
        let value = context::InvocationPrincipal {
            subject: self.context.principal.subject.clone(),
            kind: principal_kind(self.context.principal.kind).to_owned(),
            tenant: self
                .context
                .principal
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.clone()),
            service: self
                .context
                .principal
                .service
                .as_ref()
                .map(|service| service.0.clone()),
            claims: self
                .context_policy
                .claim_pairs(&self.context.principal.claims),
        };
        self.record_host_call(started);
        Ok(value)
    }

    async fn trace(&mut self) -> wasmtime::Result<context::TraceContext> {
        let started = Instant::now();
        self.capabilities.context(
            "trace",
            self.context.trace_id.len()
                + self.context.span_id.len()
                + self.context_policy.baggage_bytes(&self.context.baggage),
        )?;
        let value = context::TraceContext {
            trace_id: self.context.trace_id.clone(),
            span_id: self.context.span_id.clone(),
            trace_flags: self.context.trace_flags,
            baggage: self.context_policy.baggage_pairs(&self.context.baggage),
        };
        self.record_host_call(started);
        Ok(value)
    }

    async fn deadline_unix_millis(&mut self) -> wasmtime::Result<Option<u64>> {
        let started = Instant::now();
        let _call = self.capabilities.scalar(
            "latent:context/context@0.1.0",
            "deadline-unix-millis",
            latent_policy::capability::ResourceTarget::Context,
            16,
        )?;
        let value = self.context.deadline_unix_millis;
        self.record_host_call(started);
        Ok(value)
    }

    async fn metadata(&mut self) -> wasmtime::Result<Vec<(String, String)>> {
        let started = Instant::now();
        self.capabilities.context(
            "metadata",
            self.context_policy.metadata_bytes(&self.context.metadata),
        )?;
        let value = self.context_policy.metadata_pairs(&self.context.metadata);
        self.record_host_call(started);
        Ok(value)
    }
}

impl context::HostWithStore<HostState> for HasSelf<HostState> {
    fn remaining_budget(
        mut host: Access<'_, HostState, Self>,
    ) -> wasmtime::Result<context::ResourceBudget> {
        let started = Instant::now();
        let fuel = host.as_context().get_fuel()?;
        let state = host.get();
        let _call = state.capabilities.scalar(
            "latent:context/context@0.1.0",
            "remaining-budget",
            latent_policy::capability::ResourceTarget::Context,
            11 * 8,
        )?;
        let result = state.remaining_budget_snapshot(fuel);
        state.record_host_call(started);
        result
    }
}

fn principal_kind(kind: PrincipalKind) -> &'static str {
    match kind {
        PrincipalKind::User => "user",
        PrincipalKind::Service => "service",
        PrincipalKind::Node => "node",
        PrincipalKind::Trigger => "trigger",
        PrincipalKind::Administrator => "administrator",
        PrincipalKind::Anonymous => "anonymous",
        _ => "unknown",
    }
}
