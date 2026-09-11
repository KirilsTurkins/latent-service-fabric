mod assertions;
mod evidence;

use latent_wire::invocation::{proto, InvocationService};
use serde_json::{json, Value};

use super::{fixture, session::Session, telemetry};

pub async fn run(session: &mut Session) -> (Vec<Value>, Value) {
    let mut rows = Vec::new();
    let mut tenant_telemetry = None;
    for function in ["snapshot", "work-observe", "clocks"] {
        let direct_id = format!("direct-cap-{function}");
        let rpc_id = format!("remote-cap-{function}");
        let before = session.node.clock.sample().unix_millis();
        session.work.before_command(true).unwrap();
        let direct = session
            .adapter
            .invoke(session.tests.request(request(function, &direct_id)))
            .await
            .unwrap()
            .into_inner();
        session.work.before_command(true).unwrap();
        let remote = session
            .client
            .invoke(fixture::authenticated(
                request(function, &rpc_id),
                fixture::TESTS_TOKEN,
            ))
            .await
            .unwrap()
            .into_inner();
        let after = session.node.clock.sample().unix_millis();
        assert_eq!(direct.activation_id, direct_id);
        assert_eq!(remote.activation_id, rpc_id);
        assert_eq!(direct.release_digest, session.capability_release);
        assert_eq!(direct.release_digest, remote.release_digest);
        assert_eq!(direct.revision_id, remote.revision_id);
        assert_eq!(direct.route_generation, remote.route_generation);
        let direct_status = direct_status(session, &direct).await;
        let remote_status = remote_status(session, &remote).await;
        let log_count = match function {
            "snapshot" => 0,
            "work-observe" => 1,
            _ => 2,
        };
        let direct_telemetry =
            telemetry::observe(&session.node, &direct, "tests", ROOT, PARENT, log_count).await;
        let remote_telemetry =
            telemetry::observe(&session.node, &remote, "tests", ROOT, PARENT, log_count).await;
        let direct = evidence::call(&direct, &direct_status, direct_telemetry);
        let remote = evidence::call(&remote, &remote_status, remote_telemetry);
        assertions::check(function, &direct, before, after);
        assertions::check(function, &remote, before, after);
        for field in ["peak_memory_bytes", "log_bytes"] {
            assert_eq!(direct["consumption"][field], remote["consumption"][field]);
        }
        assert_ne!(
            direct["completion_span"]["trace"]["trace_id"],
            remote["completion_span"]["trace"]["trace_id"]
        );
        if function == "work-observe" {
            tenant_telemetry = Some(remote.clone());
        }
        rows.push(json!({"name":function,"direct":direct,"rpc":remote,
            "observed_before_unix_millis":before.to_string(),"observed_after_unix_millis":after.to_string()}));
    }
    (rows, tenant_telemetry.unwrap())
}

pub const ROOT: &str = "capability-root";
pub const PARENT: &str = "capability-parent";
pub const FUEL: u64 = 100_000_000;
pub const MEMORY: u64 = 67_108_864;
pub const LOG: u64 = 16_384;
pub const WALL: u64 = 4000;

fn request(function: &str, id: &str) -> proto::InvokeRequest {
    proto::InvokeRequest {
        activation_id: Some(id.to_owned()),
        root_activation_id: Some(ROOT.to_owned()),
        parent_activation_id: Some(PARENT.to_owned()),
        target: Some(proto::InvocationTarget {
            tenant: "tests".to_owned(),
            service: fixture::SHARED.to_owned(),
            contract: "tests:capabilities/api@0.1.0".to_owned(),
            function: function.to_owned(),
            route: None,
        }),
        payload: b"[]".to_vec(),
        media_type: latent_wasmtime::WIT_VALUES_MEDIA_TYPE.to_owned(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: FUEL,
            memory_bytes: MEMORY,
            log_bytes: LOG,
            wall_time_limit_millis: Some(WALL),
            ..proto::ResourceBudget::default()
        }),
        metadata: [
            ("guest.visible".to_owned(), "paired".to_owned()),
            (
                "internal.credential".to_owned(),
                "private-context-marker".to_owned(),
            ),
        ]
        .into(),
        ..proto::InvokeRequest::default()
    }
}

async fn direct_status(
    session: &Session,
    response: &proto::InvokeResponse,
) -> proto::ActivationStatus {
    session.work.before_command(false).unwrap();
    session
        .adapter
        .get_activation(session.tests.request(proto::GetActivationRequest {
            activation_id: response.activation_id.clone(),
        }))
        .await
        .unwrap()
        .into_inner()
}

async fn remote_status(
    session: &mut Session,
    response: &proto::InvokeResponse,
) -> proto::ActivationStatus {
    session.work.before_command(false).unwrap();
    session
        .client
        .get_activation(fixture::authenticated(
            proto::GetActivationRequest {
                activation_id: response.activation_id.clone(),
            },
            fixture::TESTS_TOKEN,
        ))
        .await
        .unwrap()
        .into_inner()
}
