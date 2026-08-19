use std::path::PathBuf;

use latent_toolchain_smoke::echo_fixture::{MAX_ACTIVATION_ID_BYTES, MAX_MESSAGE_BYTES};
use latent_toolchain_smoke::host::echo_bindings::{
    exports::examples::echo::api::EchoError,
    latent::{
        context::context::{
            Host as ContextHost, InvocationPrincipal, ResourceBudget, TraceContext,
        },
        log::log::{Field, Host as LogHost, Level, LogError},
    },
    Service,
};
use wasmtime::component::{Component, HasSelf, Linker};
use wasmtime::{Config, Engine, Store};

#[derive(Debug)]
struct CapturedLog {
    level: Level,
    message: String,
    fields: Vec<Field>,
}

#[derive(Debug)]
struct HostState {
    activation_id: String,
    activation_id_reads: u32,
    logs: Vec<CapturedLog>,
}

impl HostState {
    fn new() -> Self {
        Self {
            activation_id: "a".repeat(MAX_ACTIVATION_ID_BYTES + 17),
            activation_id_reads: 0,
            logs: Vec::new(),
        }
    }
}

impl ContextHost for HostState {
    fn activation_id(&mut self) -> String {
        self.activation_id_reads += 1;
        self.activation_id.clone()
    }

    fn root_activation_id(&mut self) -> String {
        "root-phase-0-echo".to_owned()
    }

    fn parent_activation_id(&mut self) -> Option<String> {
        None
    }

    fn principal(&mut self) -> InvocationPrincipal {
        InvocationPrincipal {
            subject: "fixture".to_owned(),
            kind: "test".to_owned(),
            tenant: Some("examples".to_owned()),
            service: Some("echo".to_owned()),
            claims: Vec::new(),
        }
    }

    fn trace(&mut self) -> TraceContext {
        TraceContext {
            trace_id: "00000000000000000000000000000001".to_owned(),
            span_id: "0000000000000001".to_owned(),
            trace_flags: 1,
            baggage: Vec::new(),
        }
    }

    fn deadline_unix_millis(&mut self) -> Option<u64> {
        None
    }

    fn remaining_budget(&mut self) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 4 * 1024 * 1024,
            wall_deadline_unix_millis: None,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 16 * 1024,
            effect_count: 0,
        }
    }

    fn metadata(&mut self) -> Vec<(String, String)> {
        vec![("fixture".to_owned(), "echo".to_owned())]
    }
}

impl LogHost for HostState {
    fn write(
        &mut self,
        level: Level,
        message: String,
        fields: Vec<Field>,
    ) -> Result<bool, LogError> {
        self.logs.push(CapturedLog {
            level,
            message,
            fields,
        });
        Ok(true)
    }
}

#[test]
#[ignore = "requires the component produced by tools/build_echo_capsule.py"]
fn component_round_trips_success_and_declared_errors() -> wasmtime::Result<()> {
    let artifact = fixture_path();
    let mut configuration = Config::new();
    configuration.wasm_component_model(true);
    let engine = Engine::new(&configuration)?;
    let component = Component::from_file(&engine, artifact)?;

    let mut linker = Linker::new(&engine);
    Service::add_to_linker::<_, HasSelf<_>>(&mut linker, |state| state)?;

    let mut store = Store::new(&engine, HostState::new());
    let service = Service::instantiate(&mut store, &component, &linker)?;
    let api = service.examples_echo_api();

    let successful = api.call_echo(&mut store, "phase-0")?;
    match successful {
        Ok(value) => assert_eq!(value, "phase-0"),
        Err(error) => panic!("normal echo returned a domain error: {error:?}"),
    }

    let empty = api.call_echo(&mut store, "")?;
    assert!(matches!(empty, Err(EchoError::EmptyMessage)));

    let oversized_message = "x".repeat(MAX_MESSAGE_BYTES + 1);
    let oversized = api.call_echo(&mut store, &oversized_message)?;
    assert!(matches!(oversized, Err(EchoError::MessageTooLarge)));

    let state = store.data();
    assert_eq!(state.activation_id_reads, 3);
    assert_eq!(state.logs.len(), 3);
    let logged_activation_id = "a".repeat(MAX_ACTIVATION_ID_BYTES);
    assert_log(&state.logs[0], &logged_activation_id, "7", "success");
    assert_log(&state.logs[1], &logged_activation_id, "0", "empty-message");
    assert_log(
        &state.logs[2],
        &logged_activation_id,
        &(MAX_MESSAGE_BYTES + 1).to_string(),
        "message-too-large",
    );

    Ok(())
}

fn fixture_path() -> PathBuf {
    std::env::var_os("LATENT_ECHO_COMPONENT")
        .map(PathBuf::from)
        .expect("LATENT_ECHO_COMPONENT must point to the generated component")
}

fn assert_log(
    log: &CapturedLog,
    activation_id: &str,
    message_bytes: &str,
    outcome: &str,
) {
    assert!(matches!(&log.level, Level::Info));
    assert_eq!(log.message, "echo invocation");
    assert_eq!(log.fields.len(), 3);
    assert_field(&log.fields, "activation.id", activation_id);
    assert_field(&log.fields, "message.bytes", message_bytes);
    assert_field(&log.fields, "outcome", outcome);
}

fn assert_field(fields: &[Field], name: &str, expected: &str) {
    let field = fields
        .iter()
        .find(|field| field.name == name)
        .unwrap_or_else(|| panic!("missing structured log field {name}"));
    assert_eq!(field.value, expected);
}
