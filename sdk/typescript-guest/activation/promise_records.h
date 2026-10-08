#pragma once
#include "native_job_queue.h"
#include "js/GCAPI.h"

namespace lsf::typescript::activation {

struct NativeOwner {
  Token token{};
  bool live = false;
};

class PromiseAccounting {
public:
  virtual ~PromiseAccounting() = default;
  // Compiler snapshot observations carry no tenant owner. Runtime admission
  // uses the same configured native-owner ceiling and original ledger.
  virtual bool beforeAllocate(JSContext*, NativeOwner&) = 0;
  virtual bool acknowledgeRetirement(JSContext*, NativeOwner&) = 0;
};

class PromiseRecords final {
  struct Record {
    NativeOwner owner;
    JS::Heap<JSObject*> object;
    bool pending = false;
    bool physical = false;
    std::unique_ptr<Record> next;
    explicit Record(NativeOwner accepted) : owner(accepted) {}
  };

  PromiseAccounting& accounting_;
  std::unique_ptr<Record> records_;
  NativeOwner failed_admission_{};
  bool failed_admission_pending_ = false;
  bool stopped_ = false;

public:
  explicit PromiseRecords(PromiseAccounting& accounting) : accounting_(accounting) {}

  bool beforeAllocate(JSContext* cx, void** output) {
    *output = nullptr;
    if (stopped_) {
      JS_ReportErrorASCII(cx, "activation-runtime-promise-admission-closed");
      return false;
    }
    NativeOwner owner;
    if (!accounting_.beforeAllocate(cx, owner)) {
      if (owner.live) {
        failed_admission_ = owner;
        failed_admission_pending_ = true;
        stopped_ = true;
      }
      return false;
    }
    auto record = std::unique_ptr<Record>(new (std::nothrow) Record(owner));
    if (!record) {
      // Keep failed rollback ownership without another allocation. The queue
      // remains closed until that exact native reservation is acknowledged.
      if (!accounting_.acknowledgeRetirement(cx, owner) || owner.live) {
        failed_admission_ = owner;
        failed_admission_pending_ = true;
        stopped_ = true;
      }
      JS_ReportOutOfMemory(cx);
      return false;
    }
    *output = record.get();
    record->next = std::move(records_);
    records_ = std::move(record);
    return true;
  }

  static void allocationFailed(void* pointer) {
    auto* record = static_cast<Record*>(pointer);
    if (!record) return;
    record->pending = false;
    record->physical = false;
  }
  static void created(JSContext*, JSObject* object, void* pointer) {
    if (!pointer) return;
    auto* record = static_cast<Record*>(pointer);
    record->object = object;
    record->physical = record->pending = true;
  }
  void settled(JSContext*, JSObject* object) {
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->object == object) {
        record->pending = false;
        return;
      }
    }
  }
  void sweep(JSTracer* tracer) {
    // Weak-GC APIs update moved objects and clear unreachable edges. Neither
    // weak observation nor a collection callback invokes the host broker.
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->object) JS_UpdateWeakPointerAfterGC(tracer, &record->object);
    }
  }
  unsigned collectionCompleted() {
    unsigned retired = 0;
    // Keep physical ownership across incremental sweep slices. Collection end
    // is an actual swept-object boundary, still not an owner acknowledgement.
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->physical && !record->object) {
        record->pending = record->physical = false;
        ++retired;
      }
    }
    return retired;
  }

  bool checkpoint(JSContext* cx) {
    if (failed_admission_pending_) {
      if (!accounting_.acknowledgeRetirement(cx, failed_admission_) ||
          failed_admission_.live) return false;
      failed_admission_pending_ = false;
    }
    auto* link = &records_;
    while (*link) {
      auto* record = link->get();
      if (record->physical || record->pending) {
        link = &record->next;
        continue;
      }
      if (!accounting_.acknowledgeRetirement(cx, record->owner) ||
          record->owner.live) return false;
      auto next = std::move(record->next);
      *link = std::move(next);
    }
    return true;
  }

  bool hasPendingPromises() const {
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->pending) return true;
    }
    return false;
  }
  bool hasRetainedRetirement() const {
    if (failed_admission_pending_) return true;
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (!record->physical && record->owner.live) return true;
    }
    return false;
  }
};

} // namespace lsf::typescript::activation
