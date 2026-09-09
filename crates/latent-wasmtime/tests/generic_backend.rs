//! Small real-component regressions; fixture construction is in the contracts gate.

#[path = "generic_backend/cache_lifetimes.rs"]
mod cache_lifetimes;

#[path = "generic_backend/cold_readiness.rs"]
mod cold_readiness;
#[path = "generic_backend/containment.rs"]
mod containment;
#[path = "generic_backend/dispatch.rs"]
mod dispatch;
#[path = "generic_backend/owned_preparation.rs"]
mod owned_preparation;
#[path = "generic_backend/preparation.rs"]
mod preparation;
#[path = "generic_backend/preparation_source.rs"]
mod preparation_source;
#[path = "generic_backend/rejection.rs"]
mod rejection;
#[path = "generic_backend/request_ownership.rs"]
mod request_ownership;
#[path = "generic_backend/support.rs"]
mod support;
