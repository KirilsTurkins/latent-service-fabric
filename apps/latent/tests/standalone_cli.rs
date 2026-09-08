//! Small actual CLI processes; remote fixtures run only through the contract gate.

#[path = "standalone_cli/local.rs"]
mod local;
#[cfg(target_os = "linux")]
#[path = "standalone_cli/outcomes.rs"]
mod outcomes;
#[path = "standalone_cli/process.rs"]
mod process;
#[cfg(target_os = "linux")]
#[path = "standalone_cli/support.rs"]
mod support;
#[cfg(target_os = "linux")]
#[path = "standalone_cli/workflow.rs"]
mod workflow;
