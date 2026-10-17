"""Original external Rust crate revisions for the normal signed watch programme."""
import hashlib
import json
from pathlib import Path
import shutil

PRIMARY = 'outside-watch-primary'
CHILD = 'outside-watch-child'
PRIMARY_SOURCE = b'pub fn answer()->u32 {outside_watch_child::add(3)}\npub fn resource()->&\'static str {include_str!("badge.txt")}\n'
RESOURCE = b'captured watch data'


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def revision(number: int) -> dict:
    if number not in (1, 2):
        raise ValueError('unknown owned watch fixture revision')
    version, increment = ('0.1.0', 39) if number == 1 else ('0.1.1', 40)
    return {'primary': {'Cargo.toml': ('[package]\nname="' + PRIMARY + '"\nversion="' + version + '"\nedition="2021"\n'
        '[dependencies]\n' + CHILD + '={path="../child",version="=' + version + '"}\n').encode(),
        'src/lib.rs': PRIMARY_SOURCE, 'src/badge.txt': RESOURCE},
        'child': {'Cargo.toml': ('[package]\nname="' + CHILD + '"\nversion="' + version + '"\nedition="2021"\n').encode(),
            'src/lib.rs': ('pub fn add(value:u32)->u32 {value+' + str(increment) + '}\n').encode()}}


def restore_revision(inputs: dict, number: int) -> None:
    root = Path(inputs['root'])
    if root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']):
        raise ValueError('owned Rust watch input root changed')
    for name, files in revision(number).items():
        directory = root / name
        if directory.exists() or directory.is_symlink():
            raise ValueError('choose fresh owned Rust watch crate roots')
        directory.mkdir(mode=0o700)
        for relative, raw in files.items():
            path = directory / relative; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw)


def create(application: Path) -> dict:
    root = application.parent / 'outside-watch-inputs'
    root.mkdir(mode=0o700)
    records = {}
    for number in (1, 2):
        for name, files in revision(number).items():
            encoded = json.dumps({relative: digest(raw) for relative, raw in sorted(files.items())},
                sort_keys=True, separators=(',', ':')).encode()
            records[name + '-v' + str(number)] = digest(encoded)
    result = {'root': str(root), 'ownedRoot': str(root.resolve(strict=True)),
        'primary': str(root / 'primary'), 'child': str(root / 'child'), 'inputDigests': records}
    restore_revision(result, 1)
    return result


def remove_original(inputs: dict, name: str) -> None:
    if name not in {'primary', 'child'}:
        raise ValueError('unknown owned Rust watch crate')
    root = Path(inputs['root']); directory = root / name
    if (root.is_symlink() or root.resolve(strict=True) != Path(inputs['ownedRoot']) or directory.is_symlink()
            or directory.resolve(strict=True).parent != root.resolve(strict=True)):
        raise ValueError('owned Rust watch removal escaped its original root')
    shutil.rmtree(directory)


def application_source(*, removed=False) -> str:
    body = 'Ok(format!("removed/{name}"))' if removed else (
        'Ok(format!("{}/{name}/{}", outside_watch_primary::answer(),outside_watch_primary::resource()))')
    return '''use std::sync::atomic::{AtomicU32,Ordering};
static CALLS:AtomicU32=AtomicU32::new(0);
pub fn greet(name:String)->Result<String,String>{
  if CALLS.fetch_add(1,Ordering::Relaxed)!=0{return Err("activation-state-reused".into());}
  let name=name.trim();
  if name.is_empty() || name.len()>100{return Err("invalid-watch-input".into());}
  ''' + body + '''
}
#[cfg(target_arch="wasm32")]
mod component {
  wit_bindgen::generate!({path:"wit",world:"service"});
  struct Capsule;
  impl exports::examples::greeting::api::Guest for Capsule {
    fn greet(name:String)->Result<String,String>{super::greet(name)}
  }
  export!(Capsule);
}
'''
