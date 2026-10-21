// Serialized lifetime doubles only: these do not execute JavaScript or GC.
#pragma once
#include <cstdint>
#include <memory>
namespace js { template<class T> using UniquePtr = std::unique_ptr<T>; }

struct JSContext {};
struct JSObject {};
struct JSTracer {};
extern unsigned rooted_callables;
extern bool call_succeeds;
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
struct HandleValueArray { static HandleValueArray empty() { return {}; } };
inline int UndefinedHandleValue = 0;
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
inline void JS_ReportErrorASCII(JSContext*, const char*) {}
inline void JS_ReportOutOfMemory(JSContext*) {}
template<class T> void JS_UpdateWeakPointerAfterGC(JSTracer*, T*) {}
