// Compiler-internal functions. The initializer captures these into its own
// module lexical scope and deletes the content-global bridge before app code.
#include "native_engine.h"
#include "js/Conversions.h"
#include "jsapi.h"

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
     !JS_DefineFunction(cx,bridge,"backingFreeCount",backingFreeCount,0,0) ||
     !JS_DefineFunction(cx,bridge,"cancel",cancel,1,0) ||
     !JS_DefineFunction(cx,bridge,"watchBorrow",watchBorrow,1,0) ||
     !JS_DefineFunction(cx,bridge,"borrowReleased",borrowReleased,1,0) ||
     !JS_DefineFunction(cx,bridge,"cancelBorrow",cancelBorrow,1,0))return false;
  return JS_DefineProperty(cx,global,"__lsfAsyncImportBridge",bridge,0);
}
} // namespace lsf::typescript::activation
