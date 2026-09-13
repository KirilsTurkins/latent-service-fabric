//! Fixed-schema traversal before allocation of the lossless JSON result.
mod audit;
mod common;
mod deployment;
mod release;
mod rollout;
use super::{invalid_response, proto};
use crate::error::Failure;
use prost::Message;
use serde_json::{json, Value};

pub(in crate::management) trait Project {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure>;
    fn project(self) -> Value;
}
pub(in crate::management) fn checked<T: Project + Message>(
    value: &T,
    maximum: usize,
) -> Result<(), Failure> {
    let mut tree = Tree {
        nodes: 65_536,
        bytes: maximum.checked_mul(8).ok_or_else(invalid_response)?,
    };
    value.validate(&mut tree)?;
    if value.encoded_len() > maximum {
        return Err(invalid_response());
    }
    Ok(())
}
pub(in crate::management) struct Tree {
    nodes: usize,
    bytes: usize,
}
impl Tree {
    fn charge(&mut self, count: usize, bytes: usize) -> Result<(), Failure> {
        self.nodes = self.nodes.checked_sub(count).ok_or_else(invalid_response)?;
        self.bytes = self.bytes.checked_sub(bytes).ok_or_else(invalid_response)?;
        Ok(())
    }
    fn message<T>(&mut self) -> Result<(), Failure> {
        self.charge(1, std::mem::size_of::<T>())
    }
    fn text(&mut self, value: &String, maximum: usize) -> Result<(), Failure> {
        if value.capacity() > maximum || value.chars().any(char::is_control) {
            return Err(invalid_response());
        }
        self.charge(1, value.capacity())
    }
    fn sequence<T>(&mut self, value: &Vec<T>, maximum: usize) -> Result<(), Failure> {
        if value.len() > maximum || value.capacity() > maximum.saturating_mul(2) {
            return Err(invalid_response());
        }
        self.charge(
            value.len(),
            value
                .capacity()
                .checked_mul(std::mem::size_of::<T>())
                .ok_or_else(invalid_response)?,
        )
    }
}
