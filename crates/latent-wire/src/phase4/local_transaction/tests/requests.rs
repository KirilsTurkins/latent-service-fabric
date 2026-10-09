use super::*;
use crate::invocation::AuthenticatedInvocationContext;
use latent_core::{
    ClockSample, InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget, TenantId,
};
use serde_json::{json, Value};

pub(super) fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100_000_000,
        memory_bytes: 64 * 1024 * 1024,
        wall_time_limit_millis: Some(10_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 4 * 1024 * 1024,
        state_write_bytes: 2 * 1024 * 1024,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 32,
    }
}
pub(super) fn principal(subject: &str) -> InvocationPrincipal {
    InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId(publication::TENANT.into())),
        service: None,
        claims: Metadata::new(),
    }
}
pub(super) fn context_for(principal: InvocationPrincipal) -> AuthenticatedInvocationContext {
    let now = ClockSample::system_now();
    AuthenticatedInvocationContext::new(principal).with_transport_deadline_at(
        now.unix_millis() + 10_000,
        now.monotonic() + Duration::from_secs(10),
    )
}
pub(super) fn context(subject: &str) -> AuthenticatedInvocationContext {
    context_for(principal(subject))
}
pub(super) fn invocation(function: &str, payload: Vec<u8>, query: bool) -> i::InvokeRequest {
    let mut resources = budget();
    if query {
        resources.state_write_bytes = 0;
        resources.effect_count = 0;
    }
    i::InvokeRequest {
        target: Some(i::InvocationTarget {
            tenant: publication::TENANT.into(),
            service: publication::SERVICE.into(),
            contract: publication::CONTRACT.into(),
            function: function.into(),
            route: None,
        }),
        payload,
        media_type: "application/vnd.latent.wit-values.v1+json".into(),
        budget: Some(crate::invocation::budget_to_proto(&resources)),
        ..Default::default()
    }
}
pub(super) fn selector() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: publication::TENANT.into(),
        namespace: publication::NAMESPACE.into(),
        incarnation: "1".into(),
    }
}
pub(super) fn command(key: &str, delta: u32, reject: bool) -> t::InvokeCommandRequest {
    t::InvokeCommandRequest {
        profile: Some(latent_rpc::phase4::current_profile()),
        invocation: Some(invocation(
            "update",
            serde_json::to_vec(&json!([{"delta":delta,"reject":reject}])).unwrap(),
            false,
        )),
        command: Some(t::CommandSelector {
            namespace: Some(selector()),
            operation: "update".into(),
            client_key: key.into(),
            ..Default::default()
        }),
        input_format: publication::FORMAT.into(),
        ..Default::default()
    }
}
pub(super) async fn invoke(
    f: &Fixture,
    key: &str,
    delta: u32,
    reject: bool,
) -> t::InvokeCommandResponse {
    tokio::time::timeout(
        Duration::from_secs(10),
        f.adapter()
            .invoke_command(context("alice").request(command(key, delta, reject))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner()
}
pub(super) fn success(response: &t::InvokeCommandResponse) -> i::Success {
    let Some(i::invoke_response::Result::Success(body)) =
        response.invocation.as_ref().unwrap().result.as_ref()
    else {
        panic!("guest must commit: {response:?}")
    };
    assert_eq!(
        response.command.as_ref().unwrap().outcome,
        t::CommandOutcome::Committed as i32
    );
    assert!(
        response
            .command
            .as_ref()
            .unwrap()
            .application_state_committed
    );
    body.clone()
}
pub(super) fn aggregate(payload: &[u8]) -> u64 {
    let value: Value = serde_json::from_slice(payload).unwrap();
    value[0]["ok"]["count"]
        .as_str()
        .expect("typed u64 aggregate")
        .parse()
        .unwrap()
}
