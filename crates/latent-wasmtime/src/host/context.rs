use super::HostState;
use crate::bindings::latent::context::context;
use latent_core::PrincipalKind;
use std::time::Instant;
use wasmtime::component::{Access, HasSelf};
use wasmtime::AsContext;

impl context::Host for HostState {
    async fn activation_id(&mut self) -> String {
        let started = Instant::now();
        let value = self.context.activation_id.0.clone();
        self.record_host_call(started);
        value
    }

    async fn root_activation_id(&mut self) -> String {
        let started = Instant::now();
        let value = self.context.root_activation_id.0.clone();
        self.record_host_call(started);
        value
    }

    async fn parent_activation_id(&mut self) -> Option<String> {
        let started = Instant::now();
        let value = self
            .context
            .parent_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone());
        self.record_host_call(started);
        value
    }

    async fn principal(&mut self) -> context::InvocationPrincipal {
        let started = Instant::now();
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
        value
    }

    async fn trace(&mut self) -> context::TraceContext {
        let started = Instant::now();
        let value = context::TraceContext {
            trace_id: self.context.trace_id.clone(),
            span_id: self.context.span_id.clone(),
            trace_flags: self.context.trace_flags,
            baggage: self.context_policy.baggage_pairs(&self.context.baggage),
        };
        self.record_host_call(started);
        value
    }

    async fn deadline_unix_millis(&mut self) -> Option<u64> {
        let started = Instant::now();
        let value = self.context.deadline_unix_millis;
        self.record_host_call(started);
        value
    }

    async fn metadata(&mut self) -> Vec<(String, String)> {
        let started = Instant::now();
        let value = self.context_policy.metadata_pairs(&self.context.metadata);
        self.record_host_call(started);
        value
    }
}

impl context::HostWithStore<HostState> for HasSelf<HostState> {
    fn remaining_budget(
        mut host: Access<'_, HostState, Self>,
    ) -> wasmtime::Result<context::ResourceBudget> {
        let started = Instant::now();
        let fuel = host.as_context().get_fuel()?;
        let state = host.get();
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
