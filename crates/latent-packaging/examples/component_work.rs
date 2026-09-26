//! Bounded structural observations; not admission, validation or a host RSS claim.
use std::{io::Read, time::Instant};
use wasmparser::{Parser, Payload};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).ok_or("component path required")?;
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(64 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 64 * 1024 * 1024 {
        return Err("component byte bound".into());
    }
    let start = Instant::now();
    let mut functions = 0_u64;
    let mut operators = 0_u64;
    let mut locals = 0_u64;
    for payload in Parser::new(0).parse_all(&bytes) {
        if let Payload::CodeSectionEntry(body) = payload? {
            functions += 1;
            if functions > 65_536 {
                return Err("function work bound".into());
            }
            for local in body.get_locals_reader()? {
                locals += u64::from(local?.0);
                if locals > 1_048_576 {
                    return Err("local work bound".into());
                }
            }
            let mut reader = body.get_operators_reader()?;
            while !reader.eof() {
                reader.read()?;
                operators += 1;
                if operators > 8_000_000 {
                    return Err("operator work bound".into());
                }
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({
            "componentBytes": bytes.len(), "coreFunctions": functions,
            "bodyOperators": operators, "locals": locals,
            "inspectionNanos": start.elapsed().as_nanos(),
            "validated": false,
        })
    );
    Ok(())
}
