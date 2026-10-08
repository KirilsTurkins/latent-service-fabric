"""Private automatic compiler integration for the source-owned import candidate.

The public project selector does not advertise this candidate until its real
engine/component matrix passes. All observations remain unknown/not-evaluated.
"""
from __future__ import annotations
from pathlib import Path
from tools.typescript_guest.import_engine import IMPORT_PROFILE,NATIVE_IMPORT_SOURCES
from tools.typescript_guest import splicer_input
from tools.rust_capsule_project import read_file
import hashlib

def source_paths()->tuple[str,...]:
    from tools.typescript_guest.activation_engine import engine_input_paths
    from tools.typescript_guest.runtime_profile import CLOCK_PROFILE
    paths=engine_input_paths(CLOCK_PROFILE)+tuple('sdk/typescript-guest/activation/'+name for name in NATIVE_IMPORT_SOURCES)
    return tuple(dict.fromkeys(paths+splicer_input.input_paths()+('tools/typescript_guest/splicer_input.py','tools/typescript_guest/import_profile.py')))

def splicer_files(root:Path)->dict[str,bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError('typescript-source-splicer-directory-required')
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('typescript-source-splicer-link-forbidden')
        if path.is_file():
            files[path.relative_to(root).as_posix()]=read_file(path,64*1024**2)
        elif not path.is_dir():raise ValueError('typescript-source-splicer-special-file')
        if len(files)>32:raise ValueError('typescript-source-splicer-file-limit')
    splicer_input.identity(files)
    return files

def validate_splicer(value:dict,files:dict[str,bytes],sdk_root:Path)->dict:
    return splicer_input.validate(value,files,{name:read_file(sdk_root/name) for name in splicer_input.input_paths()})

def compiler_observation(engine:dict,splicer:dict)->dict:
    if engine['qualification']!='unknown' or splicer['qualification']!='unknown':
        raise ValueError('typescript-import-profile-cannot-infer-qualification')
    return {'profile':IMPORT_PROFILE,'ownerIssue':745,'qualification':'unknown','apiSupport':'not-evaluated',
            'authority':'none','engineInput':engine,'compilerSplicerInput':splicer,
            'sourceOnlyOrStaticInputEvidenceCannotCertifyRuntime':True}

def componentizer_adapter(original:bytes)->tuple[bytes,dict]:
    """Expose the real core and explicit source-built splicer without mutation.

    The caller writes a fresh copy into its owned protected compiler staging
    directory. All original public compiler inputs remain separately verified.
    """
    expected='e58ef4f3b126f4a3fd07c61b368930bbf02dd0029f0f03e4c6928528e994e559'
    if hashlib.sha256(original).hexdigest()!=expected:
        raise ValueError('unreviewed-componentize-js-source')
    anchors=[
      (b"import { splicer } from '../lib/spidermonkey-embedding-splicer.js';",
       b"import { splicer as publicSplicer } from '../lib/spidermonkey-embedding-splicer.js';"),
      (b'  const engine = getEnginePath(opts);',
       b'  const engine = getEnginePath(opts);\n  const splicer = opts.lsfSplicer || publicSplicer;'),
      (b'  return {\n    component,\n',b'  return {\n    core: finalBin,\n    component,\n'),
      (b'  await writeFile(initializerPath, jsBindings);',
       b'  jsBindings = opts.lsfBindings(jsBindings);\n  await writeFile(initializerPath, jsBindings);'),
    ]
    source=original
    for before,after in anchors:
        if source.count(before)!=1:raise ValueError('pinned-componentizer-import-hook-shape')
        source=source.replace(before,after,1)
    # The second original splicer use is in the same componentize function.
    # An unrelated public helper must not accidentally acquire this selection.
    return source,{'originalSha256':expected,'derivedSha256':hashlib.sha256(source).hexdigest(),
                   'explicitSourceBuiltSplicerOnly':True,'originalDefinitionsRetained':True,
                   'supportedRuntimeQualified':False,'signedLSFComponentQualified':False}
