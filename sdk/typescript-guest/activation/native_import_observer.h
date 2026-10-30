// Optional acknowledgement of one canonical import's borrow release. This is
// not evidence that its provider IoCall, IoTransfer or physical socket retired.
#pragma once
#include "native_ownership.h"
#include "js/Class.h"
#include "js/Object.h"
#include "js/Promise.h"
#include "js/RootingAPI.h"
#include "jsapi.h"
#include <memory>

namespace lsf::typescript::activation {

class ImportBorrowObserver final {
  enum Slot : uint32_t {
    Manager, Context, RecordId, GenerationLow, GenerationHigh, OwnerLow, OwnerHigh,
    Promise, Released, Count
  };
  inline static const JSClass handle_class_ = {
    "LSFPrivateImportBorrow", JSCLASS_HAS_RESERVED_SLOTS(Count)
  };

  static void word(JSObject* object, Slot slot, uint32_t value) {
    JS::SetReservedSlot(object, slot, JS::Int32Value(static_cast<int32_t>(value)));
  }
  static bool sameWord(JSObject* object, Slot slot, uint32_t value) {
    const auto stored = JS::GetReservedSlot(object, slot);
    return stored.isInt32() && static_cast<uint32_t>(stored.toInt32()) == value;
  }
  static bool sameToken(JSObject* object, Token token) {
    return sameWord(object, GenerationLow, static_cast<uint32_t>(token.generation)) &&
      sameWord(object, GenerationHigh, static_cast<uint32_t>(token.generation >> 32)) &&
      sameWord(object, OwnerLow, static_cast<uint32_t>(token.id)) &&
      sameWord(object, OwnerHigh, static_cast<uint32_t>(token.id >> 32));
  }

public:
  NativeOwner allocation_owner{};
  std::unique_ptr<ImportBorrowObserver> following;
  const uint32_t record_id;
  const Token record_owner;
  JSContext* const context;
  JS::PersistentRootedObject handle;
  bool cancellation_requested = false;
  bool quarantined = false;

  ImportBorrowObserver(JSContext* cx, uint32_t id, Token owner)
      : record_id(id), record_owner(owner), context(cx), handle(cx) {}

  bool matchesOriginal(JSContext* cx, uint32_t id, Token owner) const {
    return context == cx && record_id == id && record_owner.generation == owner.generation &&
      record_owner.id == owner.id;
  }

  bool initialize(JSContext* cx, const void* manager, uint32_t id, Token owner) {
    // The caller already admitted this observer's native storage/root owner.
    // The original Promise hooks independently preadmit the managed Promise.
    JS::RootedObject promise(cx, JS::NewPromiseObject(cx, nullptr));
    if (!promise) return false;
    JS::RootedObject object(cx, JS_NewObject(cx, &handle_class_));
    if (!object) return false;
    JS::SetReservedSlot(object, Manager, JS::PrivateValue(const_cast<void*>(manager)));
    JS::SetReservedSlot(object, Context, JS::PrivateValue(cx));
    word(object, RecordId, id);
    word(object, GenerationLow, static_cast<uint32_t>(owner.generation));
    word(object, GenerationHigh, static_cast<uint32_t>(owner.generation >> 32));
    word(object, OwnerLow, static_cast<uint32_t>(owner.id));
    word(object, OwnerHigh, static_cast<uint32_t>(owner.id >> 32));
    JS::SetReservedSlot(object, Promise, JS::ObjectValue(*promise));
    JS::SetReservedSlot(object, Released, JS::BooleanValue(false));
    handle = object;
    return true;
  }

  static bool belongsTo(JSContext* cx, JS::HandleObject object, const void* manager,
                        uint64_t generation) {
    // Reserved slots are never public JS fields. In particular no caller can
    // supply an ambient numeric record id, owner token or another context.
    return object && JS::GetClass(object) == &handle_class_ &&
      JS::GetReservedSlot(object, Manager).toPrivate() == manager &&
      JS::GetReservedSlot(object, Context).toPrivate() == cx && generation != 0 &&
      sameWord(object, GenerationLow, static_cast<uint32_t>(generation)) &&
      sameWord(object, GenerationHigh, static_cast<uint32_t>(generation >> 32));
  }
  static uint32_t recordId(JS::HandleObject object) {
    return static_cast<uint32_t>(JS::GetReservedSlot(object, RecordId).toInt32());
  }
  static bool matches(JS::HandleObject object, uint32_t id, Token owner) {
    return sameWord(object, RecordId, id) && sameToken(object, owner);
  }
  static bool released(JS::HandleObject object) {
    return JS::GetReservedSlot(object, Released).toBoolean();
  }
  static JSObject* promise(JS::HandleObject object) {
    return &JS::GetReservedSlot(object, Promise).toObject();
  }
  static bool acknowledge(JSContext* cx, JS::HandleObject object) {
    // Only Imports::collect calls this, after actual subtask/drop, original
    // record/capture/buffer destruction and every original acknowledgement.
    JS::RootedObject pending(cx, promise(object));
    if (!JS::ResolvePromise(cx, pending, JS::UndefinedHandleValue)) return false;
    JS::SetReservedSlot(object, Released, JS::BooleanValue(true));
    return true;
  }
};
} // namespace lsf::typescript::activation
