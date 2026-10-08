// Physical intrinsic reaction records and their pre-admitted future jobs.
#pragma once
#include "promise_records.h"

namespace lsf::typescript::activation {

class ReactionRecords final {
  struct Record {
    NativeOwner native;
    JobOwners job;
    JS::Heap<JSObject*> object;
    bool physical = false;
    bool transferred = false;
    std::unique_ptr<Record> next;
    Record(NativeOwner owner, JobOwners accepted) : native(owner), job(accepted) {}
  };

  PromiseAccounting& native_accounting_;
  Accounting& job_accounting_;
  std::unique_ptr<Record> records_;
  NativeOwner failed_native_{};
  JobOwners failed_job_{};
  bool failed_admission_ = false;
  bool stopped_ = false;

  static bool live(const JobOwners& owners) {
    return owners.task_live || owners.queued_live;
  }
  bool rollback(JSContext* cx, NativeOwner& native, JobOwners& job) {
    if (live(job) && (!job_accounting_.rollback(cx, job) || live(job))) return false;
    return native_accounting_.acknowledgeRetirement(cx, native) && !native.live;
  }
  void failedAdmission(JSContext* cx, NativeOwner& native, JobOwners& job) {
    if (!rollback(cx, native, job)) {
      // Refusal closes admission. Retaining this one partial record needs no
      // additional allocation, and preserves only the still-live exact tokens.
      failed_native_ = native;
      failed_job_ = job;
      failed_admission_ = true;
      stopped_ = true;
    }
  }

public:
  ReactionRecords(PromiseAccounting& native, Accounting& jobs)
      : native_accounting_(native), job_accounting_(jobs) {}

  bool beforeAllocate(JSContext* cx, void** output) {
    *output = nullptr;
    if (stopped_) {
      JS_ReportErrorASCII(cx, "activation-runtime-reaction-admission-closed");
      return false;
    }
    NativeOwner native;
    JobOwners job;
    if (!native_accounting_.beforeAllocate(cx, native)) {
      if (native.live) failedAdmission(cx, native, job);
      return false;
    }
    // Both job owners are admitted before the reaction or native record is
    // allocated, even when the source Promise will remain unresolved.
    if (!job_accounting_.admit(cx, job)) {
      failedAdmission(cx, native, job);
      return false;
    }
    auto record = std::unique_ptr<Record>(new (std::nothrow) Record(native, job));
    if (!record) {
      failedAdmission(cx, native, job);
      JS_ReportOutOfMemory(cx);
      return false;
    }
    *output = record.get();
    record->next = std::move(records_);
    records_ = std::move(record);
    return true;
  }

  static void allocationFailed(void*) {
    // The reserved record stays non-physical, eligible for deferred rollback.
  }
  static void created(JSContext*, JSObject* object, void* pointer) {
    if (!pointer) return;
    auto* record = static_cast<Record*>(pointer);
    record->object = object;
    record->physical = true;
  }
  void* record(JSContext*, JSObject* object) const {
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->object == object) return record;
    }
    return nullptr;
  }
  void sweep(JSTracer* tracer) {
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->object) JS_UpdateWeakPointerAfterGC(tracer, &record->object);
    }
  }
  unsigned collectionCompleted() {
    unsigned retired = 0;
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->physical && !record->object) {
        record->physical = false;
        ++retired;
      }
    }
    return retired;
  }

  bool transfer(JSContext* cx, void* pointer, JobOwners& output) {
    auto* record = static_cast<Record*>(pointer);
    if (!record || !record->physical || record->transferred ||
        !record->job.task_live || !record->job.queued_live || stopped_) {
      JS_ReportErrorASCII(cx, "activation-runtime-reaction-transfer-invalid");
      return false;
    }
    // The queue now retains the exact original callable/capture graph. No new
    // task/queued token is registered, and the native reaction owner remains.
    output = record->job;
    record->job = {};
    record->transferred = true;
    return true;
  }

  bool checkpoint(JSContext* cx) {
    if (failed_admission_) {
      if (!rollback(cx, failed_native_, failed_job_)) return false;
      failed_admission_ = false;
    }
    auto* link = &records_;
    while (*link) {
      auto* record = link->get();
      if (record->physical) {
        link = &record->next;
        continue;
      }
      if (!rollback(cx, record->native, record->job)) return false;
      auto next = std::move(record->next);
      *link = std::move(next);
    }
    return true;
  }
  bool hasPendingReactions() const {
    for (auto* record = records_.get(); record; record = record->next.get()) {
      if (record->physical && !record->transferred) return true;
    }
    return failed_admission_;
  }
};

} // namespace lsf::typescript::activation
