"""Source-bound derived compiler tool input; never runtime API qualification."""
from __future__ import annotations
import hashlib
from pathlib import PurePosixPath
import re

SCHEMA='latent.typescript.source-splicer-input.v1'
DIGEST=re.compile(r'^sha256:[0-9a-f]{64}$')
COMPONENTIZE_TREE='4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2'
MODULE='spidermonkey-embedding-splicer.js'

def identity(files:dict[str,bytes])->list[dict]:
    total=0;rows=[]
    if not isinstance(files,dict) or not files or len(files)>32:
        raise ValueError('typescript-source-splicer-file-limit')
    for name,raw in sorted(files.items()):
        path=PurePosixPath(name)
        if (not isinstance(raw,bytes) or not raw or path.is_absolute() or '..' in path.parts
                or str(path)!=name or ':' in name or len(name)>256):
            raise ValueError('typescript-source-splicer-file-shape')
        total+=len(raw)
        if len(raw)>64*1024**2 or total>64*1024**2:
            raise ValueError('typescript-source-splicer-byte-limit')
        if name.endswith('.wasm') and (len(raw)<8 or raw[:4]!=b'\0asm'):
            raise ValueError('typescript-source-splicer-Wasm-required')
        rows.append({'path':name,'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    if MODULE not in files or not any(name.endswith('.wasm') for name in files):
        raise ValueError('typescript-source-splicer-JS-and-Wasm-required')
    return rows

def validate(value:dict,files:dict[str,bytes],sdk_inputs:dict[str,bytes])->dict:
    fields={'schemaVersion','componentizeTree','files','sdkInputs','sourceDerivationDigest',
            'buildReceiptDigest','transpileReceiptDigest','qualification','apiSupport','inputTrust'}
    if not isinstance(value,dict) or set(value)!=fields or value['schemaVersion']!=SCHEMA:
        raise ValueError('typescript-source-splicer-input-schema')
    if value['componentizeTree']!=COMPONENTIZE_TREE or value['files']!=identity(files):
        raise ValueError('typescript-source-splicer-compiler-identity')
    expected=[{'path':name,'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'size':len(raw)}
              for name,raw in sorted(sdk_inputs.items())]
    if not expected or value['sdkInputs']!=expected:
        raise ValueError('typescript-source-splicer-SDK-source-mismatch')
    for name in ('sourceDerivationDigest','buildReceiptDigest','transpileReceiptDigest'):
        if not isinstance(value[name],str) or not DIGEST.fullmatch(value[name]):
            raise ValueError('typescript-source-splicer-recipe-material-required')
    if (value['qualification'],value['apiSupport'],value['inputTrust'])!=('unknown','not-evaluated','operator-asserted'):
        raise ValueError('typescript-source-splicer-input-cannot-certify-api')
    return value

def input_paths()->tuple[str,...]:
    return ('tools/typescript_guest/import_bindgen.py','tools/typescript_guest/import_engine.py',
            'sdk/typescript-guest/activation/async_import_descriptor.rs',
            'sdk/typescript-guest/activation/async_import_splice.rs')
