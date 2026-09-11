//! Bounded, zero-Invoke catalog comparison against two immutable revisions.
mod collector;
pub(super) mod files;
pub(super) mod fixture;
mod frames;
pub(super) mod observation;
mod plan;
mod proofs;
pub(super) mod resolve;
pub(super) mod sampler;
mod sequence;

use super::{cold::call::Clock, node::Node, writer::Writer, Result};
use plan::Plan;

#[test]
#[ignore = "explicit catalog runner supplies fixed counts, exact source identities and owned roots"]
fn phase1_catalog_collector() {
    collector::execute().unwrap();
}
