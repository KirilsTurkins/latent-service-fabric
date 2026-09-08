use super::Result;
use serde_json::Value;

pub(in super::super) fn assert_idle(sample: &Value) -> Result<()> {
    for field in [
        "active_invocations",
        "live_stores",
        "live_host_states",
        "live_component_instances",
        "live_temporary_buffers",
        "live_cancellation_probes",
    ] {
        if sample["backend"][field] != "0" {
            return Err("activation-owned backend resources remain".into());
        }
    }
    let cells = sample["inventory"]["cellCapacity"]
        .as_array()
        .ok_or("missing cell inventory")?;
    if cells.is_empty()
        || cells
            .iter()
            .any(|cell| cell["active"] != 0 || cell["queueDepth"] != 0 || cell["quarantined"] != 0)
    {
        return Err("cell ownership did not return to idle".into());
    }
    if sample["inventory"]["quotas"]["usage"]["activeActivations"] != 0
        || sample["inventory"]["quotas"]["usage"]["queuedActivations"] != 0
    {
        return Err("admission quota remains reserved".into());
    }
    for field in ["reservedCpuFuel", "reservedMemoryBytes"] {
        zero(&sample["inventory"]["quotas"]["usage"][field])?;
    }
    zero(&sample["inventory"]["cacheSummary"]["preparing"])?;
    let ownership = &sample["ownership"];
    for (owner, field) in [
        ("cancellation", "active_registrations"),
        ("journal", "active"),
        ("journal", "reserved_bytes"),
        ("observer", "active_correlations"),
    ] {
        zero(&ownership[owner][field])?;
    }
    for (owner, used, maximum) in [
        ("journal", "terminal", "maximum_terminal"),
        ("journal", "retained_bytes", "maximum_retained_bytes"),
        ("sink", "entries", "maximum_entries"),
        ("sink", "retained_bytes", "maximum_bytes"),
        ("pipeline", "queue_depth", "queue_capacity"),
    ] {
        if unsigned(&ownership[owner][used])? > unsigned(&ownership[owner][maximum])? {
            return Err("retained measurement resource exceeded configured capacity".into());
        }
    }
    Ok(())
}

fn zero(value: &Value) -> Result<()> {
    if unsigned(value)? != 0 {
        return Err("activation-owned measurement resource remains".into());
    }
    Ok(())
}

fn unsigned(value: &Value) -> Result<u64> {
    let text = value
        .as_str()
        .ok_or("missing decimal ownership observation")?;
    let parsed: u64 = text.parse()?;
    if parsed.to_string() != text {
        return Err("noncanonical ownership observation".into());
    }
    Ok(parsed)
}
