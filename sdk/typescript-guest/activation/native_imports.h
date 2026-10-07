// Native records for the selected P3 import adapter. Typed JS lowering calls
// reserve before allocating; typed lifting acknowledges only after it returns.
#pragma once
#include "broker_import_accounting.h"
#include "js/Promise.h"
#include "js/RootingAPI.h"
#include <cstring>
#include <memory>
#include <new>

namespace lsf::typescript::activation {

class Imports final {
  struct Record {
    // Accounting is per record so multiple parked imports cannot overwrite
    // another import's running/lifting state.
    BrokerImportAccounting accounting;
    NativeOwner record_owner{};
    ImportLifecycle lifecycle;
    JS::PersistentRootedObject promise;
    JS::PersistentRootedValue captures;
    void* result = nullptr;
    size_t result_size = 0;
    void* parameters = nullptr;
    size_t parameter_size = 0;
    uint32_t id = 0;
    bool promise_settled = false;
    bool result_consumed = false;
    std::unique_ptr<Record> following;
    JSContext* cx;
    Record(JSContext* cx, BrokerAccounting& jobs, BrokerPromiseAccounting& native,
           ReadinessSet& readiness)
        : accounting(jobs, native), lifecycle(accounting, readiness), promise(cx), captures(cx), cx(cx) {}
    ~Record() { JS_free(cx, parameters); JS_free(cx, result); }
  };
  BrokerAccounting& jobs_;
  BrokerPromiseAccounting& native_;
  ReadinessSet& readiness_;
  std::unique_ptr<Record> records_;
  uint32_t next_id_ = 1;
  bool stopped_ = false;
  NativeOwner failed_record_owner_{};
  ImportLifecycle::Retirement failed_retirement_{};

  bool collect(JSContext* cx) {
    auto* link = &records_;
    while (*link) {
      auto* item = link->get();
      if (item->lifecycle.phase() != ImportLifecycle::Phase::Retiring &&
          item->lifecycle.phase() != ImportLifecycle::Phase::Retired) {
        link = &item->following;
        continue;
      }
      ImportLifecycle::Retirement retirement;
      if (!item->lifecycle.releaseAfterPhysicalDestruction(cx, retirement)) return false;
      NativeOwner record_owner = item->record_owner;
      auto physical = std::move(*link);
      *link = std::move(physical->following);
      physical.reset(); // JS roots/captures/result and C++ record are gone first
      BrokerImportAccounting accounting(jobs_, native_);
      if (!accounting.physicallyRetired(cx, retirement.native, retirement.result) ||
          !native_.acknowledgeRetirement(cx, record_owner)) {
        failed_retirement_ = retirement;
        failed_record_owner_ = record_owner;
        stopped_ = true;
        return false;
      }
    }
    return true;
  }

  Record* find(uint32_t id) {
    for (auto* item = records_.get(); item; item = item->following.get())
      if (item->id == id) return item;
    return nullptr;
  }
  static bool invalid(JSContext* cx, const char* action) {
    if (!JS_IsExceptionPending(cx)) JS_ReportErrorASCII(cx, "activation-runtime-import-%s-invalid", action);
    return false;
  }
  bool rejectCancelled(JSContext* cx, Record& item) {
    if (item.promise_settled) return true;
    JS::RootedString message(cx, JS_NewStringCopyZ(cx, "activation-runtime-import-cancelled"));
    if (!message) return false;
    JS::RootedValue reason(cx, JS::StringValue(message));
    if (!JS::RejectPromise(cx, item.promise, reason)) return false;
    item.promise_settled = true;
    return true;
  }
public:
  Imports(BrokerAccounting& jobs, BrokerPromiseAccounting& native, ReadinessSet& readiness)
      : jobs_(jobs), native_(native), readiness_(readiness) {}

  bool reserve(JSContext* cx, size_t result_size, size_t parameter_size,
               JS::HandleValue captures, uint32_t& id) {
    id = 0;
    if (stopped_ || next_id_ == 0) return invalid(cx, "closed");
    // The manager's record itself also requires a Native owner before physical
    // allocation. This fixed failure slot retains failed rollback below.
    NativeOwner record_owner;
    if (!native_.beforeAllocate(cx, record_owner) || !record_owner.live) {
      if (record_owner.live) { failed_record_owner_ = record_owner; stopped_ = true; }
      return false;
    }
    auto record = std::unique_ptr<Record>(new (std::nothrow) Record(cx, jobs_, native_, readiness_));
    if (!record) {
      stopped_ = true;
      if (!native_.acknowledgeRetirement(cx, record_owner)) failed_record_owner_ = record_owner;
      JS_ReportOutOfMemory(cx);
      return false;
    }
    record->record_owner = record_owner;
    record->id = next_id_++;
    record->following = std::move(records_);
    records_ = std::move(record);
    auto& accepted = *records_;
    if (!accepted.lifecycle.reserve(cx)) { stopped_ = true; (void)collect(cx); return false; }
    accepted.result_size = result_size;
    accepted.parameter_size = parameter_size;
    // Capacities come from exact compiled WIT layout, never from runtime JS.
    // Every indirect input stays private and stable until subtask terminal/drop.
    if (parameter_size) {
      accepted.parameters = JS_malloc(cx, parameter_size);
      if (accepted.parameters) std::memset(accepted.parameters, 0, parameter_size);
    }
    if (parameter_size && !accepted.parameters) {
      JS_ReportOutOfMemory(cx); (void)accepted.lifecycle.cancel(cx); (void)collect(cx); return false;
    }
    if (result_size) {
      accepted.result = JS_malloc(cx, result_size);
      if (accepted.result) std::memset(accepted.result, 0, result_size);
      if (!accepted.result) {
        JS_ReportOutOfMemory(cx);
        (void)accepted.lifecycle.cancel(cx);
        return false;
      }
    }
    accepted.captures = captures;
    accepted.promise = JS::NewPromiseObject(cx, nullptr);
    if (!accepted.promise) { (void)accepted.lifecycle.cancel(cx); return false; }
    id = accepted.id;
    return true;
  }
  void* resultBuffer(uint32_t id) {
    auto* item = find(id);
    return item && item->lifecycle.phase() == ImportLifecycle::Phase::Reserved ? item->result : nullptr;
  }
  void* parameterBuffer(uint32_t id) {
    auto* item = find(id);
    return item && item->lifecycle.phase() == ImportLifecycle::Phase::Reserved ? item->parameters : nullptr;
  }
  bool beginLowering(JSContext* cx, uint32_t id) {
    auto* item = find(id);
    return item && item->lifecycle.beginLowering(cx);
  }
  bool started(JSContext* cx, uint32_t id, jobs_subtask_status_t status, JS::MutableHandleObject promise) {
    auto* item = find(id);
    if (!item || !item->lifecycle.started(cx, status)) return false;
    promise.set(item->promise);
    return true;
  }
  bool turn(JSContext* cx) {
    if (!collect(cx)) return false;
    for (auto* item = records_.get(); item; item = item->following.get()) {
      auto phase = item->lifecycle.phase();
      if (phase == ImportLifecycle::Phase::Pending) {
        if (!item->lifecycle.observe(cx)) return false;
        phase = item->lifecycle.phase();
      }
      if (phase == ImportLifecycle::Phase::Cancelled) {
        if (!rejectCancelled(cx, *item) || !item->lifecycle.cancel(cx)) return false;
        return collect(cx);
      }
      if (phase != ImportLifecycle::Phase::Returned || item->promise_settled) continue;
      // JS only receives a private record identity, never an early typed result.
      JS::RootedValue identity(cx, JS::NumberValue(item->id));
      if (!JS::ResolvePromise(cx, item->promise, identity)) return false;
      item->promise_settled = true;
      return true;
    }
    return true;
  }
  bool beginLifting(JSContext* cx, uint32_t id, void*& buffer) {
    auto* item = find(id);
    if (!item || !item->promise_settled || !item->lifecycle.beginLifting(cx)) return false;
    buffer = item->result;
    return true;
  }
  bool liftCompleted(JSContext* cx, uint32_t id) {
    auto* item = find(id);
    if (!item || !item->lifecycle.liftCompleted(cx)) return false;
    item->result_consumed = true;
    return collect(cx);
  }
  bool cancel(JSContext* cx, uint32_t id) {
    auto* item = find(id);
    return item && rejectCancelled(cx, *item) && item->lifecycle.cancel(cx) && collect(cx);
  }
  bool cancelAll(JSContext* cx) {
    stopped_ = true;
    for (auto* item = records_.get(); item; item = item->following.get())
      if (!item->lifecycle.cancel(cx)) return false;
    return collect(cx) && !hasPending();
  }
  bool hasPending() const {
    return records_ || failed_record_owner_.live || failed_retirement_.native.live || failed_retirement_.result.live;
  }
  bool hasReady() const {
    for (auto* item = records_.get(); item; item = item->following.get()) {
      const auto phase = item->lifecycle.phase();
      if ((phase == ImportLifecycle::Phase::Returned && !item->promise_settled) ||
          phase == ImportLifecycle::Phase::Cancelled ||
          phase == ImportLifecycle::Phase::Retiring || phase == ImportLifecycle::Phase::Retired)
        return true;
    }
    return false;
  }
};

} // namespace lsf::typescript::activation
