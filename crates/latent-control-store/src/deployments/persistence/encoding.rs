//! A single final envelope allocation with its checksum patched at a recorded offset.

use std::io::{self, Write};

use latent_manifest::{__serde::Serialize, __serde_json as json};

use super::super::compiler::CompiledCatalog;
use super::super::observation::{count, Work};
use super::{hashing::Hashing, projection::Snapshot, LimitedBytes};

const PREFIX: &[u8] = b"{\"format_version\":2,\"checksum\":\"sha256:";

pub(super) fn write(
    output: &mut LimitedBytes,
    catalog: &CompiledCatalog,
    work: &mut Work,
) -> io::Result<()> {
    write_with_control(output, catalog, None, work)
}

pub(super) fn write_with_control(
    output: &mut LimitedBytes,
    catalog: &CompiledCatalog,
    control: Option<&super::ControlPayloadRef<'_>>,
    work: &mut Work,
) -> io::Result<()> {
    if control.is_some() {
        output.write_all(b"{\"format_version\":3,\"checksum\":\"sha256:")?;
    } else {
        output.write_all(PREFIX)?;
    }
    let checksum_start = output.bytes.len();
    output.write_all(&[b'0'; 64])?;
    output.write_all(b"\",\"payload\":")?;
    let limit = output.limit;
    let mut payload = Hashing::new(&mut *output, limit);
    count!(work, payload_serializations, 1);
    write_payload(&mut payload, catalog, control)?;
    let checksum = payload.finish();
    output.write_all(b"}")?;
    // The reserved range is structural, never a search through user-controlled strings.
    output.bytes[checksum_start..checksum_start + checksum.len()].copy_from_slice(&checksum);
    Ok(())
}

fn value(output: &mut impl Write, value: &(impl Serialize + ?Sized)) -> io::Result<()> {
    json::to_writer(output, value).map_err(io::Error::other)
}

fn write_payload(
    output: &mut impl Write,
    catalog: &CompiledCatalog,
    control: Option<&super::ControlPayloadRef<'_>>,
) -> io::Result<()> {
    output.write_all(b"{\"generation\":")?;
    value(output, &catalog.generation.0)?;
    output.write_all(b",\"generated_at_unix_millis\":")?;
    value(output, &catalog.generated_at_unix_millis)?;
    output.write_all(b",\"deployments\":[")?;
    for (index, record) in catalog.records.iter().enumerate() {
        if index != 0 {
            output.write_all(b",")?;
        }
        // Compiler-created canonical JSON is raw only in the deployment array.
        // The snapshot adapter serializes the same attribute as an escaped string.
        output.write_all(
            record
                .attributes
                .get("lsf.deployment")
                .expect("compiled canonical deployment")
                .as_bytes(),
        )?;
    }
    output.write_all(b"],\"snapshot\":")?;
    value(output, &Snapshot(catalog))?;
    output.write_all(b",\"object_generations\":[")?;
    for (index, (id, generation)) in catalog.versions.iter().enumerate() {
        if index != 0 {
            output.write_all(b",")?;
        }
        value(
            output,
            &Version {
                id: &id.0,
                generation: *generation,
            },
        )?;
    }
    output.write_all(b"]")?;
    if let Some(control) = control {
        output.write_all(b",\"control\":")?;
        value(output, control)?;
    }
    output.write_all(b"}")
}

#[derive(Serialize)]
#[serde(crate = "latent_manifest::__serde")]
struct Version<'a> {
    id: &'a str,
    generation: u64,
}
