// Linked only into the explicit LSF Promise engine build. The ordinary engine
// and ordinary-value recipe do not include this translation unit.
#include "broker_accounting.h"
#include "native_engine.h"
#include "promise_accounting.h"
#include "promise_hooks.h"
#include "reaction_records.h"
#include "extension-api.h"
#include "js/Prefs.h"
#include "jsfriendapi.h"

#include <memory>

namespace lsf::typescript::activation {

namespace {
bool effects_allowed(JSContext* cx) {
  auto* engine = api::Engine::get(cx);
  return engine && engine->state() == api::EngineState::Initialized;
}

BrokerPromiseAccounting::Phase promise_phase(JSContext* cx) {
  auto* engine = api::Engine::get(cx);
  if (!engine) return BrokerPromiseAccounting::Phase::Unavailable;
  switch (engine->state()) {
  case api::EngineState::EngineInitializing:
  case api::EngineState::ScriptPreInitializing:
    return BrokerPromiseAccounting::Phase::CompilerSnapshot;
  case api::EngineState::Initialized:
    return BrokerPromiseAccounting::Phase::Activation;
  default:
    return BrokerPromiseAccounting::Phase::Unavailable;
  }
}

BrokerAccounting accounting(effects_allowed);
BrokerPromiseAccounting promise_accounting(promise_phase, accounting);
PromiseRecords promises(promise_accounting);
ReactionRecords reactions(promise_accounting, accounting);
std::unique_ptr<JobQueue> queue;

bool before_promise_allocate(JSContext* cx, void** output) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx) &&
         promises.beforeAllocate(cx, output);
}
bool before_reaction_allocate(JSContext* cx, void** output) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx) &&
         reactions.beforeAllocate(cx, output);
}
void settled_promise(JSContext* cx, JSObject* promise) {
  promises.settled(cx, promise);
}
void* reaction_record(JSContext* cx, JSObject* reaction) {
  return reactions.record(cx, reaction);
}
void sweep_owned_objects(JSTracer* tracer, void*) {
  promises.sweep(tracer);
  reactions.sweep(tracer);
}
void complete_owned_collection(JS::GCContext*, JSFinalizeStatus status, void*) {
  if (status != JSFINALIZE_COLLECTION_END) return;
  promises.collectionCompleted();
  reactions.collectionCompleted();
}
bool transfer_reaction(JSContext* cx, JS::HandleObject job, JobOwners& owners,
                       bool& transferred) {
  void* record = nullptr;
  if (!JS::ActivationReactionRecordForJob(cx, job, &record)) return false;
  if (!record) return true;
  if (!reactions.transfer(cx, record, owners)) return false;
  transferred = true;
  return true;
}
const JS::ActivationPromiseHooks promise_hooks{
    before_promise_allocate, PromiseRecords::allocationFailed,
    PromiseRecords::created, settled_promise,
    before_reaction_allocate, ReactionRecords::allocationFailed,
    ReactionRecords::created, reaction_record};
}

// Called before JS_Init. Firefox147 defaults to a second microtask queue that
// bypasses enqueuePromiseJob; that queue is not part of this explicit profile.
void configure_job_dispatch() {
  JS::Prefs::set_use_js_microtask_queue(false);
}

// Called after the engine's internal dispatch initialization. The queue and
// its rooted records live with this engine/Store, never in a tenant daemon.
bool install_job_dispatch(JSContext* cx) {
  if (queue) {
    JS_ReportErrorASCII(cx, "activation-runtime-job-queue-already-installed");
    return false;
  }
  queue.reset(new (std::nothrow) JobQueue(accounting, transfer_reaction));
  if (!queue) {
    JS_ReportOutOfMemory(cx);
    return false;
  }
  if (!JS_AddWeakPointerZonesCallback(cx, sweep_owned_objects, nullptr) ||
      !JS_AddFinalizeCallback(cx, complete_owned_collection, nullptr) ||
      !JS::SetActivationPromiseHooks(cx, &promise_hooks)) return false;
  JS::SetJobQueue(cx, queue.get());
  return true;
}

bool snapshot_jobs_empty(JSContext* cx) {
  if (!queue || !queue->empty() || queue->isDrainingStopped() ||
      api::Engine::has_pending_async_tasks() || promises.hasPendingPromises() ||
      reactions.hasPendingReactions() || !reactions.checkpoint(cx) ||
      !promises.checkpoint(cx)) {
    JS_ReportErrorASCII(cx, "activation-runtime-pending-work-during-snapshot-denied");
    return false;
  }
  return true;
}

bool acknowledge_promise_retirement(JSContext* cx) {
  return reactions.checkpoint(cx) && promises.checkpoint(cx);
}

bool has_pending_promises() {
  return promises.hasPendingPromises();
}

bool cancel_job_dispatch(JSContext* cx) {
  return queue && queue->cancelQueued(cx);
}

} // namespace lsf::typescript::activation
