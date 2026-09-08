//! Tiny Linux tests against the real standalone listener and durable catalogs.
#![cfg(target_os = "linux")]

#[path = "standalone_node/echo.rs"]
mod echo;
#[path = "standalone_node/startup.rs"]
mod startup;
#[path = "standalone_node/support.rs"]
mod support;

#[test]
fn listener_authentication_inventory_restart_and_clean_shutdown() {
    support::supervise(
        "listener_authentication_inventory_restart_and_clean_shutdown",
        startup::scenario,
    );
}

#[test]
#[ignore = "requires contracts-gate LSF_ECHO_COMPONENT; two bounded real activations"]
fn published_echo_executes_again_after_durable_restart() {
    support::supervise(
        "published_echo_executes_again_after_durable_restart",
        echo::scenario,
    );
}
