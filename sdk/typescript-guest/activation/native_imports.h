// Native records for the selected P3 import adapter. Typed JS lowering calls
// reserve before allocating; typed lifting acknowledges only after it returns.
#pragma once
#include "broker_import_accounting.h"
#include "js/Promise.h"
#include "js/Array.h"
#include "js/RootingAPI.h"
#include "native_import_values.h"
#include "native_import_observer.h"
#include <cstring>
#include <memory>
#include <new>

namespace lsf::typescript::activation {

class PartialOwnLifts;
class Imports final {
  friend class PartialOwnLifts;
#ifdef LSF_TYPESCRIPT_PARTIAL_OWN_CONTROLS
  friend struct PartialOwnLiftControls;
#endif
#ifdef LSF_TYPESCRIPT_BORROW_CONTROLS
  friend struct ImportBorrowControls;
#endif
  enum class Disposition { Unproduced, Produced, Lifting, Delivered, Disposed, Quarantined };
  using ResourceDisposer = bool (*)(uint32_t);
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
    Disposition disposition = Disposition::Unproduced;
    ResourceDisposer disposer = nullptr;
    ImportRawResult raw_kind = ImportRawResult::None;
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
  // Optional intrusive nodes use the original Native admission cap. No field
  // or storage is added to Record, and the default path creates no node/root.
  std::unique_ptr<ImportBorrowObserver> observers_;
  size_t observer_count_ = 0;
  bool failed_observer_completion_ = false;

  bool collect(JSContext* cx) {
    if (failed_observer_completion_) return invalid(cx, "borrow-quarantined");
    auto* link = &records_;
    while (*link) {
      auto* item = link->get();
      if (item->lifecycle.phase() != ImportLifecycle::Phase::Retiring &&
          item->lifecycle.phase() != ImportLifecycle::Phase::Retired) {
        link = &item->following;
        continue;
      }
      std::unique_ptr<ImportBorrowObserver>* observer_link = nullptr;
      if (!observerLink(cx, item->id, item->record_owner.token, observer_link)) return false;
      if (*observer_link && (*observer_link)->quarantined) return invalid(cx, "borrow-quarantined");
      ImportLifecycle::Retirement retirement;
      if (!item->lifecycle.releaseAfterPhysicalDestruction(cx, retirement)) {
        if (*observer_link) {
          (*observer_link)->quarantined = true;
          failed_observer_completion_ = stopped_ = true;
        }
        return false;
      }
      NativeOwner record_owner = item->record_owner;
      auto physical = std::move(*link);
      *link = std::move(physical->following);
      physical.reset(); // JS roots/captures/result and C++ record are gone first
      BrokerImportAccounting accounting(jobs_, native_);
      if (!accounting.physicallyRetired(cx, retirement.native, retirement.result) ||
          !native_.acknowledgeRetirement(cx, record_owner)) {
        failed_retirement_ = retirement;
        failed_record_owner_ = record_owner;
        if (*observer_link) {
          (*observer_link)->quarantined = true;
          failed_observer_completion_ = true;
        }
        stopped_ = true;
        return false;
      }
      if (*observer_link) {
        // Original record/captures/buffers are gone and their acks succeeded.
        // Only now detach the paid observer. Its managed handle survives on a
        // local stack root; native storage/persistent root die BEFORE refund.
        auto observer = std::move(*observer_link);
        *observer_link = std::move(observer->following);
        JS::RootedObject observer_handle(cx, observer->handle);
        NativeOwner observer_owner = observer->allocation_owner;
        observer.reset();
        --observer_count_;
        if (!native_.acknowledgeRetirement(cx, observer_owner)) {
          // Reuse the original scalar failure slot: physical storage is gone,
          // but this final paid owner remains unacknowledged. No release proof.
          failed_record_owner_ = observer_owner;
          failed_observer_completion_ = true;
          stopped_ = true;
          return false;
        }
        if (!ImportBorrowObserver::acknowledge(cx, observer_handle)) {
          failed_observer_completion_ = stopped_ = true;
          return false;
        }
      }
    }
    return true;
  }

  Record* find(uint32_t id) {
    for (auto* item = records_.get(); item; item = item->following.get())
      if (item->id == id) return item;
    return nullptr;
  }
  bool observerLink(JSContext* cx, uint32_t id, Token owner,
                    std::unique_ptr<ImportBorrowObserver>*& output) {
    auto* link = &observers_;
    size_t visited = 0;
    while (*link) {
      if (++visited > observer_count_) {
        failed_observer_completion_ = stopped_ = true;
        return invalid(cx, "borrow-list");
      }
      if ((*link)->matchesOriginal(cx, id, owner)) break;
      link = &(*link)->following;
    }
    output = link;
    return true;
  }
  static bool invalid(JSContext* cx, const char* action) {
    if (!JS_IsExceptionPending(cx)) JS_ReportErrorASCII(cx, "activation-runtime-import-%s-invalid", action);
    return false;
  }
  bool quarantineBorrow(JSContext* cx, Record& item) {
    std::unique_ptr<ImportBorrowObserver>* link = nullptr;
    if (!observerLink(cx, item.id, item.record_owner.token, link)) return false;
    if (*link) {
      (*link)->quarantined = true;
      failed_observer_completion_ = stopped_ = true;
    }
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
  bool cancelRecord(JSContext* cx, Record& item) {
    if (!item.lifecycle.cancel(cx)) return false;
    if (!item.lifecycle.hasReturnedResult()) return true;
    if (item.disposition == Disposition::Unproduced) item.disposition = Disposition::Produced;
    if (item.disposition != Disposition::Produced || !item.disposer)
      return invalid(cx,"resource-disposal-state");
    // A drop may remove its canonical handle before its destructor traps. Mark
    // non-retryable and retain every owner BEFORE entering the first intrinsic.
    item.disposition = Disposition::Quarantined;
    const bool was_stopped = stopped_;
    stopped_ = true;
    if (!item.disposer(static_cast<uint32_t>(reinterpret_cast<uintptr_t>(item.result))))
      return invalid(cx,"resource-disposal-refused");
    item.disposition = Disposition::Disposed;
    stopped_ = was_stopped;
    return item.lifecycle.discardCompleted(cx);
  }
public:
  Imports(BrokerAccounting& jobs, BrokerPromiseAccounting& native, ReadinessSet& readiness)
      : jobs_(jobs), native_(native), readiness_(readiness) {}

  bool reserve(JSContext* cx, size_t result_size, size_t parameter_size,
               ImportRawResult raw_kind, const JS::HandleValueArray& captures, uint32_t& id) {
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
    accepted.raw_kind = raw_kind;
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
    JS::RootedObject roots(cx,JS::NewArrayObject(cx,captures));
    if (!roots) { (void)accepted.lifecycle.cancel(cx); (void)collect(cx); return false; }
    accepted.captures = JS::ObjectValue(*roots);
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
    if (!item || !item->disposer) return invalid(cx, "lower-record");
    return item->lifecycle.beginLowering(cx);
  }
  bool setDisposer(JSContext* cx,uint32_t id,ResourceDisposer disposer,uint32_t result_bytes) {
    auto* item=find(id);
    if (!item || !disposer || item->disposer || item->result_size!=result_bytes ||
        item->lifecycle.phase()!=ImportLifecycle::Phase::Reserved)
      return invalid(cx,"resource-disposer-registration");
    item->disposer=disposer;
    return true;
  }
  bool started(JSContext* cx, uint32_t id, jobs_subtask_status_t status, JS::MutableHandleObject promise) {
    auto* item = find(id);
    if (!item) return invalid(cx, "start-record");
    if (!item->lifecycle.started(cx, status)) return false;
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
        if (!rejectCancelled(cx, *item) || !cancelRecord(cx, *item)) return quarantineBorrow(cx, *item);
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
    if (!item || !item->promise_settled) return invalid(cx, "lift-record");
    if (!item->lifecycle.beginLifting(cx)) return false;
    if (item->disposition != Disposition::Unproduced && item->disposition != Disposition::Produced)
      return invalid(cx,"result-transfer");
    item->disposition = Disposition::Lifting;
    buffer = item->result;
    return true;
  }
  bool liftValue(JSContext* cx, uint32_t id, JS::MutableHandleValue value) {
    auto* item = find(id);
    void* buffer = nullptr;
    if (!item) {
      if (id != 0 && (next_id_ == 0 || id < next_id_)) {
        // The private carrier may resolve before cancellation retires its
        // record. Preserve the same logical rejection when its queued typed
        // lift finally runs. This also rejects private duplicate retired lifts;
        // it returns no value and performs no retirement or acknowledgement.
        if (JS_IsExceptionPending(cx)) return false;
        JS::RootedString message(cx, JS_NewStringCopyZ(cx, "activation-runtime-import-cancelled"));
        if (!message) return false;
        JS::RootedValue reason(cx, JS::StringValue(message));
        JS_SetPendingException(cx, reason);
        return false;
      }
      return invalid(cx, "lift-record");
    }
    if (!beginLifting(cx,id,buffer)) return false;
    return lift_raw_import(cx,buffer,item->result_size,item->raw_kind,value);
  }
  bool liftCompleted(JSContext* cx, uint32_t id) {
    auto* item = find(id);
    if (!item) {
      // A cancelled record can physically retire before its rejected Promise's
      // generated finally executes. IDs are monotonic and never reused. This
      // terminal no-op performs no drop, settlement, ACK or quarantine reset.
      if (id != 0 && (next_id_ == 0 || id < next_id_)) return true;
      return invalid(cx, "finish-record");
    }
    if(item->lifecycle.phase()!=ImportLifecycle::Phase::Lifting) {
      if (!cancelRecord(cx,*item)) return quarantineBorrow(cx,*item);
      return collect(cx);
    }
    if (item->disposition != Disposition::Delivered) {
      item->disposition=Disposition::Quarantined;
      stopped_=true;
      (void)invalid(cx,"partial-typed-lift");
      return quarantineBorrow(cx,*item);
    }
    if (!item->lifecycle.liftCompleted(cx)) return quarantineBorrow(cx, *item);
    return collect(cx);
  }
  bool delivered(JSContext* cx,uint32_t id) {
    auto* item=find(id);
    if (!item || item->lifecycle.phase()!=ImportLifecycle::Phase::Lifting ||
        item->disposition!=Disposition::Lifting)
      return invalid(cx,"typed-delivery");
    item->disposition=Disposition::Delivered;
    return true;
  }
  bool cancel(JSContext* cx, uint32_t id) {
    auto* item = find(id);
    if (!item) return invalid(cx, "cancel-record");
    return rejectCancelled(cx, *item) && cancelRecord(cx, *item) && collect(cx);
  }
  bool watchBorrow(JSContext* cx, uint32_t id, JS::MutableHandleObject handle) {
    auto* item = find(id);
    if (stopped_ || !item || !item->record_owner.live) return invalid(cx, "borrow-record");
    std::unique_ptr<ImportBorrowObserver>* link = nullptr;
    if (!observerLink(cx, id, item->record_owner.token, link)) return false;
    auto* existing = link->get();
    if (existing) {
      if (existing->quarantined || !existing->handle) return invalid(cx, "borrow-quarantined");
      handle.set(existing->handle);
      return true;
    }
    // Only the selected generated reservation site can arm a new observer.
    if (item->lifecycle.phase() != ImportLifecycle::Phase::Reserved)
      return invalid(cx, "borrow-arm-phase");
    NativeOwner observer_owner;
    if (!native_.beforeAllocate(cx, observer_owner) || !observer_owner.live) {
      if (observer_owner.live) {
        failed_record_owner_ = observer_owner;
        failed_observer_completion_ = true;
      }
      stopped_ = true;
      return false;
    }
    // This one admitted Native owner covers the exact optional node, its
    // linkage, token and persistent root before any native allocation. The
    // managed handle stays inside the original JS heap cap; NewPromiseObject
    // uses the already installed before_promise/PromiseRecords hooks.
    auto observer = std::unique_ptr<ImportBorrowObserver>(new (std::nothrow) ImportBorrowObserver(cx, id, item->record_owner.token));
    if (!observer) {
      failed_record_owner_ = observer_owner;
      failed_observer_completion_ = true;
      stopped_ = true;
      JS_ReportOutOfMemory(cx);
      return false;
    }
    observer->allocation_owner = observer_owner;
    observer->following = std::move(observers_);
    observers_ = std::move(observer);
    ++observer_count_;
    if (!observers_->initialize(cx, this, id, item->record_owner.token)) {
      observers_->quarantined = stopped_ = true;
      failed_observer_completion_ = true;
      return false;
    }
    handle.set(observers_->handle);
    return true;
  }
  bool observeBorrow(JSContext* cx, JS::HandleObject handle, bool request_cancel,
                     JS::MutableHandleObject promise) {
    // Check the current already-admitted epoch even for a retained released
    // handle. Returning its old Promise must not bypass generation identity.
    if (!ImportBorrowObserver::belongsTo(cx, handle, this, jobs_.generation())) return invalid(cx, "borrow-owner");
    if (ImportBorrowObserver::released(handle)) {
      promise.set(ImportBorrowObserver::promise(handle));
      return true; // Repeated original handle, never another cancellation.
    }
    auto* item = find(ImportBorrowObserver::recordId(handle));
    std::unique_ptr<ImportBorrowObserver>* link = nullptr;
    if (item && !observerLink(cx, item->id, item->record_owner.token, link)) return false;
    auto* observer = link ? link->get() : nullptr;
    if (stopped_ || !item || !item->record_owner.live || !observer || observer->quarantined ||
        observer->handle.get() != handle.get() ||
        !ImportBorrowObserver::matches(handle, item->id, item->record_owner.token))
      return invalid(cx, "borrow-stale");
    promise.set(ImportBorrowObserver::promise(handle));
    if (request_cancel && !observer->cancellation_requested) {
      observer->cancellation_requested = true;
      // This preserves the existing immediate logical rejection. It may free
      // item; no item/observer access follows. The distinct Promise waits for
      // the original terminal event, real drop and collect boundary above.
      if (cancel(cx, item->id)) return true;
      // A refusal may have happened after collect physically destroyed item.
      // Do not touch it again; quarantine the manager's remaining paid nodes.
      failed_observer_completion_ = stopped_ = true;
      return false;
    }
    return true;
  }
  bool cancelAll(JSContext* cx) {
    stopped_ = true;
    for (auto* item = records_.get(); item; item = item->following.get())
      if (!cancelRecord(cx, *item)) return quarantineBorrow(cx, *item);
    return collect(cx) && !hasPending();
  }
  bool hasPending() const {
    return records_ || failed_record_owner_.live || failed_retirement_.native.live || failed_retirement_.result.live ||
      observers_ || failed_observer_completion_;
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
