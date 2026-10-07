// Physical native allocation ownership. The destructor path calls no host.
#pragma once
#include <memory>
#include <new>
#include <utility>

namespace lsf::typescript::activation {

template<class Owner> class NativeRetirement final {
public:
  struct Record {
    Owner owner;
    bool physical = true;
    bool collection_completed = false;
    std::unique_ptr<Record> next;
    explicit Record(Owner accepted) : owner(accepted) {}
  };

private:
  std::unique_ptr<Record> records_;
  Owner failed_owner_{};
  bool failed_owner_live_ = false;
  bool stopped_ = false;

public:
  // Admission is deliberately outside this function: reserve from the actual
  // activation ledger before allocating even this retained native record.
  bool track(Owner accepted, Record*& output) {
    output = nullptr;
    if (stopped_) return false;
    auto record = std::unique_ptr<Record>(new (std::nothrow) Record(accepted));
    if (!record) {
      failed_owner_ = accepted;
      failed_owner_live_ = true;
      stopped_ = true;
      return false;
    }
    output = record.get();
    record->next = std::move(records_);
    records_ = std::move(record);
    return true;
  }

  static void physicallyRetired(Record* record) {
    if (!record) return;
    // May run inside a GC finalizer. Keep the reservation until collection end
    // and an outside-GC checkpoint; marking alone never acknowledges a token.
    record->physical = false;
  }

  void collectionCompleted() {
    for (auto* record = records_.get(); record; record = record->next.get())
      if (!record->physical) record->collection_completed = true;
  }

  template<class Acknowledge> bool checkpoint(Acknowledge acknowledge) {
    if (failed_owner_live_) {
      if (!acknowledge(failed_owner_)) return false;
      failed_owner_live_ = false;
    }
    auto* link = &records_;
    while (*link) {
      auto* record = link->get();
      if (record->physical || !record->collection_completed) {
        link = &record->next;
        continue;
      }
      if (!acknowledge(record->owner)) {
        stopped_ = true;
        return false;
      }
      // Only the tracker storage remains here. Its physical graph has already
      // been destroyed, and this exact owner was acknowledged once above.
      auto next = std::move(record->next);
      *link = std::move(next);
    }
    return true;
  }

  bool stopped() const { return stopped_; }
  bool hasPhysical() const {
    for (auto* record = records_.get(); record; record = record->next.get())
      if (record->physical) return true;
    return false;
  }
  bool hasRetained() const { return failed_owner_live_ || records_ != nullptr; }
  bool hasUnacknowledgedRetirement() const {
    if (failed_owner_live_) return true;
    for (auto* record = records_.get(); record; record = record->next.get())
      if (!record->physical) return true;
    return false;
  }
};

template<class Records> class NativeLease final {
  typename Records::Record* record_ = nullptr;
public:
  NativeLease() = default;
  NativeLease(const NativeLease&) = delete;
  NativeLease& operator=(const NativeLease&) = delete;
  NativeLease(NativeLease&& source) : record_(source.record_) { source.record_ = nullptr; }
  NativeLease& operator=(NativeLease&&) = delete;
  bool bind(typename Records::Record* record) {
    if (record_ || !record) return false;
    record_ = record;
    return true;
  }
  ~NativeLease() { Records::physicallyRetired(record_); }
};

template<class Records,class T> struct OwnedNativeContainer final {
  NativeLease<Records> lease; // first member is destroyed after the value
  T value;
  explicit OwnedNativeContainer(NativeLease<Records>&& accepted) : lease(std::move(accepted)) {}
  OwnedNativeContainer(const OwnedNativeContainer&) = delete;
  OwnedNativeContainer& operator=(const OwnedNativeContainer&) = delete;
};

} // namespace lsf::typescript::activation
