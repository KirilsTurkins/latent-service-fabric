// Finite serialized JSAPI double for actual native owner-manager controls.
// No JavaScript, tracing GC, canonical ABI, or physical Store is executed here.
#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <vector>

struct JSContext { bool exception = false; const char* detail = nullptr; };
struct JSObject;
struct JSString {};
struct JSTracer {};
struct JSClass { const char* name; unsigned flags; };
#define JSCLASS_HAS_RESERVED_SLOTS(n) (n)
namespace js { template<class T> using UniquePtr = std::unique_ptr<T>; }
namespace fixture {
inline unsigned roots = 0, buffers = 0, allocations = 0, resolutions = 0, rejections = 0;
inline std::size_t buffer_bytes = 0, peak_buffer_bytes = 0;
inline unsigned fail_allocation = 0, calls = 0;
inline bool fail_capture = false;
inline bool (*callback)(JSContext*) = nullptr;
}
namespace JS {
struct Value {
  enum Kind { Undefined, Integer, Boolean, Object, Pointer, Number, String } kind = Undefined;
  union Data { int32_t integer; double number; bool boolean; JSObject* object; void* pointer; Data() : pointer(nullptr) {} } data;
  bool isInt32() const { return kind == Integer; }
  int32_t toInt32() const { return data.integer; }
  bool toBoolean() const { return data.boolean; }
  void* toPrivate() const { return data.pointer; }
  JSObject& toObject() const { return *data.object; }
};
inline Value Int32Value(int32_t n) { Value v; v.kind=Value::Integer; v.data.integer=n; return v; }
inline Value BooleanValue(bool b) { Value v; v.kind=Value::Boolean; v.data.boolean=b; return v; }
inline Value PrivateValue(void* p) { Value v; v.kind=Value::Pointer; v.data.pointer=p; return v; }
inline Value ObjectValue(JSObject& o) { Value v; v.kind=Value::Object; v.data.object=&o; return v; }
inline Value NumberValue(double n) { Value v; v.kind=Value::Number; v.data.number=n; return v; }
inline Value StringValue(JSString* p) { Value v; v.kind=Value::String; v.data.pointer=p; return v; }
inline Value UndefinedHandleValue{};
inline Value NullHandleValue{};
struct HandleObject {
  JSObject* value=nullptr;
  HandleObject()=default;
  HandleObject(JSObject* v) : value(v) {}
  JSObject* get() const { return value; }
  operator JSObject*() const { return value; }
};
struct RootedObject : HandleObject {
  explicit RootedObject(JSContext*, JSObject* p=nullptr) : HandleObject(p) {}
  RootedObject(JSContext*, HandleObject p) : HandleObject(p) {}
  RootedObject& operator=(JSObject* p) { value=p; return *this; }
};
struct MutableHandleObject {
  JSObject** output;
  MutableHandleObject(RootedObject* o) : output(&o->value) {}
  void set(JSObject* p) const { *output=p; }
};
struct PersistentRootedObject : HandleObject {
  explicit PersistentRootedObject(JSContext*, HandleObject p={}) : HandleObject(p) { ++fixture::roots; }
  ~PersistentRootedObject() { --fixture::roots; }
  PersistentRootedObject& operator=(JSObject* p) { value=p; return *this; }
};
struct RootedValue {
  Value value;
  explicit RootedValue(JSContext*, Value v={}) : value(v) {}
  operator Value() const { return value; }
};
struct RootedString {
  JSString* value;
  RootedString(JSContext*, JSString* p) : value(p) {}
  operator JSString*() const { return value; }
};
struct MutableHandleValue {
  Value* output;
  MutableHandleValue(RootedValue* v) : output(&v->value) {}
  void setUndefined() { *output={}; }
  void setInt32(int32_t n) { *output=Int32Value(n); }
  void setDouble(double n) { *output=NumberValue(n); }
  void setBigInt(void* p) { *output=PrivateValue(p); }
};
struct PersistentRootedValue {
  Value value;
  explicit PersistentRootedValue(JSContext*) { ++fixture::roots; }
  ~PersistentRootedValue() { --fixture::roots; }
  PersistentRootedValue& operator=(Value v) { value=v; return *this; }
};
template<class T> struct Heap {
  T value{};
  Heap& operator=(T v) { value=v; return *this; }
  operator T() const { return value; }
};
template<class T> struct PersistentRootedVector {
  std::vector<T> values;
  explicit PersistentRootedVector(JSContext*) {}
  bool initCapacity(std::size_t n) {
    if (fixture::fail_capture) { fixture::fail_capture=false; return false; }
    values.reserve(n); return true;
  }
  void infallibleAppend(const T& v) { values.push_back(v); }
};
struct HandleValueArray {
  const Value* values=nullptr; std::size_t count=0;
  HandleValueArray()=default;
  HandleValueArray(const Value* v,std::size_t n) : values(v),count(n) {}
  explicit HandleValueArray(const PersistentRootedVector<Value>& v) : values(v.values.data()),count(v.values.size()) {}
  std::size_t length() const { return count; }
  const Value& operator[](std::size_t i) const { return values[i]; }
  static HandleValueArray empty() { return {}; }
};
inline void JobQueueMayNotBeEmpty(JSContext*) {}
inline bool Call(JSContext* cx, Value, HandleObject, HandleValueArray, RootedValue*) {
  ++fixture::calls; return !fixture::callback || fixture::callback(cx);
}
inline void PrepareForFullGC(JSContext*) {}
enum class GCOptions { Normal };
enum class GCReason { API };
inline void NonIncrementalGC(JSContext*, GCOptions, GCReason) {}
struct JobQueue {
  struct SavedJobQueue {};
  virtual ~JobQueue()=default;
  virtual bool getHostDefinedData(JSContext*,MutableHandleObject) const=0;
  virtual bool getHostDefinedGlobal(JSContext*,MutableHandleObject) const=0;
  virtual bool enqueuePromiseJob(JSContext*,HandleObject,HandleObject,HandleObject,HandleObject)=0;
  virtual void runJobs(JSContext*)=0;
  virtual bool empty() const=0;
  virtual bool isDrainingStopped() const=0;
protected:
  virtual std::unique_ptr<SavedJobQueue> saveJobQueue(JSContext*)=0;
};
}
struct JSObject { const JSClass* klass=nullptr; std::array<JS::Value,16> slots{}; };
namespace fixture {
inline std::array<JSObject,128> objects{};
inline std::size_t object_count=0;
inline JSObject* object() {
  if (object_count==objects.size()) std::abort();
  return &objects[object_count++];
}
}
namespace JS {
inline void SetReservedSlot(JSObject* o,unsigned s,Value v) { o->slots.at(s)=v; }
inline Value GetReservedSlot(JSObject* o,unsigned s) { return o->slots.at(s); }
inline const JSClass* GetClass(JSObject* o) { return o->klass; }
inline JSObject* NewPromiseObject(JSContext*, std::nullptr_t) { return fixture::object(); }
inline bool ResolvePromise(JSContext*, HandleObject, Value) { ++fixture::resolutions; return true; }
inline bool RejectPromise(JSContext*, HandleObject, Value) { ++fixture::rejections; return true; }
inline JSObject* NewArrayObject(JSContext*, const HandleValueArray&) { return fixture::object(); }
inline void* NumberToBigInt(JSContext*,uint64_t) { static unsigned n; return &n; }
}
struct JSAutoRealm { JSAutoRealm(JSContext*,JS::HandleObject) {} };
inline JSObject* JS_NewObject(JSContext*,const JSClass* c) { auto* p=fixture::object(); p->klass=c; return p; }
inline JSString* JS_NewStringCopyZ(JSContext*,const char*) { static JSString s; return &s; }
inline bool JS_IsExceptionPending(JSContext* cx) { return cx->exception; }
inline void JS_ClearPendingException(JSContext* cx) { cx->exception=false; cx->detail=nullptr; }
inline void JS_SetPendingException(JSContext* cx,JS::Value) { cx->exception=true; }
inline void JS_ReportErrorASCII(JSContext* cx,const char* text,...) { cx->exception=true; cx->detail=text; }
inline void JS_ReportOutOfMemory(JSContext* cx) { cx->exception=true; cx->detail="oom"; }
template<class T> void JS_UpdateWeakPointerAfterGC(JSTracer*,T*) {}
inline void* JS_malloc(JSContext*,std::size_t n) {
  if (++fixture::allocations==fixture::fail_allocation) return nullptr;
  auto* p=static_cast<std::size_t*>(std::malloc(n+sizeof(std::size_t)));
  if (!p) return nullptr;
  *p=n; ++fixture::buffers; fixture::buffer_bytes+=n;
  if (fixture::buffer_bytes>fixture::peak_buffer_bytes) fixture::peak_buffer_bytes=fixture::buffer_bytes;
  return p+1;
}
inline void JS_free(JSContext*,void* p) {
  if (!p) return;
  auto* header=static_cast<std::size_t*>(p)-1;
  --fixture::buffers; fixture::buffer_bytes-=*header; std::free(header);
}
