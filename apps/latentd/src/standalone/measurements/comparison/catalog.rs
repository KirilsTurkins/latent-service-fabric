//! Bounded, zero-Invoke catalog comparison against two immutable revisions.
mod collector;
mod files;
mod fixture;
mod frames;
mod observation;
mod plan;
mod proofs;
mod resolve;
mod sampler;
mod sequence;

use super::{cold::call::Clock, node::Node, writer::Writer, Result};
use plan::Plan;

#[test]
#[ignore = "explicit catalog runner supplies fixed counts, exact source identities and owned roots"]
fn phase1_catalog_collector() {
    collector::execute().unwrap();
}
