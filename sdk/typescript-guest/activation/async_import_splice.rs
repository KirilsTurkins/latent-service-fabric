// Real P3 asynchronous native trampoline for the separately selected splicer.
// The original raw SpiderMonkey argument representation is preserved exactly.
use anyhow::{Context, Result};
use wirm::ir::function::FunctionBuilder;
use wirm::ir::id::{FunctionID, LocalID};
use wirm::ir::module::Module;
use wirm::ir::types::BlockType;
use wirm::module_builder::AddLocal;
use wirm::opcode::Inject;
use wirm::wasmparser::{MemArg, Operator};
use wirm::{DataType, Opcode};
use crate::lsf_async::{Descriptor, MemoryWrite};
use crate::wit::exports::local::spidermonkey_embedding_splicer::splicer::{CoreFn,CoreTy};

fn exported(module:&Module<'_>,name:&str)->Result<FunctionID> {
    module.exports.get_func_by_name(name.to_owned()).with_context(||format!("private-async-engine-export-required:{name}"))
}
fn memory(offset:u64)->MemArg { MemArg{align:0,max_align:0,offset,memory:0} }

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
                  import:FunctionID,bigint:FunctionID,cx:LocalID,vp:LocalID)->Result<FunctionID> {
    let get_result=exported(module,"lsf_import_result_buffer")?;
    let get_parameters=exported(module,"lsf_import_parameter_buffer")?;
    let begin=exported(module,"lsf_import_begin")?;
    let started=exported(module,"lsf_import_started")?;
    let mut function=FunctionBuilder::new(&[DataType::I32,DataType::I32,DataType::I32],&[DataType::I32]);
    let id=function.add_local(DataType::I32);
    let result=function.add_local(DataType::I32);
    let parameters=function.add_local(DataType::I32);
    let status=function.add_local(DataType::I32);
    let tmp=function.add_local(DataType::I64);
    function.local_get(vp);function.i64_load(memory(16));function.i32_wrap_i64();function.local_tee(id);
    function.call(get_result);function.local_set(result);
    function.local_get(id);function.call(get_parameters);function.local_set(parameters);
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
