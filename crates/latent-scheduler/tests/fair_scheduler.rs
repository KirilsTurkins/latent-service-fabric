//! Lightweight acceptance tests using real admission permits and fixed cells.

#[path = "fair_scheduler/concurrency.rs"]
mod concurrency;
#[path = "fair_scheduler/faults.rs"]
mod faults;
#[path = "fair_scheduler/lifecycle.rs"]
mod lifecycle;
#[path = "fair_scheduler/ordering.rs"]
mod ordering;
#[path = "fair_scheduler/placement.rs"]
mod placement;
#[path = "fair_scheduler/support.rs"]
mod support;
