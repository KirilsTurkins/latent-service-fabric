//! Fixed public durable mutation sequence and separately owned fresh reopen.
mod collector;
mod files;
pub(super) mod frames;
mod mutations;
pub(super) mod observation;
mod oracle;
mod plan;
mod proofs;
mod publication;
mod sequence;

use super::{cold::call::Clock, node::Node, writer::Writer, Result};
use plan::Plan;

#[test]
#[ignore = "explicit catalog mutation runner supplies exact identities and exclusively owned roots"]
fn phase1_catalog_mutation_collector() {
    collector::execute().unwrap();
}
