//! Separate bounded diagnostic population for short deadline ownership.
pub(super) mod call;
pub(super) mod collector;
pub(super) mod cpu;
mod delayed;
pub(super) mod observation;
mod plan;
mod sequence;

use super::{cold, node::Node, Result, Writer};

#[test]
#[ignore = "explicit paired budget runner supplies exact clean revision identities"]
fn phase1_budget_collector() {
    collector::collect();
}
