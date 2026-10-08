"""Exact source derivation of pinned ComponentizeJS async import bindings.

The source-owned splicer remains private until its actual typed/native matrix
passes. This helper prepares source bytes and never promotes a profile.
"""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once
from tools.typescript_guest.import_engine import SOURCE_PREIMAGES


def derive_async_bindgen(original: bytes) -> tuple[bytes,dict]:
    path='crates/spidermonkey-embedding-splicer/src/bindgen.rs'
    if hashlib.sha256(original).hexdigest()!=SOURCE_PREIMAGES[path]:
        raise ValueError('unreviewed-original-async-bindgen')
    source=original
    # All original synchronous imports/exports keep their existing machinery.
    # An actual async function supplies only its own source projection to that
    # machinery; the native descriptor retains the actual P3 ABI separately.
    start=source.index(b'    fn import_bindgen(')
    end=source.index(b'    fn create_resource_map(',start)
    body=source[start:end]
    old=b'        let fn_name = func.item_name();\n'
    new=b'''        let is_lsf_async = matches!(func.kind, FunctionKind::AsyncFreestanding |
            FunctionKind::AsyncMethod(_) | FunctionKind::AsyncStatic(_));
        let original_func = func;
        let mut synchronous = func.clone();
        synchronous.kind = match func.kind {
            FunctionKind::AsyncFreestanding => FunctionKind::Freestanding,
            FunctionKind::AsyncMethod(id) => FunctionKind::Method(id),
            FunctionKind::AsyncStatic(id) => FunctionKind::Static(id),
            _ => func.kind.clone(),
        };
        let func = &synchronous;
        let fn_name = func.item_name();
'''
    body=replace_once(body,old,new,'parser-async-function-preserving-projection')
    body=replace_once(body,b'        // All imports are sync\n        let requires_async_porcelain = false;',
        b'        // Actual native async imports return real pending engine Promises.\n'
        b'        let requires_async_porcelain = is_lsf_async;','native-import-await-selection')
    body=replace_once(body,b'uwrite!(self.src, "\\nfunction import_{binding_name}");',
        b'uwrite!(self.src, "\\n{}function import_{binding_name}", if is_lsf_async { "async " } else { "" });',
        'async-import-function')
    body=replace_once(body,b'uwrite!(self.src, "{fn_camel_name}({args}) {{\\nfunction helper");',
        b'uwrite!(self.src, "{}{}({args}) {{\\n{}function helper", if is_lsf_async { "async " } else { "" }, fn_camel_name, if is_lsf_async { "async " } else { "" });',
        'async-import-resource-method')
    body=replace_once(body,b'uwrite!(self.src, "static {fn_camel_name}");',
        b'uwrite!(self.src, "static {}{fn_camel_name}", if is_lsf_async { "async " } else { "" });',
        'async-import-static-method')
    # The native source operation itself carries the actual descriptor, while
    # original public resource identities/lifting remain in BindingItem.
    body=replace_once(body,b'        let sig = self.resolve.wasm_signature(AbiVariant::GuestImport, func);',
        b'        let sig = self.resolve.wasm_signature(AbiVariant::GuestImport, func);\n'
        b'        if is_lsf_async {\n'
        b'            self.lsf_async_imports.insert((import_name.clone(), func.name.clone()),\n'
        b'                lsf_async::descriptor(self.resolve, original_func, &self.sizes));\n'
        b'        }', 'actual-native-async-descriptor')
    source=source[:start]+body+source[end:]
    # Export continuation stays the original generic root Promise machinery.
    # Accept actual async parser kinds instead of requiring a whole-world sync
    # projection that would erase the native import descriptors above.
    start=source.index(b'    fn exports_bindgen(')
    end=source.index(b'    fn ',start+9)
    body=source[start:end]
    body=body.replace(b'FunctionKind::Freestanding => {',
        b'FunctionKind::Freestanding | FunctionKind::AsyncFreestanding => {')
    body=body.replace(b'| FunctionKind::Constructor(ty) => {',
        b'| FunctionKind::Constructor(ty) | FunctionKind::AsyncMethod(ty) | FunctionKind::AsyncStatic(ty) => {')
    for row in (b'                            FunctionKind::AsyncFreestanding => todo!(),\n',
                b'                            FunctionKind::AsyncMethod(_id) => todo!(),\n',
                b'                            FunctionKind::AsyncStatic(_id) => todo!(),\n'):
        if body.count(row)!=1: raise ValueError('pinned-async-export-dispatch-shape')
        body=body.replace(row,b'',1)
    source=source[:start]+body+source[end:]
    start=source.index(b'    fn export_bindgen(')
    end=source.index(b'    fn ',start+9)
    body=source[start:end]
    body=replace_once(body,b'        let fn_name = func.item_name();\n',
        b'''        let mut synchronous = func.clone();
        synchronous.kind = match func.kind {
            FunctionKind::AsyncFreestanding => FunctionKind::Freestanding,
            FunctionKind::AsyncMethod(id) => FunctionKind::Method(id),
            FunctionKind::AsyncStatic(id) => FunctionKind::Static(id),
            _ => func.kind.clone(),
        };
        let func = &synchronous;
        let fn_name = func.item_name();
''','root-Promise-export-kind-preserving-projection')
    source=source[:start]+body+source[end:]
    # A small separately maintained helper owns original P3 layout selection,
    # full result decoding and explicit unsupported shapes until implemented.
    source=replace_once(source,b'use crate::{uwrite, uwriteln};',
        b'use crate::{uwrite, uwriteln};\nuse crate::lsf_async;','owned-import-descriptor-module')
    source=replace_once(source,b'    // imports "specifier"\n    imports: Vec<(String, BindingItem)>,',
        b'    // imports "specifier"\n    imports: Vec<(String, BindingItem)>,\n'
        b'    lsf_async_imports: BTreeMap<(String, String), lsf_async::Descriptor>,','descriptor-storage')
    source=replace_once(source,b'        imports: Vec::new(),',
        b'        imports: Vec::new(),\n        lsf_async_imports: BTreeMap::new(),','descriptor-initialization')
    source=replace_once(source,b'    pub resource_imports: Vec<(String, String, u32)>,',
        b'    pub resource_imports: Vec<(String, String, u32)>,\n'
        b'    pub lsf_async_imports: BTreeMap<(String, String), lsf_async::Descriptor>,','actual-descriptor-output')
    source=replace_once(source,b'        resource_imports,\n    })',
        b'        resource_imports,\n        lsf_async_imports: bindgen.lsf_async_imports,\n    })','descriptor-output-move')
    # Native helper access is compiler-local. Application modules never receive
    # a manual task pump, broker token or ambient capability.
    source=replace_once(source,b'            delete globalThis.$bindings;\n',
        b'            delete globalThis.$bindings;\n'
        b'            const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\n'
        b'            delete contentGlobal.__lsfAsyncImportBridge;\n','private-bridge-capture')
    # Original FunctionBindgen retains all type operations. Its genuine async
    # porcelain awaits a local closure returning a native Promise. Reservations
    # precede generated lowering; finish follows every typed-lift exit.
    source=replace_once(source,b'        let tracing_prefix = String::new();\n',
        b'''        let lsf_async_call = requires_async_porcelain && abi == AbiVariant::GuestExport;
        let original_callee = callee;
        let adapted_callee = if lsf_async_call { "__lsfAwaitImport" } else { callee };
        let callee = adapted_callee;
        let tracing_prefix = String::new();
''','real-native-await-callee')
    source=replace_once(source,b'        self.src.push_str(&f.src);\n        self.src.push_str("}");',
        b'''        if lsf_async_call {
            let descriptor = lsf_async::descriptor(self.resolve, func, &self.sizes);
            uwriteln!(self.src, "const __lsfImportId = __lsfImports.reserve({}, {}, {}, {});",
                descriptor.result_bytes, descriptor.parameter_bytes, descriptor.raw_result,
                (0..nparams).map(|i| format!("arg{i}")).collect::<Vec<_>>().join(", "));
            uwriteln!(self.src, "const __lsfAwaitImport = async (...lowered) => __lsfImports.lift(await {original_callee}(__lsfImportId | 0, ...lowered));");
            uwriteln!(self.src, "try {{");
        }
        self.src.push_str(&f.src);
        if lsf_async_call {
            uwriteln!(self.src, "}} finally {{ __lsfImports.finish(__lsfImportId); }}");
        }
        self.src.push_str("}");''','preallocation-and-typed-lift-retirement')
    receipt={'status':'private-derived-bindgen-source','originalSha256':hashlib.sha256(original).hexdigest(),
        'derivedSha256':hashlib.sha256(source).hexdigest(),'actualNativeDescriptorRequired':True,
        'originalTypedLoweringAndLiftingRetained':True,'splicerTrampolineStillRequired':True,
        'actualCompilerExecuted':False,'qualification':'unknown','signedLSFComponentQualified':False}
    return source,receipt


def derive_async_splice(original:bytes) -> tuple[bytes,dict]:
    path='crates/spidermonkey-embedding-splicer/src/splice.rs'
    if hashlib.sha256(original).hexdigest()!=SOURCE_PREIMAGES[path]:
        raise ValueError('unreviewed-original-async-splice')
    source=replace_once(original,b'use std::path::PathBuf;',
        b'use std::path::PathBuf;\nuse std::collections::BTreeMap;\nuse crate::{lsf_async,lsf_async_splice};',
        'owned-native-splice-modules')
    source=replace_once(source,
        b'    let mut wasm =\n        splice::splice(engine, imports, exports, features, debug).map_err(|e| format!("{e:?}"))?;',
        b'''    let async_imports = imports.iter().enumerate().filter_map(|(index,(module,name,_,_))| {
        componentized.lsf_async_imports.get(&(module.clone(),name.clone())).cloned().map(|value|(index,value))
    }).collect::<BTreeMap<_,_>>();
    let mut wasm = splice::splice_with_async(engine, imports, exports, features, debug, &async_imports)
        .map_err(|e|format!("{e:?}"))?;''','actual-parser-import-native-descriptors')
    marker=b') -> Result<Vec<u8>> {\n    let mut module = Module::parse(&engine, false, false).unwrap();'
    source=replace_once(source,marker,
        b''') -> Result<Vec<u8>> {
    splice_with_async(engine,imports,exports,features,debug,&BTreeMap::new())
}

pub fn splice_with_async(
    engine:Vec<u8>, imports:Vec<(String,String,CoreFn,Option<i32>)>,
    exports:Vec<(String,CoreFn,bool)>, features:Vec<Feature>, debug:bool,
    async_imports:&BTreeMap<usize,lsf_async::Descriptor>,
) -> Result<Vec<u8>> {
    let mut module = Module::parse(&engine, false, false).unwrap();''','old-synchronous-splice-ABI-retained')
    source=replace_once(source,b'    synthesize_import_functions(&mut module, &imports, debug)?;',
        b'    synthesize_import_functions(&mut module, &imports, debug, async_imports)?;','selected-native-import-dispatch')
    source=replace_once(source,
        b'    imports: &[(String, String, CoreFn, Option<i32>)],\n    debug: bool,\n) -> Result<()> {',
        b'    imports: &[(String, String, CoreFn, Option<i32>)],\n    debug: bool,\n'
        b'    async_imports:&BTreeMap<usize,lsf_async::Descriptor>,\n) -> Result<()> {', 'native-descriptor-argument')
    source=replace_once(source,
        b'        for (impt_specifier, impt_name, impt_sig, retptr_size) in imports.iter() {',
        b'        for (import_index,(impt_specifier, impt_name, impt_sig, retptr_size)) in imports.iter().enumerate() {',
        'actual-import-index-identity')
    source=replace_once(source,
        b'            let import_fn_type = module.types.add_func_type(&params, &ret);',
        b'''            let descriptor=async_imports.get(&import_index);
            let (params,ret)=if let Some(descriptor)=descriptor {
                let params=descriptor.asynchronous_params.iter().map(|value|match value {
                    wit_parser::abi::WasmType::I32 | wit_parser::abi::WasmType::Pointer | wit_parser::abi::WasmType::Length=>DataType::I32,
                    wit_parser::abi::WasmType::I64 | wit_parser::abi::WasmType::PointerOrI64=>DataType::I64,
                    wit_parser::abi::WasmType::F32=>DataType::F32,
                    wit_parser::abi::WasmType::F64=>DataType::F64,
                }).collect::<Vec<_>>();
                (params,vec![DataType::I32])
            } else {(params,ret)};
            let native_name=if descriptor.is_some(){format!("[async-lower]{impt_name}")}else{impt_name.clone()};
            let import_fn_type = module.types.add_func_type(&params, &ret);''','real-P3-signature-and-import-name')
    # Restrict name substitutions to this exact native import creation block.
    start=source.index(b'            let native_name=')
    end=source.index(b'            // create the native JS binding function',start)
    block=source[start:end]
    block=block.replace(b'(*impt_name).clone()',b'native_name.clone()')
    source=source[:start]+block+source[end:]
    source=replace_once(source,b'            // create the native JS binding function\n',
        b'''            if let Some(descriptor)=descriptor {
                let bigint=get_export_fid(module,&coreabi_from_bigint64);
                import_fnids.push(lsf_async_splice::synthesize(module,impt_sig,descriptor,
                    import_fn_fid,bigint,ctx_arg,vp_arg)?);
                continue;
            }
            // create the native JS binding function
''','genuine-native-Promise-trampoline')
    receipt={'status':'private-derived-splicer-source','originalSha256':hashlib.sha256(original).hexdigest(),
        'derivedSha256':hashlib.sha256(source).hexdigest(),'originalSynchronousSpliceSignatureRetained':True,
        'actualP3SignatureAndAsyncLowerImports':True,'nativeBlockingWaitAdded':False,
        'actualCompilerExecuted':False,'qualification':'unknown','signedLSFComponentQualified':False}
    return source,receipt


def derive_async_compiler_sources(original:dict[str,bytes],native:dict[str,bytes])->tuple[dict[str,bytes],dict]:
    """All exact original files and only the two new owned Rust modules."""
    lib='crates/spidermonkey-embedding-splicer/src/lib.rs'
    if set(original)!=set(SOURCE_PREIMAGES)|{lib} or set(native)!= {'async_import_descriptor.rs','async_import_splice.rs'}:
        raise ValueError('exact-original-async-compiler-source-selection-required')
    if hashlib.sha256(original[lib]).hexdigest()!='69dde2fc5f0421885cfcecaece645f5332dc6d3c343aac8c4fdf70699603b7cf':
        raise ValueError('unreviewed-original-async-splicer-library')
    bindgen,bindgen_receipt=derive_async_bindgen(original['crates/spidermonkey-embedding-splicer/src/bindgen.rs'])
    splice,splice_receipt=derive_async_splice(original['crates/spidermonkey-embedding-splicer/src/splice.rs'])
    library=replace_once(original[lib],b'pub mod bindgen;\n',
        b'pub mod bindgen;\nmod lsf_async;\nmod lsf_async_splice;\n','source-owned-private-import-compiler-modules')
    result={'crates/spidermonkey-embedding-splicer/src/bindgen.rs':bindgen,
            'crates/spidermonkey-embedding-splicer/src/splice.rs':splice,lib:library,
            'crates/spidermonkey-embedding-splicer/src/lsf_async.rs':native['async_import_descriptor.rs'],
            'crates/spidermonkey-embedding-splicer/src/lsf_async_splice.rs':native['async_import_splice.rs']}
    return result,{'originalSource':identity(original),'derivedSource':identity(result),
        'bindgenDerivation':bindgen_receipt,'spliceDerivation':splice_receipt,
        'upstreamPublicSplicerWitChanged':False,'unknownProfilePromoted':False,
        'actualCompilerExecuted':False,'qualification':'unknown','signedLSFComponentQualified':False}
