// Exact emitted onabort setter/invoker with finite JSAPI and listener doubles.
// This does not qualify linked-engine execution or real garbage collection.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <functional>
#include <memory>
#include <type_traits>
#include <vector>
#if __cplusplus < 202302L
namespace std { template<class T> constexpr underlying_type_t<T> to_underlying(T v) { return static_cast<underlying_type_t<T>>(v); } }
#endif
struct JSContext { bool pending = false; };
struct JSObject;
struct Value {
  enum Kind { Undefined, Null, Boolean, Object, String } kind = Undefined;
  JSObject* object = nullptr; bool boolean = false;
  bool isObject() const { return kind == Object; }
  bool isNull() const { return kind == Null; }
  bool isBoolean() const { return kind == Boolean; }
  bool toBoolean() const { return boolean; }
  JSObject& toObject() const { assert(isObject());return *object; }
  void setObject(JSObject& obj) { kind=Object;object=&obj; }
  void setNull() { kind=Null;object=nullptr; }
  void setUndefined() { *this=Value{}; }
  void set(Value v) { *this=v; }
};
namespace JS { using Value=::Value; }
using Native = bool(*)(JSContext*,unsigned,JS::Value*);
struct JSObject {
  bool callable=false, result_false=false, fatal=false, throws=false, success_pending=false, canceled=false;
  int id=0;Native native=nullptr;
  std::array<Value,2> slots{};
  std::vector<JSObject*> listeners;
};
using JSFunction = JSObject;
struct RootedObject {
  JSObject* object;
  RootedObject(JSContext*, JSObject* o):object(o){}
  operator JSObject*() const{return object;}
};
struct RootedValue : Value {
  explicit RootedValue(JSContext*){}
  RootedValue(JSContext*, Value v):Value(v){}
};
namespace JS {
struct RootedFunction {
  JSFunction* fn;
  RootedFunction(JSContext*,JSFunction* f):fn(f){}
  operator JSFunction*() const{return fn;}
  explicit operator bool() const{return fn;}
};
template<size_t N> struct RootedValueArray: std::array<Value,N> {explicit RootedValueArray(JSContext*){}};
Value GetReservedSlot(JSObject* obj,int slot){return obj->slots[slot];}
void SetReservedSlot(JSObject* obj,int slot,Value v){obj->slots[slot]=v;}
Value FalseValue(){Value v;v.kind=Value::Boolean;return v;}
Value StringValue(int){Value v;v.kind=Value::String;return v;}
bool IsCallable(JSObject* obj){return obj->callable;}
}
struct Args {
  Value* values;unsigned count;
  Value get(unsigned i){return i<count?values[i+2]:Value{};}
  Value& rval(){return values[1];}
};
#define METHOD_HEADER(n) Args args{vp,argc}; if(argc<n) return false; RootedObject self(cx,&vp[0].toObject())
static bool JS_IsExceptionPending(JSContext* cx){return cx->pending;}
static std::vector<std::unique_ptr<JSObject>> functions;
static bool function_fail=false,function_pending=false,add_fail=false,remove_fail=false;
static int registrations=0,removals=0,pending_calls=0;
static JSObject* last_receiver=nullptr;
static std::vector<int> calls;
static std::function<void()> callback_hook;
static JSFunction* JS_NewFunction(JSContext* cx,Native native,unsigned,unsigned,const char*){
 if(function_fail){cx->pending=true;return nullptr;}
 functions.push_back(std::make_unique<JSObject>());auto* fn=functions.back().get();fn->native=native;fn->callable=true;
 if(function_pending)cx->pending=true;
 return fn;
}
static JSObject* JS_GetFunctionObject(JSFunction* fn){return fn;}
namespace JS {
bool Call(JSContext* cx,JSObject* receiver,Value function,const RootedValueArray<1>&,RootedValue* result){
 if(cx->pending)++pending_calls;
 last_receiver=receiver;calls.push_back(function.object->id);
 if(callback_hook){auto hook=std::move(callback_hook);callback_hook=nullptr;hook();}
 if(function.object->fatal)return false;
 if(function.object->throws||function.object->success_pending)cx->pending=true;
 result->kind=Value::Boolean;result->boolean=!function.object->result_false;
 return !function.object->throws;
}
}
struct EventTarget {
 static bool add_listener(JSContext* cx,JSObject* signal,Value,Value callback,Value){
  if(add_fail){cx->pending=true;return false;}
  signal->listeners.push_back(callback.object);++registrations;return true;
 }
 static bool remove_listener(JSContext* cx,JSObject* signal,Value,Value callback,Value){
  if(remove_fail){cx->pending=true;return false;}
  auto& list=signal->listeners;list.erase(std::remove(list.begin(),list.end(),callback.object),list.end());++removals;return true;
 }
};
struct Event {static void set_canceled(JSObject* event,bool value){event->canceled=value;}};
struct AbortSignal {
 enum class Slots {OnAbort,OnAbortListener};
 static constexpr int abort_type_atom=1;
 static bool onabort_set(JSContext*,unsigned,JS::Value*);
 static bool onabort_invoke(JSContext*,unsigned,JS::Value*);
};
// INSERT_EMITTED_HANDLER
static Value object(JSObject& obj){Value v;v.setObject(obj);return v;}
static bool assign(JSContext* cx,JSObject& signal,Value callback){Value args[3]={object(signal),{},callback};return AbortSignal::onabort_set(cx,1,args);}
static bool dispatch(JSContext* cx,JSObject& signal,JSObject& event){
 const auto snapshot=signal.listeners;
 for(auto* fn:snapshot){
  if(std::find(signal.listeners.begin(),signal.listeners.end(),fn)==signal.listeners.end())continue;
  Value args[3]={object(signal),{},object(event)};
  if(fn->native){if(!fn->native(cx,1,args))return false;}
  else calls.push_back(fn->id);
 }
 return !cx->pending;
}
int main(int argc,char** argv){
 if(argc!=2)return 2;
 const auto is=[&](const char* s){return !std::strcmp(argv[1],s);};
 JSContext cx;JSObject signal,first,second,manual,event;
 for(auto& slot:signal.slots)slot.setNull();
 first.callable=second.callable=manual.callable=true;first.id=1;second.id=2;manual.id=3;
 bool passed=false;
 if(is("install-failure")||is("function-failure")||is("function-pending")){
  add_fail=is("install-failure");function_fail=is("function-failure");function_pending=is("function-pending");
  passed=!assign(&cx,signal,object(first))&&cx.pending&&signal.slots[0].isNull()&&signal.slots[1].isNull()&&signal.listeners.empty();
 }else if(is("entry-pending")){
  cx.pending=true;passed=!assign(&cx,signal,object(first))&&signal.listeners.empty()&&functions.empty();
 }else if(is("noncallable")){
  first.callable=false;passed=assign(&cx,signal,object(first))&&signal.slots[0].object==&first&&dispatch(&cx,signal,event)&&calls.empty();
 }else{
  if(!assign(&cx,signal,object(first)))return 3;
  auto* identity=signal.slots[1].object;
  if(is("replace-order")){
   signal.listeners.push_back(&manual);add_fail=true;
   passed=assign(&cx,signal,object(second))&&signal.slots[0].object==&second&&signal.slots[1].object==identity&&registrations==1&&dispatch(&cx,signal,event)&&calls==std::vector<int>({2,3})&&last_receiver==&signal;
  }else if(is("remove-independent")){
   signal.listeners.push_back(&first);Value null;null.setNull();
   passed=assign(&cx,signal,null)&&signal.slots[0].isNull()&&signal.slots[1].isNull()&&dispatch(&cx,signal,event)&&calls==std::vector<int>{1};
  }else if(is("remove-failure")){
   remove_fail=true;Value null;null.setNull();
   passed=!assign(&cx,signal,null)&&cx.pending&&signal.slots[0].object==&first&&signal.slots[1].object==identity&&signal.listeners==std::vector<JSObject*>{identity};
  }else if(is("primitive-clears")){
   Value primitive;primitive.kind=Value::Boolean;primitive.boolean=true;
   passed=assign(&cx,signal,primitive)&&signal.slots[0].isNull()&&signal.slots[1].isNull()&&signal.listeners.empty();
  }else if(is("callback-reentry")){
   callback_hook=[&]{assert(assign(&cx,signal,object(second)));};
   passed=dispatch(&cx,signal,event)&&signal.slots[1].object==identity&&calls==std::vector<int>{1}&&dispatch(&cx,signal,event)&&calls==std::vector<int>({1,2});
  }else if(is("false-cancels")){
   first.result_false=true;passed=dispatch(&cx,signal,event)&&event.canceled;
  }else if(is("native-fatal")||is("callback-throws")||is("success-pending")){
   first.fatal=is("native-fatal");first.throws=is("callback-throws");first.success_pending=is("success-pending");
   passed=!dispatch(&cx,signal,event)&&calls==std::vector<int>{1}&&cx.pending==!first.fatal;
  }else return 2;
 }
 passed&=!pending_calls;
 std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",argv[1],passed?"true":"false");
 return passed?0:1;
}
