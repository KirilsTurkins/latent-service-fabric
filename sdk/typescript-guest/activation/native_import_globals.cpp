// Compiler-internal functions. The initializer captures these into its own
// module lexical scope and deletes the content-global bridge before app code.
#include "native_engine.h"
#include "js/Conversions.h"
#include "jsapi.h"

namespace lsf::typescript::activation {
namespace {
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
bool cancel(JSContext* cx,unsigned argc,JS::Value* vp) {
  auto args=JS::CallArgsFromVp(argc,vp);uint32_t id=0;
  if(!identity(cx,args,id)||!cancel_import(cx,id))return false;
  args.rval().setUndefined();return true;
}
}
bool install_import_bridge(JSContext* cx,JS::HandleObject global) {
  JS::RootedObject bridge(cx,JS_NewPlainObject(cx));
  if(!bridge || !JS_DefineFunction(cx,bridge,"reserve",reserve,3,0) ||
     !JS_DefineFunction(cx,bridge,"lift",lift,1,0) ||
     !JS_DefineFunction(cx,bridge,"finish",finish,1,0) ||
     !JS_DefineFunction(cx,bridge,"cancel",cancel,1,0))return false;
  return JS_DefineProperty(cx,global,"__lsfAsyncImportBridge",bridge,0);
}
} // namespace lsf::typescript::activation
