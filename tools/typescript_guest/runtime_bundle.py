"""Explicit, source-bound candidate tools; presence never certifies API support."""
from pathlib import Path
import json

from tools.rust_capsule_project import read_file
from tools.typescript_guest import runtime_profile as runtime
from tools.typescript_guest.activation_engine import engine_input_paths
from tools.typescript_guest.import_profile import splicer_files, validate_splicer

ROOT=Path(__file__).resolve().parents[2]
MANIFEST='runtime-bundle.json'
SCHEMA='latent.typescript.runtime-tool-inputs.v1'


def regular_files(root:Path)->dict[str,bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError('typescript-runtime-bundle-directory-required')
    files={};total=0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('typescript-runtime-bundle-link-forbidden')
        if path.is_file():
            raw=read_file(path,64*1024**2);total+=len(raw)
            files[path.relative_to(root).as_posix()]=raw
        elif not path.is_dir():raise ValueError('typescript-runtime-bundle-special-file')
        if len(files)>48 or total>128*1024**2:
            raise ValueError('typescript-runtime-bundle-input-limit')
    return files


def validate(root:Path, *, sdk_root:Path=ROOT)->dict:
    files=regular_files(root)
    raw=files.get(MANIFEST)
    if raw is None or len(raw)>65536:
        raise ValueError('typescript-runtime-bundle-manifest-required')
    from tools.dev_workflow.common import decode
    value=decode(raw,65536)
    required={'schemaVersion','profile','files','qualification','apiSupport'}
    if (not isinstance(value,dict) or set(value)!=required or value['schemaVersion']!=SCHEMA or
        value['profile'] not in runtime.NATIVE_PROFILES or
        (value['qualification'],value['apiSupport'])!=('unknown','not-evaluated')):
        raise ValueError('typescript-runtime-bundle-profile-or-schema')
    rows=[{'path':name,'digest':runtime.digest(content),'size':len(content)}
          for name,content in sorted(files.items()) if name!=MANIFEST]
    if value['files']!=rows:
        raise ValueError('typescript-runtime-bundle-byte-identity')
    profile=value['profile']
    required_files={'engine.wasm','engine-input.json'}
    if not any(name.startswith('licenses/')for name in files):
        raise ValueError('typescript-runtime-bundle-original-notices-required')
    if profile==runtime.IMPORT_PROFILE:
        required_files.add('splicer-input.json')
        if not any(name.startswith('splicer/')for name in files):
            raise ValueError('typescript-runtime-bundle-source-splicer-required')
    if not required_files<=files.keys() or any(name not in required_files|{MANIFEST}
            and not name.startswith('licenses/')
            and not (profile==runtime.IMPORT_PROFILE and name.startswith('splicer/'))for name in files):
        raise ValueError('typescript-runtime-bundle-unexpected-or-missing-file')
    envelope=decode(files['engine-input.json'],65536)
    sdk={name:read_file(sdk_root/name)for name in engine_input_paths(profile)}
    runtime.validate_engine(envelope,files['engine.wasm'],sdk,
        read_file(sdk_root/'wit/platform/activation-runtime/package.wit'),profile=profile)
    if profile==runtime.IMPORT_PROFILE:
        splicer=splicer_files(root/'splicer')
        validate_splicer(decode(files['splicer-input.json'],65536),splicer,sdk_root)
        if envelope['compilerSplicerInputDigest']!=runtime.digest(files['splicer-input.json']):
            raise ValueError('typescript-runtime-bundle-engine-splicer-mismatch')
    return value


def compiler_options(staged:Path,project:Path)->dict:
    """Select only the explicit project profile from authenticated staged tools."""
    from tools.dev_workflow.common import decode
    value=decode(read_file(project/'capsule-project.json',65536),65536)
    profile=runtime.selected_profile(value)
    if profile==runtime.SYNC_PROFILE:return {}
    root=staged/'typescript-runtime'
    bundle=validate(root)
    if bundle['profile']!=profile:
        raise ValueError('typescript-runtime-bundle-project-profile-mismatch')
    options={'runtime_engine':root/'engine.wasm','runtime_engine_receipt':root/'engine-input.json'}
    if profile==runtime.IMPORT_PROFILE:
        options.update(runtime_splicer=root/'splicer',runtime_splicer_receipt=root/'splicer-input.json')
    return options
