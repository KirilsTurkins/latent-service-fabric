use super::*;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Mode {
    format_version: u32,
    enforced: bool,
    receipt_capacity: usize,
    baseline_digest: [u8; 32],
    baseline_count: usize,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Intent {
    format_version: u32,
    mode: [u8; 32],
    old_head: Head,
    new_head: Head,
    old_row_digest: Option<[u8; 32]>,
    new_row: Option<StoredRow>,
    slot: usize,
    old_receipt_digest: Option<[u8; 32]>,
    new_receipt: StoredReceipt,
}
fn row_name(release: &ReleaseDigest) -> Result<String, PlatformError> {
    release
        .0
        .parse::<ArtifactBlobDigest>()
        .map_err(|_| corrupt())?;
    Ok(format!("{}.json", &release.0[7..]))
}
pub(super) fn row_path(root: &Path, release: &ReleaseDigest) -> Result<PathBuf, PlatformError> {
    Ok(root.join("records").join(row_name(release)?))
}
fn slot_path(root: &Path, slot: usize) -> PathBuf {
    root.join("receipts").join(format!("{slot:03}.json"))
}

pub(super) fn open(
    root: &Path,
    limits: LifecycleLimits,
    enforced: bool,
    baseline: &[LifecycleIdentity],
) -> Result<State, PlatformError> {
    if baseline.len() > limits.max_records {
        return Err(exhausted());
    }
    let mut identities = BTreeMap::new();
    for identity in baseline {
        validation::identity(identity, enforced)?;
        if identities
            .insert(identity.release.clone(), identity)
            .is_some()
        {
            return Err(corrupt());
        }
    }
    io::create_directory(&root.join("records"))?;
    io::create_directory(&root.join("receipts"))?;
    io::create_directory(&root.join("evidence"))?;
    let mut baseline_hash = sha2::Sha256::new();
    use sha2::Digest;
    baseline_hash.update(b"lsf-lifecycle-baseline-v1\0");
    for identity in identities.values() {
        let bytes = encode(identity, limits.max_record_bytes)?;
        baseline_hash.update((bytes.len() as u64).to_le_bytes());
        baseline_hash.update(bytes);
    }
    let expected_mode = Mode {
        format_version: 1,
        enforced,
        receipt_capacity: limits.max_recent_operations,
        baseline_digest: baseline_hash.finalize().into(),
        baseline_count: baseline.len(),
    };
    let mode_path = root.join("MODE");
    let initialized = io::read(&root.join("INITIALIZED"), 128)?;
    let mode = match io::read(&mode_path, 4096)? {
        Some(bytes) => {
            let mode: Mode = decode(&bytes, 4096)?;
            if mode.format_version != 1
                || mode.enforced != enforced
                || mode.receipt_capacity != limits.max_recent_operations
            {
                return Err(corrupt());
            }
            mode
        }
        None => {
            if initialized.is_some()
                || !io::files(&root.join("records"), limits.max_records + 1)?.is_empty()
                || !io::files(&root.join("receipts"), limits.max_recent_operations + 1)?.is_empty()
                || !io::files(&root.join("evidence"), limits.max_records + 2)?.is_empty()
                || io::read(&root.join("HEAD"), 4096)?.is_some()
                || io::read(&root.join("INTENT"), limits.max_intent_bytes)?.is_some()
            {
                return Err(corrupt());
            }
            io::write(&mode_path, &encode(&expected_mode, 4096)?)?;
            expected_mode.clone()
        }
    };
    let mode_digest = digest(&encode(&mode, 4096)?);
    if let Some(initialized) = initialized {
        if initialized != encode(&mode_digest, 128)? {
            return Err(corrupt());
        }
    } else {
        if mode != expected_mode {
            return Err(corrupt());
        }
        bootstrap(root, limits, &mode_digest, &identities)?;
        io::write(&root.join("INITIALIZED"), &encode(&mode_digest, 128)?)?;
    }
    if let Some(bytes) = io::read(&root.join("INTENT"), limits.max_intent_bytes)? {
        let intent: Intent = decode(&bytes, limits.max_intent_bytes)?;
        recover_intent(root, limits, &mode_digest, &intent)?;
    }
    let head: Head = decode(&io::required(&root.join("HEAD"), 4096)?, 4096)?;
    if head.format_version != 1 || head.mode != mode_digest || head.rows > limits.max_records {
        return Err(corrupt());
    }
    let mut entries = BTreeMap::new();
    let mut row_bytes = 0usize;
    for name in io::files(&root.join("records"), limits.max_records + 1)? {
        if name.ends_with(".next") {
            io::remove(&root.join("records").join(name))?;
            continue;
        }
        let bytes = io::required(&root.join("records").join(&name), limits.max_record_bytes)?;
        let stored: StoredRow = decode(&bytes, limits.max_record_bytes)?;
        validation::identity(&stored.identity, enforced)?;
        validation::record(&stored.record, limits)?;
        if name != row_name(&stored.identity.release)?
            || stored.identity.scope != stored.record.scope
            || stored.identity.release != stored.record.release
            || stored.identity.package != stored.record.package
        {
            return Err(corrupt());
        }
        if identities.get(&stored.identity.release).copied() != Some(&stored.identity) {
            return Err(corrupt());
        }
        row_bytes = row_bytes.checked_add(bytes.len()).ok_or_else(exhausted)?;
        validation::retention(entries.len() + 1, row_bytes, limits)?;
        let key = stored.identity.release.clone();
        let row = Row::new(&stored.record);
        if entries
            .insert(
                key,
                Entry {
                    stored,
                    row,
                    bytes: bytes.len(),
                },
            )
            .is_some()
        {
            return Err(corrupt());
        }
    }
    if entries.len() != head.rows || row_bytes != head.row_bytes || head.rows < mode.baseline_count
    {
        return Err(corrupt());
    }
    let receipts = read_receipts(root, limits, &head)?;
    let state = State {
        head,
        entries,
        receipts,
    };
    validation::recovered_quota(&state, limits)?;
    validate_root_names(root)?;
    Ok(state)
}
fn bootstrap(
    root: &Path,
    limits: LifecycleLimits,
    mode: &[u8; 32],
    identities: &BTreeMap<ReleaseDigest, &LifecycleIdentity>,
) -> Result<(), PlatformError> {
    let mut row_bytes = 0usize;
    for (index, identity) in identities.values().enumerate() {
        row_bytes = row_bytes
            .checked_add(encode(&bootstrap_row(identity), limits.max_record_bytes)?.len())
            .ok_or_else(exhausted)?;
        validation::retention(index + 1, row_bytes, limits)?;
    }
    for identity in identities.values() {
        let stored = bootstrap_row(identity);
        let bytes = encode(&stored, limits.max_record_bytes)?;
        let path = row_path(root, &identity.release)?;
        if let Some(existing) = io::read(&path, limits.max_record_bytes)? {
            if existing != bytes {
                return Err(corrupt());
            }
        } else {
            io::write(&path, &bytes)?;
        }
    }
    let mut count = 0;
    for name in io::files(&root.join("records"), limits.max_records + 1)? {
        if name.ends_with(".next") {
            io::remove(&root.join("records").join(name))?;
        } else {
            count += 1;
        }
    }
    if count != identities.len()
        || !io::files(&root.join("receipts"), limits.max_recent_operations + 1)?.is_empty()
    {
        return Err(corrupt());
    }
    let head = Head {
        format_version: 1,
        mode: *mode,
        sequence: 0,
        receipt_digest: None,
        rows: identities.len(),
        row_bytes,
    };
    let bytes = encode(&head, 4096)?;
    if let Some(existing) = io::read(&root.join("HEAD"), 4096)? {
        if existing != bytes {
            return Err(corrupt());
        }
    } else {
        io::write(&root.join("HEAD"), &bytes)?;
    }
    Ok(())
}
fn bootstrap_row(identity: &LifecycleIdentity) -> StoredRow {
    StoredRow {
        identity: identity.clone(),
        record: ReleaseLifecycleRecord {
            scope: identity.scope.clone(),
            release: identity.release.clone(),
            package: identity.package.clone(),
            state: ReleaseLifecycleState::Admitted,
            generation: 1,
            actor: ReleaseActor {
                subject: "catalog-bootstrap".to_owned(),
                kind: ReleaseActorKind::Host,
            },
            reason: ReleaseLifecycleReason::Admitted,
            operation_id: "bootstrap".to_owned(),
            policy: None,
            observed_at_unix_millis: None,
            evidence_revision_digest: None,
        },
    }
}
fn read_receipts(
    root: &Path,
    limits: LifecycleLimits,
    head: &Head,
) -> Result<BTreeMap<usize, StoredReceipt>, PlatformError> {
    let retained = head.sequence.min(limits.max_recent_operations as u64);
    let mut receipts = BTreeMap::new();
    for name in io::files(&root.join("receipts"), limits.max_recent_operations + 1)? {
        if name.ends_with(".next") {
            io::remove(&root.join("receipts").join(name))?;
            continue;
        }
        let bytes = io::required(
            &root.join("receipts").join(&name),
            limits.max_receipt_bytes + 256,
        )?;
        let receipt: StoredReceipt = decode(&bytes, limits.max_receipt_bytes + 256)?;
        validation::receipt(&receipt.receipt, limits)?;
        if receipt.sequence == 0
            || receipt.sequence > head.sequence
            || receipt.sequence <= head.sequence - retained
        {
            return Err(corrupt());
        }
        let slot = ((receipt.sequence - 1) % limits.max_recent_operations as u64) as usize;
        if name != format!("{slot:03}.json") || receipts.insert(slot, receipt).is_some() {
            return Err(corrupt());
        }
    }
    if receipts.len() != retained as usize {
        return Err(corrupt());
    }
    if head.sequence == 0 {
        if head.receipt_digest.is_some() {
            return Err(corrupt());
        }
    } else {
        let slot = ((head.sequence - 1) % limits.max_recent_operations as u64) as usize;
        let latest = receipts.get(&slot).ok_or_else(corrupt)?;
        if head.receipt_digest != Some(digest(&encode(latest, limits.max_receipt_bytes + 256)?)) {
            return Err(corrupt());
        }
    }
    // Sequence cardinality plus exact window/slot constraints prove contiguous
    // retained history; never guess a new HEAD from whichever slots survived.
    Ok(receipts)
}
pub(super) fn commit(
    root: &Path,
    limits: LifecycleLimits,
    state: &mut State,
    prepared: &LifecyclePrepared,
) -> Result<(), PlatformError> {
    let sequence = state.head.sequence.checked_add(1).ok_or_else(exhausted)?;
    let slot = ((sequence - 1) % limits.max_recent_operations as u64) as usize;
    let new_receipt = StoredReceipt {
        sequence,
        receipt: prepared.receipt.clone(),
    };
    let mut new_head = state.head.clone();
    new_head.sequence = sequence;
    new_head.receipt_digest = Some(digest(&encode(
        &new_receipt,
        limits.max_receipt_bytes + 256,
    )?));
    let new_row = if prepared.receipt.disposition == ReleaseOperationDisposition::Committed {
        let record = prepared.receipt.record.as_ref().ok_or_else(invalid)?;
        let old = state.entries.get(&record.release);
        let identity = prepared
            .identity
            .as_ref()
            .or_else(|| old.map(|entry| &entry.stored.identity))
            .ok_or_else(invalid)?;
        let stored = StoredRow {
            identity: identity.clone(),
            record: record.clone(),
        };
        let size = encode(&stored, limits.max_record_bytes)?.len();
        if let Some(old) = old {
            new_head.row_bytes = new_head
                .row_bytes
                .checked_sub(old.bytes)
                .ok_or_else(corrupt)?;
        } else {
            new_head.rows = new_head.rows.checked_add(1).ok_or_else(exhausted)?;
        }
        new_head.row_bytes = new_head.row_bytes.checked_add(size).ok_or_else(exhausted)?;
        Some(stored)
    } else {
        None
    };
    let old_row_digest = new_row
        .as_ref()
        .and_then(|row| state.entries.get(&row.identity.release))
        .map(|entry| encode(&entry.stored, limits.max_record_bytes).map(|bytes| digest(&bytes)))
        .transpose()?;
    let old_receipt_digest = state
        .receipts
        .get(&slot)
        .map(|receipt| encode(receipt, limits.max_receipt_bytes + 256).map(|bytes| digest(&bytes)))
        .transpose()?;
    let intent = Intent {
        format_version: 1,
        mode: state.head.mode,
        old_head: state.head.clone(),
        new_head: new_head.clone(),
        old_row_digest,
        new_row,
        slot,
        old_receipt_digest,
        new_receipt: new_receipt.clone(),
    };
    io::write(
        &root.join("INTENT"),
        &encode(&intent, limits.max_intent_bytes)?,
    )?;
    fault(1)?;
    recover_intent(root, limits, &state.head.mode, &intent)?;
    if let Some(stored) = intent.new_row {
        let bytes = encode(&stored, limits.max_record_bytes)?.len();
        if let Some(entry) = state.entries.get_mut(&stored.identity.release) {
            entry.row.adopt(&stored.record);
            entry.stored = stored;
            entry.bytes = bytes;
        } else {
            let row = Row::new(&stored.record);
            state.entries.insert(
                stored.identity.release.clone(),
                Entry { stored, row, bytes },
            );
        }
    }
    state.receipts.insert(slot, new_receipt);
    state.head = new_head;
    Ok(())
}
fn recover_intent(
    root: &Path,
    limits: LifecycleLimits,
    mode: &[u8; 32],
    intent: &Intent,
) -> Result<(), PlatformError> {
    if intent.format_version != 1
        || intent.mode != *mode
        || intent.old_head.mode != *mode
        || intent.new_head.mode != *mode
        || intent.new_head.sequence
            != intent
                .old_head
                .sequence
                .checked_add(1)
                .ok_or_else(corrupt)?
        || intent.new_receipt.sequence != intent.new_head.sequence
        || intent.slot
            != ((intent.new_head.sequence - 1) % limits.max_recent_operations as u64) as usize
    {
        return Err(corrupt());
    }
    validation::receipt(&intent.new_receipt.receipt, limits)?;
    let new_receipt = encode(&intent.new_receipt, limits.max_receipt_bytes + 256)?;
    if intent.new_head.receipt_digest != Some(digest(&new_receipt)) {
        return Err(corrupt());
    }
    let current = io::required(&root.join("HEAD"), 4096)?;
    let old_head = encode(&intent.old_head, 4096)?;
    let new_head = encode(&intent.new_head, 4096)?;
    if current != old_head && current != new_head {
        return Err(corrupt());
    }
    if let Some(row) = &intent.new_row {
        if intent.new_receipt.receipt.disposition != ReleaseOperationDisposition::Committed
            || intent.new_receipt.receipt.record.as_ref() != Some(&row.record)
        {
            return Err(corrupt());
        }
        replace_checked(
            &row_path(root, &row.identity.release)?,
            intent.old_row_digest,
            &encode(row, limits.max_record_bytes)?,
            limits.max_record_bytes,
        )?;
    } else if intent.old_row_digest.is_some()
        || intent.new_receipt.receipt.disposition != ReleaseOperationDisposition::Rejected
    {
        return Err(corrupt());
    }
    fault(2)?;
    replace_checked(
        &slot_path(root, intent.slot),
        intent.old_receipt_digest,
        &new_receipt,
        limits.max_receipt_bytes + 256,
    )?;
    fault(3)?;
    replace_checked(&root.join("HEAD"), Some(digest(&old_head)), &new_head, 4096)?;
    fault(4)?;
    io::remove(&root.join("INTENT"))?;
    Ok(())
}
fn replace_checked(
    path: &Path,
    old: Option<[u8; 32]>,
    new: &[u8],
    maximum: usize,
) -> Result<(), PlatformError> {
    let current = io::read(path, maximum)?;
    if current.as_deref() == Some(new) {
        return Ok(());
    }
    if current.as_ref().map(|bytes| digest(bytes)) != old {
        return Err(corrupt());
    }
    io::write(path, new)
}
fn validate_root_names(root: &Path) -> Result<(), PlatformError> {
    for name in io::files(root, 16)? {
        match name.as_str() {
            "MODE" | "INITIALIZED" | "HEAD" | "records" | "receipts" | "evidence" => {}
            "MODE.next" | "INITIALIZED.next" | "HEAD.next" | "INTENT.next" => {
                io::remove(&root.join(name))?
            }
            _ => return Err(corrupt()),
        }
    }
    Ok(())
}
#[cfg(test)]
thread_local! {pub(super) static FAIL:Cell<u8>=const{Cell::new(0)};}
fn fault(point: u8) -> Result<(), PlatformError> {
    #[cfg(test)]
    if FAIL.with(|value| {
        if value.get() == point {
            value.set(0);
            true
        } else {
            false
        }
    }) {
        return Err(unavailable());
    }
    let _ = point;
    Ok(())
}
