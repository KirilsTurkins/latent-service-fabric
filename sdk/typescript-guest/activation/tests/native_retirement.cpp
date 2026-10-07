// Real physical C++ ownership reference, no LSF host or JS engine substitute.
#include "../native_retirement.h"
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;
struct Owner { unsigned id = 0; bool live = false; };
using Records = NativeRetirement<Owner>;
static Records::Record* watched = nullptr;
static bool body_destroyed = false;
static bool body_while_physical = false;
struct Body {
  ~Body() {
    body_destroyed = true;
    body_while_physical = watched && watched->physical;
  }
};

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  Records records;
  Records::Record* first = nullptr;
  unsigned acknowledgements = 0;
  bool in_gc = false;
  bool host_in_gc = false;
  bool refuse = false;
  auto acknowledge = [&](Owner& owner) {
    if (in_gc) host_in_gc = true;
    if (refuse) return false;
    if (!owner.live) return false;
    ++acknowledgements;
    owner.live = false;
    return true;
  };
  if (!records.track({1, true}, first) || !first || !records.hasPhysical()) return 3;
  int status = 1;
  const char* selected = argv[1];
  if (!std::strcmp(selected, "physical-container-retains-charge")) {
    status = records.checkpoint(acknowledge) && acknowledgements == 0 &&
             first->owner.live && records.hasPhysical() ? 0 : 1;
    Records::physicallyRetired(first);
    records.collectionCompleted();
  } else if (!std::strcmp(selected, "destructor-never-acknowledges")) {
    in_gc = true;
    Records::physicallyRetired(first);
    status = acknowledgements == 0 && !records.hasPhysical() && first->owner.live &&
             !first->collection_completed ? 0 : 1;
    in_gc = false;
    records.collectionCompleted();
  } else if (!std::strcmp(selected, "safe-checkpoint-needs-collection-end")) {
    Records::physicallyRetired(first);
    status = records.checkpoint(acknowledge) && acknowledgements == 0 &&
             first->owner.live && records.hasUnacknowledgedRetirement() ? 0 : 1;
    records.collectionCompleted();
  } else if (!std::strcmp(selected, "collection-end-never-calls-host")) {
    in_gc = true;
    Records::physicallyRetired(first);
    records.collectionCompleted();
    status = acknowledgements == 0 && first->owner.live && first->collection_completed ? 0 : 1;
    in_gc = false;
  } else if (!std::strcmp(selected, "failed-ack-retains-exact-owner")) {
    Records::physicallyRetired(first);
    records.collectionCompleted();
    refuse = true;
    const bool result = records.checkpoint(acknowledge);
    status = !result && records.stopped() && records.hasRetained() && first->owner.id == 1 &&
             first->owner.live && acknowledgements == 0 ? 0 : 1;
    Records::Record* forbidden = nullptr;
    status = status == 0 && !records.track({2, true}, forbidden) && !forbidden ? 0 : 1;
    refuse = false;
  } else if (!std::strcmp(selected, "independent-live-graph-not-refunded")) {
    Records::Record* second = nullptr;
    if (!records.track({2, true}, second)) return 3;
    Records::physicallyRetired(first);
    records.collectionCompleted();
    const bool result = records.checkpoint(acknowledge);
    status = result && acknowledgements == 1 && records.hasPhysical() && second->owner.live ? 0 : 1;
    Records::physicallyRetired(second);
    records.collectionCompleted();
  } else if (!std::strcmp(selected, "move-lease-does-not-retire-source-owner")) {
    NativeLease<Records> original;
    if (!original.bind(first)) return 3;
    {
      auto moved = std::move(original);
      status = first->physical && first->owner.live && acknowledgements == 0 ? 0 : 1;
    }
    status = status == 0 && !first->physical && first->owner.live ? 0 : 1;
    records.collectionCompleted();
  } else if (!std::strcmp(selected, "container-body-destructs-before-owner-retirement")) {
    watched = first;
    NativeLease<Records> accepted;
    if (!accepted.bind(first)) return 3;
    {
      OwnedNativeContainer<Records,Body> body(std::move(accepted));
      if (body_destroyed || !first->physical) return 3;
    }
    status = body_destroyed && body_while_physical && !first->physical && first->owner.live &&
             acknowledgements == 0 ? 0 : 1;
    records.collectionCompleted();
  } else return 4;
  if (!records.checkpoint(acknowledge) || records.hasRetained() || records.hasPhysical() || host_in_gc)
    status = 1;
  const auto before = acknowledgements;
  if (!records.checkpoint(acknowledge) || acknowledgements != before) status = 1;
  std::printf("{\"case\":\"%s\",\"status\":%d,\"acknowledgements\":%u,\"retained\":%s,\"hostcallInGC\":%s}\n",
              selected, status, acknowledgements, records.hasRetained() ? "true" : "false",
              host_in_gc ? "true" : "false");
  return status;
}
