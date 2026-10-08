"""Retain pinned native text codecs required by actual typed string bindings."""
from tools.typescript_guest.activation_engine import identity,replace_once
import hashlib

SOURCES=(
 'StarlingMonkey/builtins/web/text-codec/text-codec.cpp',
 'StarlingMonkey/builtins/web/text-codec/text-encoder.cpp',
 'StarlingMonkey/builtins/web/text-codec/text-decoder.cpp',
)
PREIMAGES={
 SOURCES[0]:'03774a3a9dc65b6cc7aca8f35d8c7d342817841be566b397048ed4c495d69f88',
 SOURCES[1]:'9d1c43e553276b1b249f04a99df08aeb96bef569f7d14611d1962730b32f51d6',
 SOURCES[2]:'057004705f7508453514c0b4f21685e2010691e571b43422dab4c83edc57443f',
 'StarlingMonkey/cmake/builtins.cmake':'289a6dbd59fed4f7c976f5b3dc2118f6600bce9b0d661e94e6c331f98d879b23',
}


def extend_native_text_codec_source(base:dict[str,bytes],builtin_selection:bytes)->tuple[dict[str,bytes],dict]:
    """Add the original full native codec definitions before app initialization."""
    if not set(PREIMAGES)<=base.keys():
        raise ValueError('pinned-native-text-codec-source-required')
    for name,expected in PREIMAGES.items():
        if hashlib.sha256(base[name]).hexdigest()!=expected:
            raise ValueError('unreviewed-native-text-codec-source:'+name)
    if not isinstance(builtin_selection,bytes) or b'NS_DEF(builtins::web::text_codec)'in builtin_selection:
        raise ValueError('native-text-codec-already-selected-or-invalid')
    selection=replace_once(builtin_selection,b'NS_DEF(componentize::embedding)\n',
        b'NS_DEF(builtins::web::text_codec)\nNS_DEF(componentize::embedding)\n',
        'original-native-text-codec-before-component-bindings')
    result=dict(base);result['builtins.incl']=selection
    return result,{'originalSource':identity(base),'derivedSource':identity(result),
        'originalBuiltinSelectionDigest':hashlib.sha256(builtin_selection).hexdigest(),
        'selectedBuiltinSelectionDigest':hashlib.sha256(selection).hexdigest(),
        'compilerSourceFilesToAdd':list(SOURCES),'originalNativeCodecDefinitionsUnchanged':True,
        'applicationLibraryPatchOrAmbientImportAdded':False,'qualification':'unknown',
        'standardTextCodecOrSignedLSFQualificationClaimed':False}
