//! Lossless trusted inventory conversion; RPC bounds are checked before materialization.
mod bounds;
mod convert;
#[cfg(test)]
mod tests;

pub(super) use bounds::validate_inventory;
pub use convert::{node_inventory_from_proto, node_inventory_to_proto};
