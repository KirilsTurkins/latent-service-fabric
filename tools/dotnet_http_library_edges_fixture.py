"""Normal application error handling for Refit's response-body transport errors."""
import json
from tools import dotnet_published_http_fixture as original
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE_SHA256 = 'sha256:83f67ddf3affc53928997e18ab40da1cbbb6276bda3364f943798780f5a028fb'
BEFORE = b'if (response.Error is ApiException responseError) {'
AFTER = BEFORE + b'\n                    if (responseError.InnerException is HttpRequestException or IOException)\n                        return prefix + "transport-error";'


def managed_source(source):
    require(type(source) is bytes and digest(source)==SOURCE_SHA256 and source.count(BEFORE)==1,
        'dotnet-library-edges-original-application-preimage')
    return source.replace(BEFORE,AFTER,1)


def project(directory):
    app=original.project(directory)
    source=managed_source(read_file(ROOT/original.ROOT_SOURCE))
    (app/'src/Main.cs').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf8',newline='\n')
    return app


install=original.install
