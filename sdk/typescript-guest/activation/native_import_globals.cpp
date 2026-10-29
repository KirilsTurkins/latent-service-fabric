// Compiler-internal functions. The initializer captures these into its own
// module lexical scope and deletes the content-global bridge before app code.
#include "native_engine.h"
#include "js/Conversions.h"
#include "jsapi.h"
#include "js/Id.h"

// Original allocator observation lives in the fresh embedding translation
// unit. These link-only getters are not public core/Component Model exports.
extern "C" uint32_t lsf_import_backing_free_count();
extern "C" bool lsf_import_backing_free_overflow();

namespace lsf::typescript::activation {
namespace {
bool backingFreeCount(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);
  if(argc!=0 || lsf_import_backing_free_overflow()) {
    JS_ReportErrorASCII(cx,"activation-runtime-import-backing-observation-invalid");return false;
  }
  args.rval().setNumber(static_cast<double>(lsf_import_backing_free_count()));
  return true;
}
bool reserve(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);
  if(argc<3 || !args[0].isInt32() || !args[1].isInt32() || !args[2].isInt32() ||
     args[0].toInt32()<0 || args[1].toInt32()<0 || args[2].toInt32()<0) {
    JS_ReportErrorASCII(cx,"activation-runtime-import-reservation-layout-invalid");return false;
  }
  uint32_t id=0;void* result=nullptr;void* parameters=nullptr;
  auto captures=JS::HandleValueArray::subarray(JS::HandleValueArray(args),3,argc-3);
  if(!reserve_import(cx,args[0].toInt32(),args[1].toInt32(),args[2].toInt32(),
                     captures,&id,&result,&parameters))return false;
  args.rval().setNumber(id);return true;
}
bool identity(JSContext* cx,const JS::CallArgs& args,uint32_t& id) {
  if(args.length()!=1 || !args[0].isNumber() ||
     !JS::ToUint32(cx,args[0],&id) || id==0 || args[0].toNumber()!=static_cast<double>(id)) {
    JS_ReportErrorASCII(cx,"activation-runtime-import-record-identity-invalid");return false;
  }
  return true;
}
bool lift(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  return identity(cx,args,id) && lift_import_value(cx,id,args.rval());
}
bool finish(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(!identity(cx,args,id)||!finish_import(cx,id))return false;
  args.rval().setUndefined();return true;
}
bool delivered(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(argc!=2) {JS_ReportErrorASCII(cx,"activation-runtime-import-delivery-shape-invalid");return false;}
  if(!args[0].isNumber() || !JS::ToUint32(cx,args[0],&id) || id==0 ||
     args[0].toNumber()!=static_cast<double>(id) || !mark_import_delivered(cx,id))return false;
  args.rval().set(args[1]);return true;
}
// Initialization-only ABI 2: arguments are source-authenticated generated
// constants/lexical objects; no application object or coercion establishes it.
bool u32(const JS::Value& value,uint32_t& output) {
  if(!value.isNumber())return false;
  const double number=value.toNumber();
  if(!(number>=0 && number<=4294967295.0))return false;
  output=static_cast<uint32_t>(number);
  return number==static_cast<double>(output);
}
bool beginOwnPlans(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t version=0,plans=0,slots=0;
  if(argc!=3 || !u32(args[0],version) || !u32(args[1],plans) || !u32(args[2],slots)) {
    JS_ReportErrorASCII(cx,"activation-runtime-own-plan-shape-invalid");return false;
  }
  if(!begin_import_own_plans(cx,version,plans,slots))return false;
  args.rval().setUndefined();return true;
}
bool bindOwnSlot(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t key=0,bytes=0,count=0,index=0,offset=0,resource=0;
  if(argc!=8 || !u32(args[0],key) || !u32(args[1],bytes) || !u32(args[2],count) ||
      !u32(args[3],index) || !u32(args[4],offset) || !u32(args[5],resource) ||
      !args[6].isObject() || !args[7].isSymbol()) {
    JS_ReportErrorASCII(cx,"activation-runtime-own-slot-shape-invalid");return false;
  }
  JS::RootedObject prototype(cx,&args[6].toObject());
  JS::RootedId symbol(cx,JS::PropertyKey::Symbol(args[7].toSymbol()));
  if(!bind_import_own_slot(cx,key,bytes,count,index,offset,resource,prototype,symbol))return false;
  args.rval().setUndefined();return true;
}
bool attachOwn(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0,slot=0;
  if(argc!=2 || !u32(args[0],id) || !id || !u32(args[1],slot)) {
    JS_ReportErrorASCII(cx,"activation-runtime-own-handoff-shape-invalid");return false;
  }
  JS::RootedObject result(cx);
  if(!attach_import_own(cx,id,slot,&result))return false;
  args.rval().setObject(*result);return true;
}
bool uncertainOwn(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(!identity(cx,args,id) || !uncertain_import_own(cx,id))return false;
  args.rval().setUndefined();return true;
}

bool cancel(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(!identity(cx,args,id)||!cancel_import(cx,id))return false;
  args.rval().setUndefined();return true;
}
bool watchBorrow(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  JS::RootedObject handle(cx);
  if(!identity(cx,args,id)||!watch_import_borrow(cx,id,&handle))return false;
  args.rval().setObject(*handle);return true;
}
bool observeBorrow(JSContext* cx,unsigned argc,JS::Value* vp,bool cancel_requested) {
  auto args=JS::CallArgsFromVp(argc,vp);
  if(args.length()!=1||!args[0].isObject()) {
    JS_ReportErrorASCII(cx,"activation-runtime-import-borrow-handle-invalid");return false;
  }
  JS::RootedObject handle(cx,&args[0].toObject()),promise(cx);
  if(!observe_import_borrow(cx,handle,cancel_requested,&promise))return false;
  args.rval().setObject(*promise);return true;
}
bool borrowReleased(JSContext* cx,unsigned argc,JS::Value* vp) {
  return observeBorrow(cx,argc,vp,false);
}
bool cancelBorrow(JSContext* cx,unsigned argc,JS::Value* vp) {
  return observeBorrow(cx,argc,vp,true);
}
}
bool install_import_bridge(JSContext* cx,JS::HandleObject global) {
  JS::RootedObject bridge(cx,JS_NewPlainObject(cx));
  if(!bridge || !JS_DefineFunction(cx,bridge,"reserve",reserve,3,0) ||
     !JS_DefineFunction(cx,bridge,"lift",lift,1,0) ||
     !JS_DefineFunction(cx,bridge,"finish",finish,1,0) ||
     !JS_DefineFunction(cx,bridge,"delivered",delivered,2,0) ||
     !JS_DefineFunction(cx,bridge,"beginOwnPlans",beginOwnPlans,3,0) ||
     !JS_DefineFunction(cx,bridge,"bindOwnSlot",bindOwnSlot,8,0) ||
     !JS_DefineFunction(cx,bridge,"attachOwn",attachOwn,2,0) ||
     !JS_DefineFunction(cx,bridge,"uncertainOwn",uncertainOwn,1,0) ||
     !JS_DefineFunction(cx,bridge,"backingFreeCount",backingFreeCount,0,0) ||
     !JS_DefineFunction(cx,bridge,"cancel",cancel,1,0) ||
     !JS_DefineFunction(cx,bridge,"watchBorrow",watchBorrow,1,0) ||
     !JS_DefineFunction(cx,bridge,"borrowReleased",borrowReleased,1,0) ||
     !JS_DefineFunction(cx,bridge,"cancelBorrow",cancelBorrow,1,0))return false;
  return JS_DefineProperty(cx,global,"__lsfAsyncImportBridge",bridge,0);
}
} // namespace lsf::typescript::activation
