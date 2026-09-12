//! Generated RPC clients over an in-memory transport and real durable catalogs.
#![cfg(unix)]

#[path = "management_service/audit.rs"]
mod audit;
#[path = "management_service/deployment.rs"]
mod deployment;
#[path = "management_service/inspection.rs"]
mod inspection;
#[path = "management_service/release.rs"]
mod release;
#[path = "management_service/support.rs"]
mod support;
