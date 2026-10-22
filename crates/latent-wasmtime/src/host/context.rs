use super::HostState;
use crate::bindings::latent::context::context;
use latent_core::{BudgetProfile, PrincipalKind};
use std::time::Instant;
use wasmtime::component::{Access, HasSelf, HostOutput, Linker};
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
        let value = principal_value(self, false);
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
        let value = trace_value(self, false);
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

fn principal_value(state: &HostState, exact: bool) -> context::InvocationPrincipal {
    context::InvocationPrincipal {
        subject: state.context.principal.subject.clone(),
        kind: principal_kind(state.context.principal.kind).to_owned(),
        tenant: state
            .context
            .principal
            .tenant
            .as_ref()
            .map(|tenant| tenant.0.clone()),
        service: state
            .context
            .principal
            .service
            .as_ref()
            .map(|service| service.0.clone()),
        claims: if exact {
            state
                .context_policy
                .claim_pairs_exact(&state.context.principal.claims)
        } else {
            state
                .context_policy
                .claim_pairs(&state.context.principal.claims)
        },
    }
}

fn trace_value(state: &HostState, exact: bool) -> context::TraceContext {
    context::TraceContext {
        trace_id: state.context.trace_id.clone(),
        span_id: state.context.span_id.clone(),
        trace_flags: state.context.trace_flags,
        baggage: if exact {
            state
                .context_policy
                .baggage_pairs_exact(&state.context.baggage)
        } else {
            state.context_policy.baggage_pairs(&state.context.baggage)
        },
    }
}

fn owned_reply<R>(
    state: &mut HostState,
    started: Instant,
    charge: impl FnOnce(&HostState) -> wasmtime::Result<usize>,
    build: impl FnOnce(&HostState, bool) -> R,
) -> wasmtime::Result<HostOutput<(R,)>> {
    let accounted = matches!(
        state.accounting.budget().profile(),
        BudgetProfile::Phase3 | BudgetProfile::Phase4
    );
    let allocation = if accounted {
        crate::native_tables::reserve(state.accounting.budget(), charge(state)?)?
    } else {
        None
    };
    // All capability errors occurred before reserve. These closed builders only
    // clone pinned String/Vec/records: no fallible builder error can own R.
    let output = HostOutput::build(allocation, || (build(state, accounted),));
    state.record_host_call(started);
    Ok(output)
}

/// Exact context ABI, with original backing owners only for the six heap replies.
pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    use super::policy::{reply_add, reply_string_charge as text};
    let mut interface = linker.instance("latent:context/context@0.1.0")?;
    interface.func_wrap_async_owned::<(), (String,), _>("activation-id", |mut caller, ()| {
        Box::new(async move {
            let state = caller.data_mut();
            let started = Instant::now();
            state
                .capabilities
                .context("activation-id", state.context.activation_id.0.len())?;
            owned_reply(
                state,
                started,
                |s| text(&s.context.activation_id.0),
                |s, _| s.context.activation_id.0.clone(),
            )
        })
    })?;
    interface.func_wrap_async_owned::<(), (String,), _>(
        "root-activation-id",
        |mut caller, ()| {
            Box::new(async move {
                let state = caller.data_mut();
                let started = Instant::now();
                state.capabilities.context(
                    "root-activation-id",
                    state.context.root_activation_id.0.len(),
                )?;
                owned_reply(
                    state,
                    started,
                    |s| text(&s.context.root_activation_id.0),
                    |s, _| s.context.root_activation_id.0.clone(),
                )
            })
        },
    )?;
    interface.func_wrap_async_owned::<(), (Option<String>,), _>(
        "parent-activation-id",
        |mut caller, ()| {
            Box::new(async move {
                let state = caller.data_mut();
                let started = Instant::now();
                state.capabilities.context(
                    "parent-activation-id",
                    state
                        .context
                        .parent_activation_id
                        .as_ref()
                        .map_or(0, |id| id.0.len()),
                )?;
                owned_reply(
                    state,
                    started,
                    |s| {
                        s.context
                            .parent_activation_id
                            .as_ref()
                            .map_or(Ok(0), |id| text(&id.0))
                    },
                    |s, _| {
                        s.context
                            .parent_activation_id
                            .as_ref()
                            .map(|id| id.0.clone())
                    },
                )
            })
        },
    )?;
    interface.func_wrap_async_owned::<(), (context::InvocationPrincipal,), _>(
        "principal",
        |mut caller, ()| {
            Box::new(async move {
                let state = caller.data_mut();
                let started = Instant::now();
                state.capabilities.context(
                    "principal",
                    state.context.principal.subject.len()
                        + 16
                        + state
                            .context
                            .principal
                            .tenant
                            .as_ref()
                            .map_or(0, |t| t.0.len())
                        + state
                            .context
                            .principal
                            .service
                            .as_ref()
                            .map_or(0, |s| s.0.len())
                        + state
                            .context_policy
                            .claim_bytes(&state.context.principal.claims),
                )?;
                owned_reply(
                    state,
                    started,
                    |s| {
                        let p = &s.context.principal;
                        let mut bytes =
                            reply_add(text(&p.subject)?, text(principal_kind(p.kind))?)?;
                        for value in [
                            p.tenant.as_ref().map(|x| &x.0),
                            p.service.as_ref().map(|x| &x.0),
                        ]
                        .into_iter()
                        .flatten()
                        {
                            bytes = reply_add(bytes, text(value)?)?;
                        }
                        reply_add(bytes, s.context_policy.claim_reply_charge(&p.claims)?)
                    },
                    principal_value,
                )
            })
        },
    )?;
    interface.func_wrap_async_owned::<(), (context::TraceContext,), _>(
        "trace",
        |mut caller, ()| {
            Box::new(async move {
                let state = caller.data_mut();
                let started = Instant::now();
                state.capabilities.context(
                    "trace",
                    state.context.trace_id.len()
                        + state.context.span_id.len()
                        + state.context_policy.baggage_bytes(&state.context.baggage),
                )?;
                owned_reply(
                    state,
                    started,
                    |s| {
                        reply_add(
                            reply_add(text(&s.context.trace_id)?, text(&s.context.span_id)?)?,
                            s.context_policy.baggage_reply_charge(&s.context.baggage)?,
                        )
                    },
                    trace_value,
                )
            })
        },
    )?;
    interface.func_wrap_async_owned::<(), (Vec<(String, String)>,), _>(
        "metadata",
        |mut caller, ()| {
            Box::new(async move {
                let state = caller.data_mut();
                let started = Instant::now();
                state.capabilities.context(
                    "metadata",
                    state.context_policy.metadata_bytes(&state.context.metadata),
                )?;
                owned_reply(
                    state,
                    started,
                    |s| s.context_policy.metadata_reply_charge(&s.context.metadata),
                    |s, exact| {
                        if exact {
                            s.context_policy.metadata_pairs_exact(&s.context.metadata)
                        } else {
                            s.context_policy.metadata_pairs(&s.context.metadata)
                        }
                    },
                )
            })
        },
    )?;
    // Keep the two original scalar implementations and store-aware fuel read.
    interface.func_wrap_async::<(), (Option<u64>,), _>(
        "deadline-unix-millis",
        |mut caller, ()| {
            Box::new(
                async move { Ok((context::Host::deadline_unix_millis(caller.data_mut()).await?,)) },
            )
        },
    )?;
    interface.func_wrap::<(), (context::ResourceBudget,), _>(
        "remaining-budget",
        |caller, ()| {
            let access = Access::<HostState, HasSelf<HostState>>::new(caller, |state| state);
            Ok((
                <HasSelf<HostState> as context::HostWithStore<HostState>>::remaining_budget(
                    access,
                )?,
            ))
        },
    )?;
    Ok(())
}
