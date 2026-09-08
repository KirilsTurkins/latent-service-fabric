//! Bounded lifecycle integration with real admission and scheduling.

#[path = "activation_lifecycle/backend.rs"]
mod backend;
#[path = "activation_lifecycle/catalog.rs"]
mod catalog;
#[path = "activation_lifecycle/cleanup.rs"]
mod cleanup;
#[path = "activation_lifecycle/identity.rs"]
mod identity;
#[path = "activation_lifecycle/model.rs"]
mod model;
#[path = "activation_lifecycle/outcomes.rs"]
mod outcomes;
#[path = "activation_lifecycle/preparation.rs"]
mod preparation;
#[path = "activation_lifecycle/races.rs"]
mod races;
#[path = "activation_lifecycle/support.rs"]
mod support;

#[path = "activation_lifecycle/observations.rs"]
mod observations;

#[path = "activation_lifecycle/deadline_abort.rs"]
mod deadline_abort;
