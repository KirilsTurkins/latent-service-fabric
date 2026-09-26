use super::{
    fs,
    fs::Directory,
    model::{self, OwnerRecord, StageRecord},
    parse, read, record, Arc, AtomicBool, AtomicUsize, Inner, LocalBlobError, LocalBlobLimits,
    LocalBlobStore, Mutex, Object, Path, ReferenceRecord, Result, Stage, State, OBJECT_BYTES,
    OWNER_BYTES, RECORD_BYTES, STAGE_BYTES,
};

pub(super) fn open(
    path: &Path,
    namespace: &str,
    limits: LocalBlobLimits,
) -> Result<Arc<LocalBlobStore>> {
    let root = Directory::root(path)?;
    let lock = root.open_file("LOCK", true, !root.present("LOCK")?, 0)?;
    lock.try_lock().map_err(|_| LocalBlobError::Busy)?;
    let names = root.names(4)?;
    if names
        .iter()
        .any(|n| !["LOCK", "OWNER.json", "objects", "staging"].contains(&n.as_str()))
    {
        return Err(LocalBlobError::Corrupt);
    }
    if !names.iter().any(|n| n == "OWNER.json") {
        if names.iter().any(|n| n != "LOCK") {
            return Err(LocalBlobError::Corrupt);
        }
        root.write_new(
            "OWNER.json",
            &record(&OwnerRecord {
                version: 1,
                namespace: namespace.into(),
            })?,
        )?;
        root.sync()?;
    }
    let owner: OwnerRecord = parse(&root, "OWNER.json")?;
    if owner.version != 1 || owner.namespace != namespace {
        return Err(LocalBlobError::PermissionDenied);
    }
    let objects = root.child("objects", !root.present("objects")?)?;
    let staging = root.child("staging", !root.present("staging")?)?;
    let inner = Arc::new(Inner {
        root,
        objects,
        staging,
        namespace: namespace.into(),
        limits,
        state: Mutex::new(State::default()),
        handles: AtomicUsize::new(0),
        work: AtomicUsize::new(0),
        publishing: AtomicBool::new(false),
        pending_objects: AtomicUsize::new(0),
        poisoned: AtomicBool::new(false),
        closed: AtomicBool::new(false),
        _lock: lock,
    });
    let state = recover_inventory(&inner)?;
    // Re-establish the directory durability boundary before admitting recovered
    // references, including a rename that may have outlived a lost response.
    inner.objects.sync()?;
    inner.staging.sync()?;
    *inner.state()? = state;
    Ok(Arc::new(LocalBlobStore { inner }))
}
fn recover_inventory(inner: &Inner) -> Result<State> {
    let limits = inner.limits;
    let mut state = State::default();
    let object_capacity = limits
        .maximum_objects
        .min((limits.maximum_metadata_bytes - OWNER_BYTES) / OBJECT_BYTES);
    for key in inner.objects.names(object_capacity)? {
        inner.room(&state, OBJECT_BYTES)?;
        if !model::hex(&key, 64) {
            return Err(LocalBlobError::Corrupt);
        }
        let directory = inner.objects.child(&key, false)?;
        let names = inventory(&directory, true, limits.maximum_object_bytes)?;
        let released = names.is_empty() || names.iter().any(|n| n == "RELEASED");
        let object = if released {
            Object {
                record: None,
                bytes: payload_size(&directory)?,
                pins: AtomicUsize::new(0),
                referenced: AtomicBool::new(false),
                identity: None,
            }
        } else {
            let reference: ReferenceRecord = parse(&directory, "REFERENCE.json")?;
            reference.validate(&inner.namespace, limits.maximum_object_bytes)?;
            if reference.key() != key {
                return Err(LocalBlobError::Corrupt);
            }
            let source: StageRecord = parse(&directory, "STAGE.json")?;
            validate_stage(&source, &reference, limits.maximum_object_bytes)?;
            state.next = state.next.max(source.id);
            let (_, identity) = read::verify(&directory, &reference, &|| Ok(()))?;
            state.referenced += 1;
            Object {
                bytes: reference.size,
                record: Some(reference),
                pins: AtomicUsize::new(0),
                referenced: AtomicBool::new(true),
                identity: Some(identity),
            }
        };
        inner.disk_room(&state, 1, object.bytes)?;
        state.resident = state
            .resident
            .checked_add(object.bytes)
            .filter(|n| *n <= limits.maximum_disk_bytes)
            .ok_or(LocalBlobError::Capacity)?;
        state.objects.insert(key, Arc::new(object));
    }
    let stage_capacity = limits
        .maximum_stages
        .min((limits.maximum_metadata_bytes - inner.metadata(&state)?) / STAGE_BYTES);
    for name in inner.staging.names(stage_capacity)? {
        inner.room(&state, STAGE_BYTES)?;
        if !model::hex(&name, 16) {
            return Err(LocalBlobError::Corrupt);
        }
        let id = u64::from_str_radix(&name, 16).map_err(|_| LocalBlobError::Corrupt)?;
        if id == 0 {
            return Err(LocalBlobError::Corrupt);
        }
        let directory = inner.staging.child(&name, false)?;
        inventory(&directory, false, limits.maximum_object_bytes)?;
        let maximum = payload_size(&directory)?;
        inner.disk_room(&state, 1, maximum)?;
        state.reserved = state
            .reserved
            .checked_add(maximum)
            .filter(|n| *n <= limits.maximum_stage_bytes)
            .ok_or(LocalBlobError::Capacity)?;
        if state
            .reserved
            .checked_add(state.resident)
            .is_none_or(|n| n > limits.maximum_disk_bytes)
        {
            return Err(LocalBlobError::Capacity);
        }
        state.next = state.next.max(id);
        state.stages.insert(
            id,
            Stage {
                maximum,
                active: Arc::new(AtomicBool::new(false)),
            },
        );
    }
    Ok(state)
}
pub(super) fn inventory(directory: &Directory, object: bool, maximum: u64) -> Result<Vec<String>> {
    let names = directory.names(if object { 4 } else { 3 })?;
    for name in &names {
        let bound = match name.as_str() {
            "data" => maximum,
            "STAGE.json" | "REFERENCE.json" => RECORD_BYTES as u64,
            "RELEASED" if object => 64,
            _ => return Err(LocalBlobError::Corrupt),
        };
        directory.open_file(name, false, false, bound)?;
    }
    Ok(names)
}
fn payload_size(directory: &Directory) -> Result<u64> {
    if directory.present("data")? {
        Ok(directory
            .open_file("data", false, false, u64::MAX)?
            .metadata()
            .map_err(fs::failure)?
            .len())
    } else {
        Ok(0)
    }
}
fn validate_stage(stage: &StageRecord, reference: &ReferenceRecord, maximum: u64) -> Result<()> {
    if stage.version != 1
        || stage.id == 0
        || stage.tenant != reference.tenant
        || stage.media_type != reference.media_type
        || stage.maximum_size > maximum
        || reference.size > stage.maximum_size
        || stage
            .expected_size
            .is_some_and(|size| size != reference.size)
    {
        return Err(LocalBlobError::Corrupt);
    }
    Ok(())
}
