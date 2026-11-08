// Serialized lifetime doubles only: these do not execute JavaScript or GC.
#pragma once
#include <cstdint>
#include <memory>
#include <cstddef>
#include <vector>
namespace js { template<class T> using UniquePtr = std::unique_ptr<T>; }

struct JSContext { bool exception = false; const char* detail = nullptr; };
struct JSObject {};
struct JSTracer { JSObject* unreachable = nullptr; };
extern unsigned rooted_callables;
extern bool call_succeeds;
extern bool fail_next_capture;
namespace JS {
template<class T> struct Heap {
  T value{};
  Heap& operator=(T next) { value = next; return *this; }
  operator T() const { return value; }
};
using HandleObject = JSObject*;
struct MutableHandleObject { void set(JSObject*) {} };
struct PersistentRootedObject {
  JSObject* value;
  PersistentRootedObject(JSContext*, HandleObject object) : value(object) { ++rooted_callables; }
  ~PersistentRootedObject() { --rooted_callables; }
  operator HandleObject() const { return value; }
};
struct RootedValue { explicit RootedValue(JSContext*) {} };
struct Value { unsigned long long bits = 0; };
template<class T> struct PersistentRootedVector {
  std::vector<T> values;
  explicit PersistentRootedVector(JSContext*) {}
  bool initCapacity(std::size_t n) {
    if (fail_next_capture) { fail_next_capture = false; return false; }
    values.reserve(n); return true;
  }
  void infallibleAppend(const T& v) { values.push_back(v); }
};
struct HandleValueArray {
  const Value* values = nullptr; std::size_t count = 0;
  HandleValueArray() = default;
  HandleValueArray(const Value* v, std::size_t n) : values(v), count(n) {}
  explicit HandleValueArray(const PersistentRootedVector<Value>& v) : values(v.values.data()), count(v.values.size()) {}
  std::size_t length() const { return count; }
  const Value& operator[](std::size_t i) const { return values[i]; }
  static HandleValueArray empty() { return {}; }
};
inline int UndefinedHandleValue = 0;
inline int NullHandleValue = 0;
inline void JobQueueMayNotBeEmpty(JSContext*) {}
inline bool Call(JSContext*, int, HandleObject, HandleValueArray, RootedValue*) { return call_succeeds; }
inline void PrepareForFullGC(JSContext*) {}
enum class GCOptions { Normal };
enum class GCReason { API };
inline void NonIncrementalGC(JSContext*, GCOptions, GCReason) {}
struct JobQueue {
  struct SavedJobQueue {};
  virtual ~JobQueue() = default;
  virtual bool getHostDefinedData(JSContext*, MutableHandleObject) const = 0;
  virtual bool getHostDefinedGlobal(JSContext*, MutableHandleObject) const = 0;
  virtual bool enqueuePromiseJob(JSContext*, HandleObject, HandleObject, HandleObject, HandleObject) = 0;
  virtual void runJobs(JSContext*) = 0;
  virtual bool empty() const = 0;
  virtual bool isDrainingStopped() const = 0;
protected:
  virtual std::unique_ptr<SavedJobQueue> saveJobQueue(JSContext*) = 0;
};
}
struct JSAutoRealm { JSAutoRealm(JSContext*, JS::HandleObject) {} };
inline bool JS_IsExceptionPending(JSContext* cx) { return cx->exception; }
inline void JS_ClearPendingException(JSContext* cx) { cx->exception = false; cx->detail = nullptr; }
inline void JS_ReportErrorASCII(JSContext* cx, const char* detail, ...) { cx->exception = true; cx->detail = detail; }
inline void JS_ReportOutOfMemory(JSContext* cx) { cx->exception = true; cx->detail = "oom"; }
template<class T> void JS_UpdateWeakPointerAfterGC(JSTracer* tracer, T* edge) {
  if (tracer && edge->value == tracer->unreachable) edge->value = nullptr;
}
