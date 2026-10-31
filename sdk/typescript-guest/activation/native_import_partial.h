#pragma once
#include "native_imports.h"
#include "js/Id.h"
#include "js/PropertyAndElement.h"
#include "js/Realm.h"
#include "jsapi.h"
#include <array>

namespace lsf::typescript::activation {

// Private binding ABI 2. This is identity/progress metadata, not a credit
// ledger. Imports, its Record, whole-unlifted disposer and cancellation walk
// retain their original layouts/bodies. Optional runtime nodes acquire an
// ORIGINAL Native owner before allocation; static plans are initial component
// heap inputs, bounded by the existing compiler's 256 functions and 64 slots.
class PartialOwnLifts final {
#ifdef LSF_TYPESCRIPT_PARTIAL_OWN_CONTROLS
  friend struct PartialOwnLiftControls;
#endif
  using Getter = uint64_t (*)(uint32_t);
  using Disposer = bool (*)(uint32_t, uint32_t, uint32_t);
  struct Slot {
    uint32_t offset = 0, resource = 0;
    JS::PersistentRootedObject prototype;
    JS::PersistentRootedId symbol;
  };
  struct Plan {
    uint32_t key = 0, bytes = 0, count = 0, bound = 0;
    std::unique_ptr<Slot[]> slots;
    std::unique_ptr<Plan> next;
  };
  struct Lift {
    uint32_t id = 0;
    Token record{};
    NativeOwner owner{};
    const Plan* plan = nullptr;
    Getter getter = nullptr;
    Disposer disposer = nullptr;
    uint64_t transferred = 0, attaching = 0;
    std::array<uint32_t,64> handles{}; // Inside this ORIGINAL pre-admitted Lift.
    bool snapshot = false;
    bool uncertain = false, legacy_this = false, cleaning = false;
    std::unique_ptr<Lift> next;
  };
  Imports& imports_;
  bool (*initializing_)(JSContext*);
  std::unique_ptr<Plan> plans_;
  std::unique_ptr<Lift> lifts_;
  uint32_t expected_plans_ = 0, expected_slots_ = 0, bound_plans_ = 0, bound_slots_ = 0;
  bool begun_ = false, sealed_ = false, binding_failed_ = false, collecting_ = false, preparing_ = false;
  NativeOwner failed_owner_{};
  bool invalid(JSContext* cx, const char* reason) {
    return Imports::invalid(cx, reason);
  }
  bool bindingFailure(JSContext* cx) {
    binding_failed_ = true;
    return invalid(cx, "own-plan-binding");
  }
  const Plan* plan(uint32_t key) const {
    for (auto* p = plans_.get(); p; p = p->next.get()) if (p->key == key) return p;
    return nullptr;
  }
  Lift* find(uint32_t id) {
    for (auto* p = lifts_.get(); p; p = p->next.get()) if (p->id == id) return p;
    return nullptr;
  }
  static bool same(Token a, Token b) { return a.id == b.id && a.generation == b.generation; }
  bool current(JSContext* cx, const Lift& lift, const Imports::Record* item) const {
    return item && item->cx == cx && item->record_owner.live &&
      same(item->record_owner.token, lift.record) && lift.record.id &&
      imports_.jobs_.generation() == lift.record.generation && !imports_.stopped_ &&
      item->lifecycle.phase() == ImportLifecycle::Phase::Lifting &&
      item->disposition == Imports::Disposition::Lifting;
  }
  bool validateFrame(JSContext* cx,uint32_t id,Token token,const Plan* identity,Getter getter) {
    for(uint32_t index=0;index<identity->count;++index) {
      const uint64_t actual=getter(index); // No Record/Slot/frame borrow over callback.
      auto* lift=find(id);auto* item=imports_.find(id);
      if(!lift || !same(lift->record,token) || lift->plan!=identity ||
          !current(cx,*lift,item) || lift->uncertain || lift->cleaning ||
          actual!=((uint64_t(identity->slots[index].offset)<<32)|identity->slots[index].resource)) {
        if(lift) {lift->uncertain=true;lift->legacy_this=false;}
        return invalid(cx,"own-plan-frame");
      }
    }
    auto* lift=find(id);auto* item=imports_.find(id);
    if(!lift || !same(lift->record,token) || lift->plan!=identity || !current(cx,*lift,item) ||
        lift->uncertain || lift->cleaning) return invalid(cx,"own-plan-frame-owner");
    // No callbacks/JS/GC occur in this fixed scan. Preserve the original full
    // raw handles and check aliases BEFORE first positive handoff and again
    // BEFORE any destructor. Mutated or duplicate ownership is never replayed.
    for(uint32_t index=0;index<identity->count;++index) {
      const auto offset=identity->slots[index].offset;
      uint32_t handle=0;
      if(offset>item->result_size || item->result_size-offset<sizeof(handle)) {
        lift->uncertain=true;lift->legacy_this=false;return invalid(cx,"own-plan-frame-range");
      }
      std::memcpy(&handle,static_cast<const uint8_t*>(item->result)+offset,sizeof(handle));
      if(lift->snapshot && lift->handles[index]!=handle) {
        lift->uncertain=true;lift->legacy_this=false;return invalid(cx,"own-plan-frame-mutated");
      }
      if(!lift->snapshot)lift->handles[index]=handle;
      const auto& slot=identity->slots[index];
      for(uint32_t previous=0;previous<index;++previous) {
        const auto& other=identity->slots[previous];
        const bool same_resource=slot.resource==other.resource ||
          (slot.prototype.get()==other.prototype.get() && slot.symbol.get()==other.symbol.get());
        if(same_resource && lift->handles[previous]==handle) {
          lift->uncertain=true;lift->legacy_this=false;return invalid(cx,"own-plan-duplicate-handle");
        }
      }
    }
    lift->snapshot=true;
    return true;
  }

public:
  PartialOwnLifts(Imports& imports, bool (*initializing)(JSContext*))
      : imports_(imports), initializing_(initializing) {}
  bool rejectBinding(JSContext* cx) { return bindingFailure(cx); }
  bool begin(JSContext* cx, uint32_t version, uint32_t plans, uint32_t slots) {
    if (!initializing_ || !initializing_(cx) || begun_ || sealed_ || binding_failed_ ||
        version != 2 || plans > 256 || slots > 256 * 64 || slots < plans ||
        ((plans == 0) != (slots == 0))) return bindingFailure(cx);
    begun_ = true; expected_plans_ = plans; expected_slots_ = slots;
    return true;
  }
  bool bind(JSContext* cx, uint32_t key, uint32_t bytes, uint32_t count, uint32_t index,
            uint32_t offset, uint32_t resource, JS::HandleObject prototype, JS::HandleId symbol) {
    if (!initializing_ || !initializing_(cx) || !begun_ || sealed_ || binding_failed_ ||
        count == 0 || count > 64 || index >= count || offset > bytes || bytes - offset < 4 ||
        !prototype || !symbol.isSymbol() || bound_slots_ >= expected_slots_)
      return bindingFailure(cx);
    Plan* selected = nullptr;
    if (index == 0) {
      if (plan(key) || bound_plans_ >= expected_plans_) return bindingFailure(cx);
      auto fresh = std::unique_ptr<Plan>(new (std::nothrow) Plan);
      if (!fresh) { JS_ReportOutOfMemory(cx); binding_failed_ = true; return false; }
      fresh->slots.reset(new (std::nothrow) Slot[count]);
      if (!fresh->slots) { JS_ReportOutOfMemory(cx); binding_failed_ = true; return false; }
      fresh->key = key; fresh->bytes = bytes; fresh->count = count;
      fresh->next = std::move(plans_); plans_ = std::move(fresh);
      selected = plans_.get(); ++bound_plans_;
    } else {
      selected = plans_.get(); // Each source-authenticated plan binds contiguously.
    }
    if (!selected || selected->key != key || selected->bytes != bytes ||
        selected->count != count || selected->bound != index) return bindingFailure(cx);
    auto& slot = selected->slots[index];
    slot.offset = offset; slot.resource = resource;
    slot.prototype.init(cx, prototype); slot.symbol.init(cx, symbol);
    ++selected->bound; ++bound_slots_;
    return true;
  }
  // Called natively AFTER JS_ExecuteScript and BEFORE any application ESM.
  // Script omission, failure or a partial table cannot be blessed by guest code.
  bool seal(JSContext* cx) {
    if (!initializing_ || !initializing_(cx) || !begun_ || sealed_ || binding_failed_ ||
        bound_plans_ != expected_plans_ || bound_slots_ != expected_slots_)
      return bindingFailure(cx);
    for (auto* p = plans_.get(); p; p = p->next.get())
      if (p->count != p->bound) return bindingFailure(cx);
    sealed_ = true;
    return true;
  }
  bool prepare(JSContext* cx, uint32_t id, uint32_t key, Getter getter,
               Disposer disposer, uint32_t count) {
    const auto* selected = plan(key);
    // A source-selected overbound/unsupported/ambiguous plan remains the old
    // complete-unlifted/unknown-quarantine route, with no extra runtime node.
    if (!selected) return true;
    if (preparing_ || collecting_) {
      imports_.stopped_ = true; return invalid(cx, "own-plan-reentrant-admission");
    }
    auto* item = imports_.find(id);
    if (!sealed_ || binding_failed_ || !item || item->cx != cx || !getter || !disposer ||
        !item->record_owner.live || !item->record_owner.token.id ||
        !imports_.jobs_.generation() || item->record_owner.token.generation != imports_.jobs_.generation() ||
        !item->disposer || count != selected->count || selected->bytes != item->result_size ||
        find(id) || item->lifecycle.phase() != ImportLifecycle::Phase::Reserved)
      return invalid(cx, "own-plan-record");
    preparing_ = true;
    struct Reset { bool& value; ~Reset() { value = false; } } reset{preparing_};
    const Token record = item->record_owner.token;
    item = nullptr; // Admission can fail/reenter: retain no Record borrow.
    NativeOwner owner;
    if (!imports_.native_.beforeAllocate(cx, owner) || !owner.live) {
      if (owner.live) failed_owner_ = owner;
      imports_.stopped_ = true; return false;
    }
    if (imports_.stopped_) {
      failed_owner_ = owner; return invalid(cx, "own-plan-admission-uncertain");
    }
    auto fresh = std::unique_ptr<Lift>(new (std::nothrow) Lift);
    if (!fresh) {
      failed_owner_ = owner; imports_.stopped_ = true; JS_ReportOutOfMemory(cx); return false;
    }
    item = imports_.find(id);
    if (!item || item->cx != cx || !item->record_owner.live ||
        !same(item->record_owner.token, record) || imports_.jobs_.generation()!=record.generation || find(id) ||
        item->lifecycle.phase() != ImportLifecycle::Phase::Reserved) {
      failed_owner_ = owner; imports_.stopped_ = true;
      return invalid(cx, "own-plan-admission-owner");
    }
    fresh->id = id; fresh->record = record; fresh->owner = owner;
    fresh->plan = selected; fresh->getter = getter; fresh->disposer = disposer;
    fresh->next = std::move(lifts_); lifts_ = std::move(fresh);
    return true;
  }
  bool uncertain(JSContext* cx, uint32_t id) {
    auto* lift = find(id);
    if (!lift) return true; // Unselected shapes retain the original route.
    if (!current(cx, *lift, imports_.find(id))) {
      lift->uncertain = true; lift->legacy_this = false; return invalid(cx, "own-plan-stale");
    }
    if (!lift->uncertain) lift->legacy_this = true;
    lift->uncertain = true;
    return true;
  }
  bool attach(JSContext* cx, uint32_t id, uint32_t index, JS::MutableHandleObject result) {
    Token token{}; uint32_t handle = 0;
    const Plan* identity = nullptr; Getter getter = nullptr;
    JS::RootedObject prototype(cx); JS::RootedId symbol(cx);
    {
      auto* lift = find(id); auto* item = imports_.find(id);
      if (!lift || !current(cx, *lift, item) || lift->uncertain || lift->cleaning ||
          index >= lift->plan->count || lift->attaching ||
          (lift->transferred & (uint64_t(1) << index))) {
        if (lift) { lift->uncertain = true; lift->legacy_this = false; }
        return invalid(cx, "own-plan-handoff");
      }
      const auto& slot = lift->plan->slots[index];
      token = lift->record; identity = lift->plan;
      getter = lift->getter;
      prototype.set(slot.prototype); symbol.set(slot.symbol);
      lift->attaching = uint64_t(1) << index;
    }
    if(!validateFrame(cx,id,token,identity,getter))return false;
    {
      auto* lift=find(id);auto* item=imports_.find(id);
      if(!lift || !same(lift->record,token) || lift->plan!=identity ||
          !current(cx,*lift,item) || lift->uncertain || !lift->snapshot ||
          lift->attaching!=(uint64_t(1)<<index))return invalid(cx,"own-plan-snapshot-owner");
      handle=lift->handles[index];
    } // NO Record*, frame pointer, Lift* or Slot reference survives a JS API.
    JS::RootedObject wrapper(cx);
    {
      JSAutoRealm realm(cx, prototype);
      wrapper = JS_NewObjectWithGivenProto(cx, nullptr, prototype);
      JS::RootedValue value(cx, JS::NumberValue(static_cast<int32_t>(handle)));
      if (!wrapper || !JS_DefinePropertyById(cx, wrapper, symbol, value, JSPROP_PERMANENT))
        return false; // In-flight remains retained; the result never escapes.
    }
    JS::RootedValue wrapped(cx, JS::ObjectValue(*wrapper));
    if (!JS_WrapValue(cx, &wrapped)) return false;
    if (!wrapped.isObject() || &wrapped.toObject() != wrapper.get())
      return invalid(cx, "own-plan-cross-compartment-result");
    auto* lift = find(id); auto* item = imports_.find(id);
    const uint64_t bit = uint64_t(1) << index;
    if (!lift || !same(lift->record, token) || lift->plan != identity ||
        !current(cx, *lift, item) || lift->uncertain || lift->cleaning ||
        lift->attaching != bit || (lift->transferred & bit)) {
      if (lift) { lift->uncertain = true; lift->legacy_this = false; }
      return invalid(cx, "own-plan-commit");
    }
    lift->transferred |= bit; lift->attaching = 0;
    result.set(wrapper); // First publication, AFTER the scalar commit.
    return true;
  }
  bool deliveredGuard(JSContext* cx, uint32_t id) {
    auto* lift = find(id);
    if (!lift) return true;
    if (!current(cx, *lift, imports_.find(id)) || lift->attaching || lift->cleaning ||
        (lift->uncertain && !lift->legacy_this)) {
      lift->uncertain = true; lift->legacy_this = false; return invalid(cx, "own-plan-delivered-inflight");
    }
    return true;
  }
  bool collect(JSContext* cx) {
    if (collecting_ || preparing_) {
      imports_.stopped_ = true;
      return invalid(cx, "own-plan-reentrant-ACK");
    }
    if (!hasPending()) return true;
    if (imports_.stopped_ || failed_owner_.live) return false;
    collecting_ = true;
    struct Reset { bool& value; ~Reset() { value = false; } } reset{collecting_};
    for (;;) {
      NativeOwner owner;
      {
        auto* link = &lifts_;
        while (*link && imports_.find((*link)->id)) link = &(*link)->next;
        if (!*link) return true;
        owner = (*link)->owner;
        auto physical = std::move(*link); *link = std::move(physical->next);
        physical.reset(); // Physical deletion precedes original ticket ACK.
      } // NO interior link or node/record pointer crosses the callback.
      if (!imports_.native_.acknowledgeRetirement(cx, owner)) {
        failed_owner_ = owner; imports_.stopped_ = true; return false;
      }
      if (imports_.stopped_) return false;
      // Restart at the current head after every potentially reentrant ACK.
    }
  }
  bool finish(JSContext* cx, uint32_t id) {
    uint32_t buffer = 0; uint64_t mask = 0; Token token{}; Disposer dispose = nullptr;
    const Plan* identity=nullptr; Getter getter=nullptr;
    {
      auto* lift=find(id);auto* item=imports_.find(id);
      if(lift && item && current(cx,*lift,item) && lift->transferred && !lift->attaching &&
          !lift->uncertain && !lift->cleaning) {
        token=lift->record;identity=lift->plan;getter=lift->getter;
      }
    }
    if(identity && !validateFrame(cx,id,token,identity,getter))return false;
    {
      auto* lift = find(id); auto* item = imports_.find(id);
      if (!lift || !item || item->disposition == Imports::Disposition::Delivered) {
        // Existing full delivery, cancellation and complete-unlifted disposal.
        if (!imports_.liftCompleted(cx, id)) return false;
        return collect(cx);
      }
      if (!current(cx, *lift, item) || !lift->transferred || lift->attaching ||
          lift->uncertain || lift->cleaning) {
        lift->uncertain = true; lift->legacy_this = false;
        return imports_.liftCompleted(cx, id); // Original partial quarantine.
      }
      lift->cleaning = true;
      item->disposition = Imports::Disposition::Quarantined;
      token = lift->record; mask = lift->transferred; dispose = lift->disposer;
      buffer = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(item->result));
    }
    // Mark non-replayability BEFORE the first original canonical destructor.
    if (!dispose(buffer, static_cast<uint32_t>(mask), static_cast<uint32_t>(mask >> 32))) {
      imports_.stopped_ = true;
      return invalid(cx, "own-plan-disposal");
    }
    auto* lift = find(id); auto* item = imports_.find(id);
    if (!lift || !item || imports_.stopped_ || !same(lift->record, token) || !item->record_owner.live ||
        !same(item->record_owner.token, token) || imports_.jobs_.generation() != token.generation ||
        item->lifecycle.phase() != ImportLifecycle::Phase::Lifting ||
        item->disposition != Imports::Disposition::Quarantined || !lift->cleaning || lift->uncertain)
      return invalid(cx, "own-plan-disposal-owner");
    item->disposition = Imports::Disposition::Disposed;
    // From here any failure keeps Disposed/cleaning and cannot replay a drop.
    if (!item->lifecycle.liftCompleted(cx) || !imports_.collect(cx)) return false;
    return collect(cx);
  }
  void cancel(uint32_t id) { if (auto* p = find(id)) { p->uncertain = true; p->legacy_this = false; } }
  void cancelAll() { for (auto* p = lifts_.get(); p; p = p->next.get()) { p->uncertain = true; p->legacy_this = false; } }
  bool hasPending() const { return lifts_ || failed_owner_.live; }
};

} // namespace lsf::typescript::activation
