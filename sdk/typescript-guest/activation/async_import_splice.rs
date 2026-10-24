// Real P3 asynchronous native trampoline for the separately selected splicer.
// The original raw SpiderMonkey argument representation is preserved exactly.
use anyhow::{Context, Result};
use wirm::ir::function::FunctionBuilder;
use wirm::ir::id::{FunctionID, GlobalID, LocalID};
use wirm::ir::module::Module;
use wirm::ir::module::module_globals::GlobalKind;
use wirm::ir::module::module_functions::FuncKind;
use wirm::ir::types::{BlockType, ElementItems, ElementKind, InitInstr, Value};
use wirm::module_builder::AddLocal;
use wirm::opcode::Inject;
use wirm::wasmparser::{MemArg, Operator};
use wirm::{DataType, Opcode};
use crate::lsf_async::{Descriptor, MemoryWrite, ResourceDisposal};
use crate::wit::exports::local::spidermonkey_embedding_splicer::splicer::{CoreFn,CoreTy};

fn exported(module:&Module<'_>,name:&str)->Result<FunctionID> {
    module.exports.get_func_by_name(name.to_owned()).with_context(||format!("private-async-engine-export-required:{name}"))
}
fn memory(offset:u64)->MemArg { MemArg{align:0,max_align:0,offset,memory:0} }

pub fn validate_disposer_table_append(module:&Module<'_>)->Result<()> {
    let table=module.tables.main_function()?.context("native-disposer-main-table-required")?;
    let initial=module.tables.get(table).context("native-disposer-main-table-required")?.initial;
    let first=module.elements.iter().next().context("native-disposer-active-segment-required")?;
    let ElementItems::Functions(functions)=&first.items else {
        anyhow::bail!("native-disposer-functions-segment-required");
    };
    let ElementKind::Active{table_index,offset_expr}=&first.kind else {
        anyhow::bail!("native-disposer-active-segment-required");
    };
    anyhow::ensure!(table_index.unwrap_or(0)==*table,"native-disposer-main-segment-required");
    let [InitInstr::Value(Value::I32(base))]=offset_expr.instructions() else {
        anyhow::bail!("native-disposer-fixed-segment-offset-required");
    };
    anyhow::ensure!(*base>=0,"native-disposer-nonnegative-segment-offset-required");
    let end=u64::try_from(*base)?.checked_add(u64::try_from(functions.len())?)
        .context("native-disposer-segment-end-overflow")?;
    anyhow::ensure!(end==initial,"native-disposer-segment-must-end-at-table-initial");
    // No later initializer may overwrite the newly appended callback range.
    let active=module.elements.iter().filter(|element|match &element.kind {
        ElementKind::Active{table_index,..}=>table_index.unwrap_or(0)==*table,
        _=>false,
    }).count();
    anyhow::ensure!(active==1,"native-disposer-unique-main-active-segment-required");
    Ok(())
}

// Resolve the original compiler-produced import identity, never a mixed import
// ordinal, resource-name suffix or guessed function-table position. Both the
// normal binding and the resource disposer must use this stable Functions ID.
pub fn import_function(module:&Module<'_>,key:&(String,String))->Result<Option<FunctionID>> {
    let mut selected=None;
    // Wirm 5's imports.get_func returns a mixed import-section ordinal. Calls
    // require the stable Functions index, especially after new imports append
    // behind the original local functions. Follow the actual import_id link.
    for (index,function) in module.functions.iter().enumerate() {
        let id=FunctionID(u32::try_from(index)?);
        if module.functions.is_deleted(id) {continue;}
        let FuncKind::Import(import)=function.kind() else {continue;};
        let original=module.imports.get(import.import_id);
        if original.module.as_ref()==key.0.as_str() && original.name.as_ref()==key.1.as_str() {
            anyhow::ensure!(selected.is_none(),"unique-original-import-function-required");
            selected=Some(id);
        }
    }
    Ok(selected)
}

pub fn resource_disposer(module:&mut Module<'_>, descriptor:&Descriptor,
    imports:&[(String,String,CoreFn,Option<i32>)])->Result<FunctionID> {
    let mut drops=std::collections::BTreeMap::new();
    fn resolve(module:&mut Module<'_>,plan:&[ResourceDisposal],
        imports:&[(String,String,CoreFn,Option<i32>)],
        drops:&mut std::collections::BTreeMap<(String,String),FunctionID>)->Result<bool> {
        let mut supported=true;
        for node in plan {
            match node {
                ResourceDisposal::Own{drop_import:Some(key),..} => {
                    if drops.contains_key(key) {continue;}
                    let entries=imports.iter().filter(|(module,name,_,_)|module==&key.0 && name==&key.1).collect::<Vec<_>>();
                    let [(name,field,signature,Some(0))]=entries.as_slice() else {
                        anyhow::bail!("exact-original-resource-drop-import-required");
                    };
                    anyhow::ensure!(matches!(signature.params.as_slice(),[CoreTy::I32]) && signature.ret.is_none()
                        && !signature.retptr && !signature.paramptr && signature.retsize==0,
                        "exact-original-resource-drop-signature-required");
                    let function=if let Some(function)=import_function(module,key)? {
                        function
                    } else {
                        let ty=module.types.add_func_type(&[DataType::I32],&[]);
                        module.add_import_func(name.clone(),field.clone(),ty).0
                    };
                    drops.insert(key.clone(),function);
                },
                ResourceDisposal::Variant{cases,..} => for case in cases {
                    supported &= resolve(module,case,imports,drops)?;
                },
                ResourceDisposal::List{stride,elements,..} => {
                    anyhow::ensure!(*stride>0,"owned-list-element-must-have-storage");
                    supported &= resolve(module,elements,imports,drops)?;
                },
                _ => supported=false,
            }
        }
        Ok(supported)
    }
    let supported=resolve(module,&descriptor.disposal,imports,&mut drops)?;
    let mut function=FunctionBuilder::new(&[DataType::I32],&[DataType::I32]);
    let base=LocalID(0);
    if supported {
        // Validate active tags/list address arithmetic before the first drop.
        disposal_walk(&mut function,&descriptor.disposal,base,&drops,true);
        disposal_walk(&mut function,&descriptor.disposal,base,&drops,false);
    }
    function.i32_const(i32::from(supported));
    Ok(function.finish_module(module))
}

fn refuse(function:&mut FunctionBuilder<'_>) {
    function.i32_const(0);function.return_stmt();
}
fn disposal_walk(function:&mut FunctionBuilder<'_>,plan:&[ResourceDisposal],base:LocalID,
    drops:&std::collections::BTreeMap<(String,String),FunctionID>,validate:bool) {
    for node in plan {
        match node {
            ResourceDisposal::Own{offset,drop_import:Some(key),..} => if !validate {
                function.local_get(base);function.i32_load(memory(u64::from(*offset)));
                function.call(drops[key]);
            },
            ResourceDisposal::Variant{offset,tag_bytes,cases} => {
                let tag=function.add_local(DataType::I32);
                function.local_get(base);
                match tag_bytes {
                    1=>{function.inject(Operator::I32Load8U{memarg:memory(u64::from(*offset))});},
                    2=>{function.inject(Operator::I32Load16U{memarg:memory(u64::from(*offset))});},
                    4=>{function.i32_load(memory(u64::from(*offset)));},
                    _=>{refuse(function);continue;},
                }
                function.local_set(tag);
                if validate {
                    function.local_get(tag);function.i32_const(cases.len() as i32);
                    function.i32_ge_u();function.if_stmt(BlockType::Empty);refuse(function);function.end();
                }
                for (index,case) in cases.iter().enumerate() {
                    function.local_get(tag);function.i32_const(index as i32);function.i32_eq();
                    function.if_stmt(BlockType::Empty);
                    disposal_walk(function,case,base,drops,validate);function.end();
                }
            },
            ResourceDisposal::List{offset,stride,elements} => {
                let pointer=function.add_local(DataType::I32);
                let length=function.add_local(DataType::I32);
                let index=function.add_local(DataType::I32);
                let element=function.add_local(DataType::I32);
                function.local_get(base);function.i32_load(memory(u64::from(*offset)));function.local_set(pointer);
                function.local_get(base);function.i32_load(memory(u64::from(*offset)+4));function.local_set(length);
                if validate {
                    function.local_get(pointer);function.i64_extend_i32_u();
                    function.local_get(length);function.i64_extend_i32_u();
                    function.i64_const(i64::from(*stride));function.i64_mul();function.i64_add();
                    function.inject(Operator::MemorySize{mem:0});function.i64_extend_i32_u();
                    function.i64_const(65536);function.i64_mul();function.i64_gt_u();
                    function.if_stmt(BlockType::Empty);refuse(function);function.end();
                }
                function.i32_const(0);function.local_set(index);
                function.inject(Operator::Block{blockty:wirm::wasmparser::BlockType::Empty});
                function.inject(Operator::Loop{blockty:wirm::wasmparser::BlockType::Empty});
                function.local_get(index);function.local_get(length);function.i32_ge_u();
                function.inject(Operator::BrIf{relative_depth:1});
                function.local_get(pointer);function.local_get(index);function.i32_const(*stride as i32);
                function.i32_mul();function.i32_add();function.local_set(element);
                disposal_walk(function,elements,element,drops,validate);
                function.local_get(index);function.i32_const(1);function.i32_add();function.local_set(index);
                function.inject(Operator::Br{relative_depth:0});function.end();function.end();
            },
            _ => refuse(function),
        }
    }
}

pub fn import_getter_pointer(module:&Module<'_>, getter:FunctionID, sample:FunctionID)
    ->Result<(usize,i32)> {
    let table=module.tables.main_function()?.context("native-import-function-table-required")?;
    let mut pointers=Vec::new();
    for element in module.elements.iter() {
        let ElementItems::Functions(functions)=&element.items else {continue};
        let ElementKind::Active{table_index,offset_expr}=&element.kind else {continue};
        if table_index.unwrap_or(0)!=*table {continue;}
        for (index,function) in functions.iter().enumerate() {
            if *function!=sample {continue;}
            let [InitInstr::Value(Value::I32(base))]=offset_expr.instructions() else {
                anyhow::bail!("native-import-sample-table-offset-required");
            };
            let offset=i32::try_from(index).context("native-import-table-index-overflow")?;
            pointers.push(base.checked_add(offset).context("native-import-table-index-overflow")?);
        }
    }
    let [pointer]=pointers.as_slice() else {
        anyhow::bail!("native-import-unique-sample-table-pointer-required");
    };
    let function=module.functions.get(getter).unwrap_local()
        .context("native-import-getter-definition-required")?;
    let ops=function.body.instructions.get_ops();
    let mut positions=Vec::new();
    for (index,op) in ops.iter().enumerate() {
        let Operator::I32Const{value}=op else {continue};
        let mut base=*value;
        if index>0 && matches!(ops.get(index+1),Some(Operator::I32Add)) {
            if let Operator::GlobalGet{global_index}=&ops[index-1] {
                let GlobalKind::Local(global)=module.globals.get_kind(GlobalID(*global_index)) else {
                    continue;
                };
                let [InitInstr::Value(Value::I32(offset))]=global.init_expr.instructions() else {
                    continue;
                };
                base=base.checked_add(*offset).context("native-import-table-index-overflow")?;
            }
        }
        if base==*pointer {positions.push(index);}
    }
    let [position]=positions.as_slice() else {
        anyhow::bail!("native-import-unique-getter-table-operand-required");
    };
    Ok((*position,*pointer))
}

// Identical to the original pinned splicer's JS::Value argument conversion.
// The extra first argument is a compiler-private record identity, never WIT.
fn argument(function:&mut FunctionBuilder<'_>,vp:LocalID,index:usize,kind:&CoreTy,
            bigint:FunctionID,tmp:LocalID) {
    function.local_get(vp);function.i32_const(16+8*(index as i32+1));function.i32_add();
    match kind {
        CoreTy::I32=>{function.i64_load(memory(0));function.i32_wrap_i64();},
        CoreTy::I64=>{function.call(bigint);},
        CoreTy::F32 | CoreTy::F64=>{
            function.i64_load(memory(0));function.local_tee(tmp);
            function.i64_const(32);function.i64_shr_u();function.i64_const(0xFFFFFF81);function.i64_eq();
            function.if_stmt(BlockType::Type(if matches!(kind,CoreTy::F32){DataType::F32}else{DataType::F64}));
            function.local_get(tmp);function.i32_wrap_i64();
            if matches!(kind,CoreTy::F32){function.f32_convert_i32_s();}else{function.f64_convert_i32_s();}
            function.else_stmt();function.local_get(tmp);function.f64_reinterpret_i64();
            if matches!(kind,CoreTy::F32){function.f32_demote_f64();}
            function.end();
        },
    }
}
fn store(function:&mut FunctionBuilder<'_>,kind:&CoreTy,bytes:u32,offset:u32) {
    let memarg=memory(offset as u64);
    match (kind,bytes) {
        (CoreTy::I32,1)=>{function.inject(Operator::I32Store8{memarg});},
        (CoreTy::I32,2)=>{function.inject(Operator::I32Store16{memarg});},
        (CoreTy::I32,4)=>{function.inject(Operator::I32Store{memarg});},
        (CoreTy::I64,1|2|4)=>{
            function.i32_wrap_i64();store(function,&CoreTy::I32,bytes,offset);
        },
        (CoreTy::I64,8)=>{function.inject(Operator::I64Store{memarg});},
        (CoreTy::F32,4)=>{function.inject(Operator::F32Store{memarg});},
        (CoreTy::F64,8)=>{function.inject(Operator::F64Store{memarg});},
        _=>panic!("exact-async-import-flat-memory-store-required"),
    }
}
fn writes(function:&mut FunctionBuilder<'_>,plan:&[MemoryWrite],original:&CoreFn,
          vp:LocalID,parameters:LocalID,bigint:FunctionID,tmp:LocalID) {
    for write in plan {
        match write {
            MemoryWrite::Scalar{argument:index,offset,bytes}=>{
                function.local_get(parameters);
                argument(function,vp,*index,&original.params[*index],bigint,tmp);
                store(function,&original.params[*index],*bytes,*offset);
            },
            MemoryWrite::Variant{tag_argument,tag_offset,tag_bytes,cases}=>{
                function.local_get(parameters);
                argument(function,vp,*tag_argument,&CoreTy::I32,bigint,tmp);
                store(function,&CoreTy::I32,*tag_bytes,*tag_offset);
                for (index,case) in cases.iter().enumerate() {
                    argument(function,vp,*tag_argument,&CoreTy::I32,bigint,tmp);
                    function.i32_const(index as i32);function.i32_eq();function.if_stmt(BlockType::Empty);
                    writes(function,case,original,vp,parameters,bigint,tmp);function.end();
                }
            },
        }
    }
}

pub fn synthesize(module:&mut Module<'_>,original:&CoreFn,descriptor:&Descriptor,
                  import:FunctionID,bigint:FunctionID,cx:LocalID,vp:LocalID,
                  disposer_pointer:i32)->Result<FunctionID> {
    let get_result=exported(module,"lsf_import_result_buffer")?;
    let get_parameters=exported(module,"lsf_import_parameter_buffer")?;
    let begin=exported(module,"lsf_import_begin")?;
    let started=exported(module,"lsf_import_started")?;
    let set_disposer=exported(module,"lsf_import_set_disposer")?;
    let mut function=FunctionBuilder::new(&[DataType::I32,DataType::I32,DataType::I32],&[DataType::I32]);
    let id=function.add_local(DataType::I32);
    let result=function.add_local(DataType::I32);
    let parameters=function.add_local(DataType::I32);
    let status=function.add_local(DataType::I32);
    let tmp=function.add_local(DataType::I64);
    function.local_get(vp);function.i64_load(memory(16));function.i32_wrap_i64();function.local_tee(id);
    function.call(get_result);function.local_set(result);
    function.local_get(id);function.call(get_parameters);function.local_set(parameters);
    function.local_get(cx);function.local_get(id);function.i32_const(disposer_pointer);
    function.i32_const(descriptor.result_bytes as i32);function.call(set_disposer);
    function.i32_eqz();function.if_stmt(BlockType::Empty);
    function.i32_const(0);function.return_stmt();function.end();
    // Indirect parameters use exact original canonical record offsets. For a
    // formerly indirect (>16-flat) call, copy that original record unchanged.
    if descriptor.indirect_params {
        if original.paramptr {
            function.local_get(parameters);argument(&mut function,vp,0,&CoreTy::I32,bigint,tmp);
            function.i32_const(descriptor.parameter_bytes as i32);
            function.inject(Operator::MemoryCopy{dst_mem:0,src_mem:0});
        } else {writes(&mut function,&descriptor.writes,original,vp,parameters,bigint,tmp);}
    }
    function.local_get(cx);function.local_get(id);function.call(begin);function.i32_eqz();
    function.if_stmt(BlockType::Empty);function.i32_const(0);function.return_stmt();function.end();
    if descriptor.indirect_params {function.local_get(parameters);} else {
        let count=original.params.len()-usize::from(original.retptr);
        for index in 0..count {argument(&mut function,vp,index,&original.params[index],bigint,tmp);}
    }
    // Every declared result, including an empty record, has the original P3
    // result pointer slot. The descriptor's signature is the authoritative ABI.
    let parameter_count=if descriptor.indirect_params{1}else{original.params.len()-usize::from(original.retptr)};
    if descriptor.asynchronous_params.len()>parameter_count {function.local_get(result);}
    function.call(import);function.local_set(status);
    // The native call returns a real Promise without an internal blocking wait.
    // Its record holds result/parameter/rooted storage until terminal/drop/lift.
    function.local_get(cx);function.local_get(id);function.local_get(status);function.local_get(vp);
    function.call(started);
    Ok(function.finish_module(module))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{CodeSection, ConstExpr, ElementSection, Elements, Function,
        FunctionSection, GlobalSection, GlobalType, Instruction, MemorySection, MemoryType, RefType, TableSection,
        TableType, TypeSection, ValType};

    fn fixture(pointer:i32, operand:i32, duplicate_operand:bool, duplicate_sample:bool)->Vec<u8> {
        let mut module=wasm_encoder::Module::new();
        let mut types=TypeSection::new();
        types.ty().function([ValType::I32;3],[ValType::I32]);
        module.section(&types);
        let mut functions=FunctionSection::new();
        functions.function(0).function(0);
        module.section(&functions);
        let mut table=TableSection::new();
        table.table(TableType{element_type:RefType::FUNCREF,minimum:pointer as u64+2,
            maximum:None,table64:false,shared:false});
        module.section(&table);
        let mut memories=MemorySection::new();
        memories.memory(MemoryType{minimum:1,maximum:Some(1),memory64:false,shared:false,page_size_log2:None});
        module.section(&memories);
        let mut globals=GlobalSection::new();
        globals.global(GlobalType{val_type:ValType::I32,mutable:true,shared:false},
            &ConstExpr::i32_const(1048576));
        module.section(&globals);
        let mut elements=ElementSection::new();
        let samples=if duplicate_sample {vec![0,0]}else{vec![0]};
        elements.active(None,&ConstExpr::i32_const(pointer),
            Elements::Functions(Cow::Borrowed(&samples)));
        module.section(&elements);
        let mut code=CodeSection::new();
        let mut sample=Function::new([]);
        sample.instruction(&Instruction::I32Const(42)).instruction(&Instruction::End);
        code.function(&sample);
        let mut getter=Function::new([]);
        getter.instruction(&Instruction::GlobalGet(0)).instruction(&Instruction::I32Const(16))
            .instruction(&Instruction::I32Sub).instruction(&Instruction::Drop);
        if duplicate_operand {
            getter.instruction(&Instruction::I32Const(operand)).instruction(&Instruction::Drop);
        }
        getter.instruction(&Instruction::I32Const(operand)).instruction(&Instruction::End);
        code.function(&getter);
        module.section(&code);
        module.finish()
    }

    #[test]
    fn actual_table_membership_selects_small_and_large_pointers_without_stack_arithmetic() {
        for pointer in [532,3432,8000] {
            let bytes=fixture(pointer,pointer,false,false);
            let module=Module::parse(&bytes,false,false).unwrap();
            assert_eq!(import_getter_pointer(&module,FunctionID(1),FunctionID(0)).unwrap(),
                (4,pointer));
        }
    }

    #[test]
    fn absent_or_ambiguous_pointer_shapes_are_rejected() {
        for (operand,duplicate_operand,duplicate_sample) in [(7,false,false),
            (532,true,false),(532,false,true)] {
            let bytes=fixture(532,operand,duplicate_operand,duplicate_sample);
            let module=Module::parse(&bytes,false,false).unwrap();
            assert!(import_getter_pointer(&module,FunctionID(1),FunctionID(0)).is_err());
        }
    }

    fn actual_owned_descriptor()->Descriptor {
        let mut resolve=wit_parser::Resolve::default();
        let package=resolve.push_str(std::path::Path::new("owned.wit"),
            "package tests:imports@1.0.0; interface io { resource connection; connect: async func()->connection; } world guest { import io; }").unwrap();
        let world=resolve.select_world(&[package],Some("guest")).unwrap();
        let interface=resolve.worlds[world].imports.values().find_map(|item|match item {
            wit_parser::WorldItem::Interface{id,..}=>Some(*id),_=>None,
        }).unwrap();
        let mut sizes=wit_parser::SizeAlign::default();sizes.fill(&resolve);
        let mut descriptor=crate::lsf_async::descriptor(&resolve,&resolve.interfaces[interface].functions["connect"],&sizes);
        let ResourceDisposal::Own{resource,..}=&descriptor.disposal[0] else {panic!()};
        descriptor.bind_resource_drops(&std::collections::BTreeMap::from([(*resource,
            ("tests:imports/io@1.0.0".to_owned(),"[resource-drop]connection".to_owned()))]));
        descriptor
    }
    fn original_drop_import()->(String,String,CoreFn,Option<i32>) {
        ("tests:imports/io@1.0.0".to_owned(),"[resource-drop]connection".to_owned(),
            CoreFn{params:vec![CoreTy::I32],ret:None,retptr:false,retsize:0,paramptr:false},Some(0))
    }
    #[test]
    fn actual_own_disposer_calls_only_the_exact_original_drop_import() {
        let bytes=fixture(532,532,false,false);
        let mut module=Module::parse(&bytes,false,false).unwrap();
        // Same field/signature in a different namespace cannot supply a drop.
        // Existing locals also make import ordinals differ from stable IDs.
        let ty=module.types.add_func_type(&[DataType::I32],&[]);
        module.add_import_func("other:imports/io@1.0.0".to_owned(),"[resource-drop]connection".to_owned(),ty);
        let mut disposers=Vec::new();
        for _ in 0..2 {
            disposers.push(resource_disposer(&mut module,&actual_owned_descriptor(),&[original_drop_import()]).unwrap());
        }
        // A later ordinary synchronous binding sees the drop import that the
        // first async disposer inserted. Its mixed import ordinal differs from
        // the stable Functions ID because the original module has locals.
        let (namespace,name,_,_)=original_drop_import();
        let key=(namespace.clone(),name.clone());
        let normal_import=import_function(&module,&key).unwrap().unwrap();
        assert_ne!(module.imports.get_func(namespace,name).unwrap(),normal_import);
        let count=module.num_import_func();
        assert_eq!(import_function(&module,&key).unwrap(),Some(normal_import));
        assert_eq!(module.num_import_func(),count);
        let mut normal_binding=FunctionBuilder::new(&[],&[]);
        normal_binding.i32_const(7);
        normal_binding.call(normal_import);
        disposers.push(normal_binding.finish_module(&mut module));
        for fid in disposers {
            let function=module.functions.get(fid).unwrap_local().unwrap();
            let calls=function.body.instructions.get_ops().iter().filter_map(|op|match op {
                Operator::Call{function_index}=>Some(*function_index),_=>None,
            }).collect::<Vec<_>>();
            assert_eq!(calls.len(),1);
            let FuncKind::Import(import)=module.functions.get_kind(FunctionID(calls[0])) else {panic!("drop must target imported function")};
            let target=module.imports.get(import.import_id);
            assert_eq!((target.module.as_ref(),target.name.as_ref()),("tests:imports/io@1.0.0","[resource-drop]connection"));
        }
        let encoded=module.encode().unwrap();
        wirm::wasmparser::Validator::new().validate_all(&encoded).unwrap();
        // Authenticate the actual encoded targets after Wirm remaps IDs, not
        // an assumed pre-encode numeric import ordinal.
        let reparsed=Module::parse(&encoded,false,false).unwrap();
        let mut calls=0;
        for function in reparsed.functions.iter() {
            let FuncKind::Local(local)=function.kind() else {continue;};
            for op in local.body.instructions.get_ops().iter() {
                if let Operator::Call{function_index}=op {
                    let FuncKind::Import(import)=reparsed.functions.get_kind(FunctionID(*function_index)) else {panic!("encoded drop must target original import")};
                    let target=reparsed.imports.get(import.import_id);
                    assert_eq!((target.module.as_ref(),target.name.as_ref()),("tests:imports/io@1.0.0","[resource-drop]connection"));
                    calls+=1;
                }
            }
        }
        assert_eq!(calls,3);
    }
    #[test]
    fn missing_ambiguous_or_wrong_signature_drop_mapping_is_refused() {
        for mode in 0..3 {
            let bytes=fixture(532,532,false,false);
            let mut module=Module::parse(&bytes,false,false).unwrap();
            let mut imports=vec![original_drop_import()];
            match mode {0=>imports.clear(),1=>imports.push(original_drop_import()),
                _=>imports[0].2.ret=Some(CoreTy::I32)};
            assert!(resource_disposer(&mut module,&actual_owned_descriptor(),&imports).is_err());
        }
    }
    #[test]
    fn actual_callback_table_geometry_refuses_unfilled_tail_or_ambiguous_initializers() {
        let bytes=fixture(532,532,false,false);
        let mut module=Module::parse(&bytes,false,false).unwrap();
        // This original getter fixture has one unused trailing table slot.
        assert!(validate_disposer_table_append(&module).is_err());
        let table=module.tables.main_function().unwrap().unwrap();
        module.tables.get_mut(table).unwrap().initial=533;
        assert!(validate_disposer_table_append(&module).is_ok());
        module.tables.get_mut(table).unwrap().initial=532;
        assert!(validate_disposer_table_append(&module).is_err());
        let mut wasm=wasm_encoder::Module::new();
        let mut types=TypeSection::new();types.ty().function([], [ValType::I32]);wasm.section(&types);
        let mut functions=FunctionSection::new();functions.function(0);wasm.section(&functions);
        let mut tables=TableSection::new();
        tables.table(TableType{element_type:RefType::FUNCREF,minimum:533,maximum:None,
            table64:false,shared:false});wasm.section(&tables);
        let mut elements=ElementSection::new();
        for offset in [532,0] {
            elements.active(None,&ConstExpr::i32_const(offset),Elements::Functions(Cow::Borrowed(&[0])));
        }
        wasm.section(&elements);
        let mut code=CodeSection::new();let mut function=Function::new([]);
        function.instruction(&Instruction::I32Const(1)).instruction(&Instruction::End);
        code.function(&function);wasm.section(&code);
        let bytes=wasm.finish();let module=Module::parse(&bytes,false,false).unwrap();
        assert!(validate_disposer_table_append(&module).is_err());
    }
}
