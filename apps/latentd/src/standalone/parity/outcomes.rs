use latent_wire::invocation::InvocationService;
use serde_json::{json, Value};

use super::{cases, fixture, session::Session, status, telemetry};

pub async fn run(session: &mut Session) -> (Vec<Value>, Value) {
    let mut rows = Vec::new();
    let mut echo_telemetry = None;
    for index in 0..cases::NAMES.len() {
        let direct_id = format!("direct-{index}");
        let rpc_id = format!("remote-{index}");
        session.work.before_command(true).unwrap();
        let direct = session
            .adapter
            .invoke(session.examples.request(cases::request(index, &direct_id)))
            .await;
        session.work.before_command(true).unwrap();
        let remote = session
            .client
            .invoke(fixture::request(cases::request(index, &rpc_id)))
            .await;
        match (direct, remote) {
            (Ok(direct), Ok(remote)) => {
                let direct = direct.into_inner();
                let remote = remote.into_inner();
                assert_eq!(direct.activation_id, direct_id);
                assert_eq!(remote.activation_id, rpc_id);
                rows.push(cases::compare(index, &direct, &remote));
                if matches!(index, 0 | 1 | 4 | 5) {
                    status::compare(
                        &session.node,
                        &session.adapter,
                        &mut session.client,
                        &session.examples,
                        &session.work,
                        (&direct, &remote),
                    )
                    .await;
                }
                if index == 0 {
                    assert_eq!(remote.release_digest, session.echo_release);
                    echo_telemetry = Some(
                        telemetry::observe(
                            &session.node,
                            &remote,
                            "examples",
                            "parity-root",
                            "parity-parent",
                            1,
                        )
                        .await,
                    );
                }
            }
            (Err(left), Err(right)) => {
                assert!(
                    matches!(index, 3 | 7),
                    "unexpected rejected case: {} {left} {right}",
                    cases::NAMES[index]
                );
                assert_eq!(left.code(), right.code());
                assert_eq!(left.details(), right.details());
                rows.push(json!({"name":cases::NAMES[index],"classification":"rpc-rejection","code":format!("{:?}",left.code())}));
            }
            (left, right) => panic!(
                "adapter/RPC mismatch {}: {left:?} {right:?}",
                cases::NAMES[index]
            ),
        }
    }
    (rows, echo_telemetry.expect("actual echo guest telemetry"))
}
