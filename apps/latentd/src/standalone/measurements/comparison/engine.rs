//! Fixed common engine matrix, compiled unchanged against old and new config.
mod call;
mod collector;
mod files;
mod fixture;
mod functional;
mod observation;
mod oracle;
mod plan;
mod publication;
mod resources;
mod sequence;

use super::cold::call::Clock;
use super::{node::Node, writer::Writer, Result};

#[test]
#[ignore = "explicit exact-reference engine runner supplies five-profile plan and immutable fixtures"]
fn phase1_engine_collector() {
    collector::execute().unwrap();
}
