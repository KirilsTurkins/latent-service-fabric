//! Standard fields preserve duplicate values, casing, order and child lifetime.
use super::{
    quota::Slot,
    state::{MAX_HEADERS, MAX_HEADER_BYTES},
};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};

type Entries = Vec<(String, Vec<u8>)>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HeaderError {
    InvalidSyntax,
    Forbidden,
    Immutable,
}

pub struct Fields {
    entries: Rc<RefCell<Entries>>,
    parent: Option<Rc<Cell<usize>>>,
    mutable: bool,
    _slot: Slot,
}

/// Request/response metadata owns its headers. Each exported immutable view
/// retains the data and increments this exact parent's child count.
pub struct ParentFields {
    entries: Rc<RefCell<Entries>>,
    children: Rc<Cell<usize>>,
}

pub fn token(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= MAX_HEADER_BYTES
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte))
}

pub fn reserved(name: &str) -> bool {
    [
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "authorization",
        "cookie",
        "set-cookie",
        "expect",
        "content-encoding",
        "accept-encoding",
        "x-api-key",
        "x-auth-token",
        "x-amz-security-token",
    ]
    .iter()
    .any(|value| name.eq_ignore_ascii_case(value))
}

fn valid_value(value: &[u8]) -> bool {
    // RFC field values allow obs-text. The typed UTF-8 host boundary is checked
    // separately before dispatch; Fields must not rewrite or lose these bytes.
    value
        .iter()
        .all(|byte| *byte == 9 || *byte >= 32 && *byte != 127)
}

fn validate(entries: &Entries, forbid_reserved: bool) -> Result<(), HeaderError> {
    if entries.len() > MAX_HEADERS {
        return Err(HeaderError::InvalidSyntax);
    }
    let mut bytes = 0_usize;
    for (name, value) in entries {
        if !token(name) || !valid_value(value) {
            return Err(HeaderError::InvalidSyntax);
        }
        if forbid_reserved && reserved(name) {
            return Err(HeaderError::Forbidden);
        }
        bytes = bytes
            .checked_add(name.len())
            .and_then(|v| v.checked_add(value.len()))
            .and_then(|v| v.checked_add(4))
            .ok_or(HeaderError::InvalidSyntax)?;
        if bytes > MAX_HEADER_BYTES {
            return Err(HeaderError::InvalidSyntax);
        }
    }
    Ok(())
}

impl Fields {
    pub fn new() -> Self {
        Self::from_list(Vec::new()).expect("empty bounded fields")
    }

    pub fn from_list(entries: Entries) -> Result<Self, HeaderError> {
        validate(&entries, true)?;
        let slot = Slot::new();
        Ok(Self {
            entries: Rc::new(RefCell::new(entries)),
            parent: None,
            mutable: true,
            _slot: slot,
        })
    }

    pub fn get(&self, name: &str) -> Vec<Vec<u8>> {
        if !token(name) {
            return Vec::new();
        }
        self.entries
            .borrow()
            .iter()
            .filter(|(key, _)| key.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.clone())
            .collect()
    }

    pub fn has(&self, name: &str) -> bool {
        token(name)
            && self
                .entries
                .borrow()
                .iter()
                .any(|(key, _)| key.eq_ignore_ascii_case(name))
    }

    fn writable(&self, name: &str) -> Result<(), HeaderError> {
        if !self.mutable {
            return Err(HeaderError::Immutable);
        }
        if !token(name) {
            return Err(HeaderError::InvalidSyntax);
        }
        if reserved(name) {
            return Err(HeaderError::Forbidden);
        }
        Ok(())
    }

    pub fn set(&self, name: String, values: Vec<Vec<u8>>) -> Result<(), HeaderError> {
        self.writable(&name)?;
        if values.len() > MAX_HEADERS || values.iter().any(|value| !valid_value(value)) {
            return Err(HeaderError::InvalidSyntax);
        }
        let current = self.entries.borrow();
        let mut next: Entries = current
            .iter()
            .filter(|(key, _)| !key.eq_ignore_ascii_case(&name))
            .cloned()
            .collect();
        next.extend(values.into_iter().map(|value| (name.clone(), value)));
        validate(&next, false)?;
        drop(current);
        *self.entries.borrow_mut() = next;
        Ok(())
    }

    pub fn delete(&self, name: &str) -> Result<(), HeaderError> {
        self.writable(name)?;
        self.entries
            .borrow_mut()
            .retain(|(key, _)| !key.eq_ignore_ascii_case(name));
        Ok(())
    }

    pub fn append(&self, name: String, value: Vec<u8>) -> Result<(), HeaderError> {
        self.writable(&name)?;
        let mut next = self.entries.borrow().clone();
        next.push((name, value));
        validate(&next, false)?;
        *self.entries.borrow_mut() = next;
        Ok(())
    }

    pub fn entries(&self) -> Entries {
        self.entries.borrow().clone()
    }

    pub fn deep_clone(&self) -> Self {
        // A response can contain a host-owned reserved name. A deep copy
        // preserves it; handle performs request-specific authority validation.
        let slot = Slot::new();
        Self {
            entries: Rc::new(RefCell::new(self.entries())),
            parent: None,
            mutable: true,
            _slot: slot,
        }
    }

    pub fn into_parent(self) -> ParentFields {
        assert!(
            self.parent.is_none(),
            "immutable header child cannot transfer its parent"
        );
        ParentFields {
            entries: self.entries.clone(),
            children: Rc::new(Cell::new(0)),
        }
    }
}

impl Drop for Fields {
    fn drop(&mut self) {
        if let Some(parent) = &self.parent {
            parent.set(parent.get().checked_sub(1).expect("header child owner"));
        }
    }
}

impl ParentFields {
    pub fn response(entries: Entries) -> Result<Self, HeaderError> {
        validate(&entries, false)?;
        Ok(Self {
            entries: Rc::new(RefCell::new(entries)),
            children: Rc::new(Cell::new(0)),
        })
    }

    pub fn child(&self) -> Fields {
        let slot = Slot::new();
        self.children.set(
            self.children
                .get()
                .checked_add(1)
                .expect("header child count"),
        );
        Fields {
            entries: self.entries.clone(),
            parent: Some(self.children.clone()),
            mutable: false,
            _slot: slot,
        }
    }

    pub fn entries(&self) -> Entries {
        self.entries.borrow().clone()
    }

    pub fn require_no_children(&self) {
        assert_eq!(
            self.children.get(),
            0,
            "HTTP parent still has header children"
        );
    }
}

impl Drop for ParentFields {
    fn drop(&mut self) {
        self.require_no_children();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicates_binary_values_casing_and_serial_order_are_preserved() {
        let rows = vec![("X-Item".into(), vec![0x80]), ("x-item".into(), Vec::new())];
        let fields = Fields::from_list(rows.clone()).unwrap();
        assert_eq!(fields.entries(), rows);
        assert_eq!(fields.get("X-ITEM"), vec![vec![0x80], Vec::new()]);
        assert!(fields.has("x-item"));
        assert!(!fields.has("bad key"));
        assert!(fields.get("bad key").is_empty());
    }

    #[test]
    fn set_delete_append_and_deep_clone_have_independent_mutable_state() {
        let fields = Fields::from_list(vec![("X".into(), b"old".to_vec())]).unwrap();
        let other = fields.deep_clone();
        fields
            .set("x".into(), vec![b"one".to_vec(), b"two".to_vec()])
            .unwrap();
        fields.append("Y".into(), b"three".to_vec()).unwrap();
        assert_eq!(other.get("x"), vec![b"old".to_vec()]);
        assert_eq!(
            fields
                .entries()
                .iter()
                .map(|(n, _)| n.as_str())
                .collect::<Vec<_>>(),
            vec!["x", "x", "Y"]
        );
        fields.delete("X").unwrap();
        assert_eq!(fields.entries(), vec![("Y".into(), b"three".to_vec())]);
    }

    #[test]
    fn invalid_or_forbidden_mutations_preserve_the_prior_values() {
        let fields = Fields::from_list(vec![("X".into(), b"safe".to_vec())]).unwrap();
        assert_eq!(
            fields.append("X".into(), b"bad\r\n".to_vec()),
            Err(HeaderError::InvalidSyntax)
        );
        assert_eq!(
            fields.set("Authorization".into(), vec![b"value".to_vec()]),
            Err(HeaderError::Forbidden)
        );
        assert_eq!(fields.delete("bad key"), Err(HeaderError::InvalidSyntax));
        assert_eq!(fields.entries(), vec![("X".into(), b"safe".to_vec())]);
    }

    #[test]
    fn children_are_immutable_and_parent_transfer_requires_their_retirement() {
        let parent = Fields::new().into_parent();
        let child = parent.child();
        assert_eq!(
            child.append("X".into(), Vec::new()),
            Err(HeaderError::Immutable)
        );
        assert_eq!(
            child.set("X".into(), vec![Vec::new()]),
            Err(HeaderError::Immutable)
        );
        assert_eq!(child.delete("X"), Err(HeaderError::Immutable));
        assert_eq!(parent.children.get(), 1);
        drop(child);
        parent.require_no_children();
    }

    #[test]
    fn count_and_byte_bounds_do_not_replace_original_fields() {
        let fields = Fields::new();
        assert_eq!(
            fields.set("X".into(), vec![Vec::new(); MAX_HEADERS + 1]),
            Err(HeaderError::InvalidSyntax)
        );
        assert_eq!(
            fields.append("X".into(), vec![b'a'; MAX_HEADER_BYTES]),
            Err(HeaderError::InvalidSyntax)
        );
        assert!(fields.entries().is_empty());
    }
}
