// Compiled into the separately derived pinned source-owned splicer. This
// internal descriptor does not change its public WIT or certify runtime APIs.
use wit_parser::{Function, SizeAlign, Type, TypeDefKind, Int};
use wit_parser::abi::{AbiVariant, WasmType};

#[derive(Clone, Debug)]
pub struct Descriptor {
    pub result_bytes: u32,
    pub parameter_bytes: u32,
    pub raw_result: u32,
    pub asynchronous_params: Vec<WasmType>,
    pub indirect_params: bool,
    pub writes: Vec<MemoryWrite>,
}

#[derive(Clone, Debug)]
pub enum MemoryWrite {
    Scalar { argument: usize, offset: u32, bytes: u32 },
    Variant { tag_argument: usize, tag_offset: u32, tag_bytes: u32,
              cases: Vec<Vec<MemoryWrite>> },
}

fn scalar(cursor: &mut usize, offset: u32, bytes: u32, output: &mut Vec<MemoryWrite>) {
    output.push(MemoryWrite::Scalar { argument: *cursor, offset, bytes });
    *cursor += 1;
}
fn fields(resolve: &wit_parser::Resolve, sizes: &SizeAlign, types: &[Type],
          offset:u32, cursor:&mut usize, output:&mut Vec<MemoryWrite>) {
    for (field_offset, ty) in sizes.field_offsets(types.iter()) {
        memory_writes(resolve,sizes,*ty,offset+field_offset.size_wasm32() as u32,cursor,output);
    }
}
fn variant(resolve:&wit_parser::Resolve,sizes:&SizeAlign,tag:Int,cases:Vec<Option<Type>>,
           offset:u32,cursor:&mut usize,output:&mut Vec<MemoryWrite>) {
    let tag_argument=*cursor; *cursor+=1;
    let payload=*cursor;
    let payload_offset=sizes.payload_offset(tag,cases.iter().map(Option::as_ref)).size_wasm32() as u32;
    let tag_bytes=match tag {Int::U8=>1,Int::U16=>2,Int::U32=>4,Int::U64=>8};
    let mut maximum=payload;
    let mut writes=Vec::new();
    for case in cases {
        let mut case_cursor=payload;let mut case_writes=Vec::new();
        if let Some(ty)=case {
            memory_writes(resolve,sizes,ty,offset+payload_offset,&mut case_cursor,&mut case_writes);
        }
        maximum=maximum.max(case_cursor);writes.push(case_writes);
    }
    *cursor=maximum;
    output.push(MemoryWrite::Variant{tag_argument,tag_offset:offset,tag_bytes,cases:writes});
}
fn memory_writes(resolve:&wit_parser::Resolve,sizes:&SizeAlign,ty:Type,offset:u32,
                 cursor:&mut usize,output:&mut Vec<MemoryWrite>) {
    match ty {
        Type::Bool | Type::U8 | Type::S8=>scalar(cursor,offset,1,output),
        Type::U16 | Type::S16=>scalar(cursor,offset,2,output),
        Type::U32 | Type::S32 | Type::Char | Type::F32=>scalar(cursor,offset,4,output),
        Type::U64 | Type::S64 | Type::F64=>scalar(cursor,offset,8,output),
        Type::String=>{scalar(cursor,offset,4,output);scalar(cursor,offset+4,4,output);},
        Type::Id(id)=>match &resolve.types[id].kind {
            TypeDefKind::Type(ty)=>memory_writes(resolve,sizes,*ty,offset,cursor,output),
            TypeDefKind::Handle(_)=>scalar(cursor,offset,4,output),
            TypeDefKind::Record(record)=>fields(resolve,sizes,&record.fields.iter().map(|field|field.ty).collect::<Vec<_>>(),offset,cursor,output),
            TypeDefKind::Tuple(tuple)=>fields(resolve,sizes,&tuple.types,offset,cursor,output),
            TypeDefKind::List(_)=>{scalar(cursor,offset,4,output);scalar(cursor,offset+4,4,output);},
            TypeDefKind::Enum(_)=>scalar(cursor,offset,sizes.size(&ty).size_wasm32() as u32,output),
            TypeDefKind::Flags(flags)=>{
                let words=flags.repr().count();
                let width=if words<=1 {sizes.size(&ty).size_wasm32() as u32}else{4};
                for index in 0..words {scalar(cursor,offset+index as u32*4,width,output);}
            },
            TypeDefKind::Variant(value)=>variant(resolve,sizes,value.tag(),value.cases.iter().map(|case|case.ty).collect(),offset,cursor,output),
            TypeDefKind::Option(ty)=>variant(resolve,sizes,Int::U8,vec![None,Some(*ty)],offset,cursor,output),
            TypeDefKind::Result(value)=>variant(resolve,sizes,Int::U8,vec![value.ok,value.err],offset,cursor,output),
            _=>panic!("async-import-type-outside-maintained-TypeScript-ABI"),
        },
        _=>panic!("async-import-type-outside-maintained-TypeScript-ABI"),
    }
}

fn signed_small(resolve: &wit_parser::Resolve, ty: Type) -> bool {
    match ty {
        Type::S8 | Type::S16 => true,
        Type::Id(id) => match &resolve.types[id].kind {
            TypeDefKind::Type(ty) => signed_small(resolve,*ty),
            TypeDefKind::Record(record) if record.fields.len()==1 =>
                signed_small(resolve,record.fields[0].ty),
            TypeDefKind::Tuple(tuple) if tuple.types.len()==1 =>
                signed_small(resolve,tuple.types[0]),
            _ => false,
        },
        _ => false,
    }
}

pub fn descriptor(resolve: &wit_parser::Resolve, function: &Function, sizes: &SizeAlign) -> Descriptor {
    let original=resolve.wasm_signature(AbiVariant::GuestImport,function);
    let asynchronous=resolve.wasm_signature(AbiVariant::GuestImportAsync,function);
    let result_bytes=function.result.map(|ty|sizes.size(&ty).size_wasm32() as u32).unwrap_or(0);
    let raw_result=if original.retptr { 5 } else {
        match original.results.first() {
            None=>0,
            Some(WasmType::I32)=>match result_bytes {
                1=>if signed_small(resolve,function.result.unwrap()) {6}else{7},
                2=>if signed_small(resolve,function.result.unwrap()) {8}else{9},
                4=>1,
                _=>panic!("exact-async-import-single-i32-memory-layout-required"),
            },
            Some(WasmType::I64 | WasmType::PointerOrI64)=>2,
            Some(WasmType::F32)=>3,
            Some(WasmType::F64)=>4,
            Some(WasmType::Pointer | WasmType::Length)=>1,
        }
    };
    let parameter_bytes=if asynchronous.indirect_params {
        sizes.record(function.params.iter().map(|param|&param.ty)).size.size_wasm32() as u32
    } else {0};
    let mut writes=Vec::new();
    if asynchronous.indirect_params && !original.indirect_params {
        let mut cursor=0;
        fields(resolve,sizes,&function.params.iter().map(|param|param.ty).collect::<Vec<_>>(),0,&mut cursor,&mut writes);
        let expected=original.params.len()-usize::from(original.retptr);
        assert_eq!(cursor,expected,"async-import-flat-to-memory-plan-changed-original-type-layout");
    }
    Descriptor { result_bytes, parameter_bytes, raw_result,
                 asynchronous_params:asynchronous.params,
                 indirect_params:asynchronous.indirect_params,writes }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn actual(wit:&str)->Descriptor {
        let mut resolve=wit_parser::Resolve::default();
        let package=resolve.push_str(std::path::Path::new("actual.wit"),wit).unwrap();
        let world=resolve.select_world(&[package],Some("guest")).unwrap();
        let function=resolve.worlds[world].imports.values().find_map(|item|match item {
            wit_parser::WorldItem::Function(function)=>Some(function),_=>None,
        }).unwrap();
        let mut sizes=SizeAlign::default();sizes.fill(&resolve);
        descriptor(&resolve,function,&sizes)
    }
    #[test]
    fn actual_five_flat_parameter_record() {
        let value=actual("package tests:imports@1.0.0; world guest { import call: async func(a:u32,b:u32,c:u32,d:u32,e:u32)->u32; }");
        assert!(value.indirect_params);assert_eq!(value.parameter_bytes,20);
        assert_eq!(value.result_bytes,4);assert_eq!(value.raw_result,1);
        assert_eq!(value.asynchronous_params,vec![WasmType::Pointer,WasmType::Pointer]);
        for (index,write) in value.writes.iter().enumerate() {
            assert!(matches!(write,MemoryWrite::Scalar{argument,offset,bytes} if *argument==index && *offset==index as u32*4 && *bytes==4));
        }
    }
    #[test]
    fn actual_original_padding_and_string_pair() {
        let value=actual("package tests:imports@1.0.0; world guest { import call: async func(a:bool,b:u16,c:f64,d:string)->bool; }");
        assert_eq!(value.parameter_bytes,24);assert_eq!(value.raw_result,7);assert_eq!(value.result_bytes,1);
        let layout=value.writes.iter().map(|write|match write {MemoryWrite::Scalar{argument,offset,bytes}=>(*argument,*offset,*bytes),_=>panic!()}).collect::<Vec<_>>();
        assert_eq!(layout,vec![(0,0,1),(1,2,2),(2,8,8),(3,16,4),(4,20,4)]);
    }
    #[test]
    fn actual_variant_payload_bit_layout() {
        let value=actual("package tests:imports@1.0.0; world guest { variant payload { float(f32), wide(u64) } import call: async func(p:payload,a:u32,b:u32,c:u32)->payload; }");
        assert_eq!(value.parameter_bytes,32);assert_eq!(value.raw_result,5);assert_eq!(value.result_bytes,16);
        assert!(matches!(&value.writes[0],MemoryWrite::Variant{tag_argument:0,tag_offset:0,tag_bytes:1,cases} if cases.len()==2));
        match &value.writes[0] {
            MemoryWrite::Variant{cases,..}=>{
                assert!(matches!(cases[0][0],MemoryWrite::Scalar{argument:1,offset:8,bytes:4}));
                assert!(matches!(cases[1][0],MemoryWrite::Scalar{argument:1,offset:8,bytes:8}));
            },_=>panic!(),
        }
    }
    #[test]
    fn actual_original_large_indirect_record_unchanged() {
        let parameters=(0..17).map(|index|format!("a{index}:u32")).collect::<Vec<_>>().join(",");
        let value=actual(&format!("package tests:imports@1.0.0; world guest {{ import call: async func({parameters})->u32; }}"));
        assert!(value.indirect_params);assert_eq!(value.parameter_bytes,68);assert!(value.writes.is_empty());
    }
    #[test]
    fn actual_signed_small_result_abi() {
        let a=actual("package tests:imports@1.0.0; world guest { import call: async func()->s8; }");
        let b=actual("package tests:imports@1.0.0; world guest { import call: async func()->s16; }");
        assert_eq!((a.raw_result,a.result_bytes),(6,1));assert_eq!((b.raw_result,b.result_bytes),(8,2));
    }
    #[test]
    fn actual_nested_optional_and_list_layout() {
        let value=actual("package tests:imports@1.0.0; world guest { record request {name:string,items:list<u16>,optional:option<u64>} import call: async func(r:request)->result<string,u32>; }");
        assert!(value.indirect_params);assert_eq!(value.parameter_bytes,32);
        assert_eq!((value.raw_result,value.result_bytes),(5,12));
        assert!(matches!(value.writes[4],MemoryWrite::Variant{tag_argument:4,tag_offset:16,tag_bytes:1,..}));
    }
}
