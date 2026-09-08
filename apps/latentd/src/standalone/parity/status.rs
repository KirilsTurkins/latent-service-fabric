use latent_testkit::conformance::WorkCounter;
use latent_testkit::{NodeHarness, ScopedNodeHarness};
use latent_wire::invocation::{
    activation_status_to_proto, proto, AuthenticatedInvocationContext, InvocationService,
    InvocationServiceAdapter, InvocationServiceClient, LocalInvocationRuntime,
};

use super::{fixture, StandaloneNode};

pub async fn compare(
    node: &StandaloneNode,
    adapter: &InvocationServiceAdapter<LocalInvocationRuntime>,
    client: &mut InvocationServiceClient<tonic::transport::Channel>,
    context: &AuthenticatedInvocationContext,
    work: &WorkCounter,
    responses: (&proto::InvokeResponse, &proto::InvokeResponse),
) {
    let (direct, remote) = responses;
    work.before_command(false).unwrap();
    let left = adapter
        .get_activation(context.request(proto::GetActivationRequest {
            activation_id: direct.activation_id.clone(),
        }))
        .await
        .unwrap()
        .into_inner();
    work.before_command(false).unwrap();
    let right = client
        .get_activation(fixture::request(proto::GetActivationRequest {
            activation_id: remote.activation_id.clone(),
        }))
        .await
        .unwrap()
        .into_inner();
    let scoped = ScopedNodeHarness::new(&node.manager, context.principal(), work.clone()).unwrap();
    let retained = scoped
        .status(&latent_core::ActivationId(left.activation_id.clone()))
        .unwrap()
        .expect("same scoped local terminal status");
    let mut local = activation_status_to_proto(&retained).unwrap();
    // The RPC boundary replaces producer messages with a finite public
    // vocabulary. Codes, details, retryability and all status fields must match.
    if let Some(proto::activation_status::TerminalOutcome::PlatformFailure(error)) =
        &mut local.terminal_outcome
    {
        assert_eq!(
            error.message,
            "invocation does not satisfy local admission policy"
        );
        let Some(proto::activation_status::TerminalOutcome::PlatformFailure(public)) =
            &left.terminal_outcome
        else {
            panic!("local admission failure must remain a public platform failure");
        };
        assert_eq!(
            public.message,
            "the invocation exceeded an available resource limit"
        );
        error.message.clone_from(&public.message);
    }
    assert_eq!(local, left);
    assert_eq!(left.terminal_state, right.terminal_state);
    assert_eq!(left.final_consumption, direct.consumption);
    assert_eq!(right.final_consumption, remote.consumption);
    assert!(left.terminal_at_unix_millis.is_some() && right.terminal_at_unix_millis.is_some());
}
