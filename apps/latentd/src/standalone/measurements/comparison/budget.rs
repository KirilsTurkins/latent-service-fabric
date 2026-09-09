//! Separate bounded diagnostic population for short deadline ownership.
mod call;
mod collector;
mod cpu;
mod delayed;
mod observation;
mod plan;
mod sequence;

use super::{cold, node::Node, Result, Writer};

#[test]
#[ignore = "explicit paired budget runner supplies exact clean revision identities"]
fn phase1_budget_collector() {
    collector::collect();
}
