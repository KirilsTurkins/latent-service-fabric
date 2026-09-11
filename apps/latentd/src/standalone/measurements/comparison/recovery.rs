//! Fixed four-cell transport expiry/disconnect recovery, separate from #103.
mod collector;
mod evidence;
mod plan;
mod sequence;

use super::{budget, cold, node::Node, Result, Writer};

#[test]
#[ignore = "explicit recovery runner supplies clean paired identities and bounded output"]
fn phase1_recovery_collector() {
    collector::collect();
}
