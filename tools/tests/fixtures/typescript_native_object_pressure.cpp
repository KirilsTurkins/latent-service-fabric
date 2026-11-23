// Production pressure/retirement bodies with finite GC and broker doubles.
// This does not qualify SpiderMonkey, signed components, or the host ledger.
#include "native_retirement.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct JSContext {
  bool pending = false, active = true, in_gc = false, refuse_ack = false;
  bool complete_collection = true, host_in_gc = false;
  unsigned collections = 0, checkpoints = 0, registrations = 0;
  std::string error;
};
bool JS_IsExceptionPending(JSContext* cx) { return cx->pending; }
void JS_ReportErrorASCII(JSContext* cx, const char* text) { cx->pending = true; cx->error = text; }
void JS_ReportOutOfMemory(JSContext* cx) { JS_ReportErrorASCII(cx, "out-of-memory"); }

namespace lsf::typescript::activation {
struct NativeOwner { unsigned token = 0; bool live = false; };
using NativeObjectRecords = NativeRetirement<NativeOwner>;
using NativeObjectLease = NativeLease<NativeObjectRecords>;
NativeObjectRecords native_objects;
struct Entry { NativeObjectRecords::Record* record; bool reachable, finalized = false; };
std::vector<Entry> entries;
std::vector<unsigned> acknowledged;
struct Accounting {
  unsigned live = 0, next = 1;
  unsigned liveNative() const { return live; }
  bool beforeAllocate(JSContext* cx, NativeOwner& owner) {
    cx->host_in_gc |= cx->in_gc;
    ++cx->registrations;
    if (live >= 64) { JS_ReportErrorASCII(cx, "native-limit"); return false; }
    owner = {next++, true}; ++live; return true;
  }
  bool acknowledgeRetirement(JSContext* cx, NativeOwner& owner) {
    cx->host_in_gc |= cx->in_gc;
    if (cx->refuse_ack) { JS_ReportErrorASCII(cx, "ack-refused"); return false; }
    if (!owner.live || !live) return false;
    acknowledged.push_back(owner.token);
    owner.live = false; --live; return true;
  }
} promise_accounting;
bool effects_allowed(JSContext* cx) { return cx->active; }
bool acknowledge_promise_retirement(JSContext* cx) {
  ++cx->checkpoints;
  return native_objects.checkpoint([cx](NativeOwner& owner) {
    return promise_accounting.acknowledgeRetirement(cx, owner) && !owner.live;
  });
}
}
namespace JS {
enum class GCOptions { Normal };
enum class GCReason { API };
void PrepareForFullGC(JSContext*) {}
void NonIncrementalGC(JSContext* cx, GCOptions, GCReason) {
  using namespace lsf::typescript::activation;
  ++cx->collections;
  cx->in_gc = true;
  for (auto& entry : entries) {
    if (!entry.reachable && !entry.finalized) {
      NativeObjectRecords::physicallyRetired(entry.record);
      entry.finalized = true;
    }
  }
  if (cx->complete_collection) native_objects.collectionCompleted();
  cx->in_gc = false;
}
}
namespace lsf::typescript::activation {
// INSERT_PRESSURE_TEMPLATE
// INSERT_COLLECTION_HELPER
// INSERT_PREPARE_AND_ADMIT
bool fill(JSContext* cx, unsigned count, unsigned reachable) {
  for (unsigned i = 0; i < count; ++i) {
    NativeOwner owner;
    NativeObjectRecords::Record* record = nullptr;
    if (!promise_accounting.beforeAllocate(cx, owner) || !native_objects.track(owner, record)) return false;
    entries.push_back({record, i < reachable});
  }
  cx->registrations = 0;
  return true;
}
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  using namespace lsf::typescript::activation;
  JSContext cx;
  const char* name = argv[1];
  bool passed = false;
  if (!std::strcmp(name, "below-pressure")) {
    if (!fill(&cx, 31, 31)) return 3;
    passed = prepare_native_object_allocation(&cx) && cx.collections == 0 && cx.checkpoints == 2 &&
             promise_accounting.live == 31 && acknowledged.empty() && cx.registrations == 0;
  } else if (!std::strcmp(name, "collect-dead-before-admission")) {
    if (!fill(&cx, 64, 52)) return 3;
    const bool ready = prepare_native_object_allocation(&cx);
    bool exact = acknowledged.size() == 12;
    for (unsigned id : acknowledged) exact &= id > 52 && id <= 64;
    NativeObjectLease lease;
    passed = ready && exact && promise_accounting.live == 52 && cx.registrations == 0 &&
             admit_native_object(&cx, lease) && promise_accounting.live == 53 &&
             cx.collections == 1 && cx.registrations == 1;
  } else if (!std::strcmp(name, "reachable-owners-still-refuse")) {
    if (!fill(&cx, 64, 64)) return 3;
    const bool ready = prepare_native_object_allocation(&cx);
    NativeObjectLease lease;
    passed = ready && !admit_native_object(&cx, lease) && cx.error == "native-limit" &&
             promise_accounting.live == 64 && acknowledged.empty() && cx.collections == 1;
  } else if (!std::strcmp(name, "admission-never-collects-staged-captures")) {
    if (!fill(&cx, 64, 52)) return 3;
    NativeObjectLease lease;
    passed = !admit_native_object(&cx, lease) && promise_accounting.live == 64 &&
             cx.collections == 0 && acknowledged.empty() && cx.error == "native-limit";
  } else if (!std::strcmp(name, "physical-death-needs-collection-end")) {
    if (!fill(&cx, 64, 52)) return 3;
    cx.complete_collection = false;
    const bool ready = prepare_native_object_allocation(&cx);
    NativeObjectLease lease;
    passed = ready && !admit_native_object(&cx, lease) && acknowledged.empty() &&
             promise_accounting.live == 64 && cx.collections == 1 && cx.error == "native-limit";
  } else if (!std::strcmp(name, "retirement-refusal-fences-preflight")) {
    if (!fill(&cx, 64, 52)) return 3;
    cx.refuse_ack = true;
    passed = !prepare_native_object_allocation(&cx) && cx.error == "ack-refused" &&
             promise_accounting.live == 64 && acknowledged.empty() && native_objects.stopped() &&
             cx.registrations == 0 && cx.collections == 1;
    cx.pending = false;
    passed &= !prepare_native_object_allocation(&cx) && cx.collections == 1 && cx.registrations == 0;
  } else if (!std::strcmp(name, "entry-exception-is-preserved")) {
    if (!fill(&cx, 64, 52)) return 3;
    cx.pending = true; cx.error = "original-error";
    passed = !prepare_native_object_allocation(&cx) && cx.error == "original-error" &&
             cx.collections == 0 && cx.checkpoints == 0 && cx.registrations == 0;
  } else if (!std::strcmp(name, "snapshot-is-not-collected-or-admitted")) {
    if (!fill(&cx, 64, 52)) return 3;
    cx.active = false;
    passed = !prepare_native_object_allocation(&cx) && cx.collections == 0 &&
             cx.checkpoints == 0 && cx.registrations == 0 && promise_accounting.live == 64;
  } else return 2;
  passed &= !cx.host_in_gc;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", name, passed ? "true" : "false");
  return passed ? 0 : 1;
}
