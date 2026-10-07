// Real intrinsic controls for the distinct source-built Promise engine.
// Fixture admission is not LSF host or signed-component qualification.
#include "../promise_hooks.h"
#include "../promise_records.h"
#include "../reaction_records.h"
#include "js/CompilationAndEvaluation.h"
#include "js/GCAPI.h"
#include "js/Initialization.h"
#include "js/Prefs.h"
#include "js/SourceText.h"
#include "jsfriendapi.h"
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;

struct FixtureJobs final : Accounting {
  unsigned tasks = 0, queued = 0, admitted = 0, entries = 0, exits = 0;
  unsigned limit = 16;
  uint64_t next = 1;
  bool refuse_retirement = false;
  bool admit(JSContext* cx, JobOwners& owners) override {
    if (queued >= limit) {
      JS_ReportErrorASCII(cx, "fixture-pending-reaction-exhausted");
      return false;
    }
    owners.task = {1, next++};
    owners.queued = {1, next++};
    owners.task_live = owners.queued_live = true;
    ++tasks; ++queued; ++admitted;
    return true;
  }
  bool release(JobOwners& owners) {
    if (refuse_retirement) return false;
    if (owners.queued_live) { owners.queued_live = false; --queued; }
    if (owners.task_live) { owners.task_live = false; --tasks; }
    return true;
  }
  bool rollback(JSContext*, JobOwners& owners) override { return release(owners); }
  bool started(JSContext*, JobOwners& owners) override {
    if (!owners.task_live || !owners.queued_live) return false;
    owners.queued_live = false; --queued; ++entries;
    return true;
  }
  bool completed(JSContext*, JobOwners& owners) override {
    if (!release(owners)) return false;
    ++exits;
    return true;
  }
  bool cancelled(JSContext*, JobOwners& owners) override { return release(owners); }
};

struct FixtureNative final : PromiseAccounting {
  unsigned owners = 0, admissions = 0, acknowledgements = 0, limit = 64;
  uint64_t next = 1;
  bool refuse_retirement = false, in_gc = false, hostcall_in_gc = false;
  bool beforeAllocate(JSContext* cx, NativeOwner& owner) override {
    if (in_gc) hostcall_in_gc = true;
    if (owners >= limit) {
      JS_ReportErrorASCII(cx, "fixture-native-allocation-exhausted");
      return false;
    }
    owner.token = {1, next++}; owner.live = true;
    ++owners; ++admissions;
    return true;
  }
  bool acknowledgeRetirement(JSContext*, NativeOwner& owner) override {
    if (in_gc) hostcall_in_gc = true;
    if (!owner.live) return true;
    if (refuse_retirement) return false;
    owner.live = false; --owners; ++acknowledgements;
    return true;
  }
};

static PromiseRecords* promise_records;
static ReactionRecords* reaction_records;
static unsigned promises_created = 0, promises_settled = 0, promises_finalized = 0;
static unsigned reactions_created = 0, reactions_finalized = 0;
static bool before_promise(JSContext* cx, void** output) {
  return promise_records->checkpoint(cx) && reaction_records->checkpoint(cx) &&
         promise_records->beforeAllocate(cx, output);
}
static bool before_reaction(JSContext* cx, void** output) {
  return promise_records->checkpoint(cx) && reaction_records->checkpoint(cx) &&
         reaction_records->beforeAllocate(cx, output);
}
static void created_promise(JSContext* cx, JSObject* object, void* record) {
  ++promises_created; PromiseRecords::created(cx, object, record);
}
static void settled_promise(JSContext* cx, JSObject* object) {
  ++promises_settled; promise_records->settled(cx, object);
}
static void created_reaction(JSContext* cx, JSObject* object, void* record) {
  ++reactions_created; ReactionRecords::created(cx, object, record);
}
static void* reaction_record(JSContext* cx, JSObject* object) {
  return reaction_records->record(cx, object);
}
static void weak_sweep(JSTracer* tracer, void*) {
  promise_records->sweep(tracer);
  reaction_records->sweep(tracer);
}
static void collection_completed(JS::GCContext*, JSFinalizeStatus status, void*) {
  if (status != JSFINALIZE_COLLECTION_END) return;
  promises_finalized += promise_records->collectionCompleted();
  reactions_finalized += reaction_records->collectionCompleted();
}
static bool transfer_reaction(JSContext* cx, JS::HandleObject job, JobOwners& owners,
                              bool& transferred) {
  void* record = nullptr;
  if (!JS::ActivationReactionRecordForJob(cx, job, &record)) return false;
  if (!record) return true;
  if (!reaction_records->transfer(cx, record, owners)) return false;
  transferred = true;
  return true;
}

static bool evaluate(JSContext* cx, const char* code, JS::MutableHandleValue output) {
  JS::CompileOptions options(cx);
  options.setFileAndLine("source-built-intrinsic-promise-controls.js", 1);
  JS::SourceText<mozilla::Utf8Unit> text;
  return text.init(cx, code, std::strlen(code), JS::SourceOwnership::Borrowed) &&
         JS::Evaluate(cx, options, text, output);
}
static bool expect(JSContext* cx, const char* code) {
  JS::RootedValue output(cx);
  return evaluate(cx, code, &output) && output.isBoolean() && output.toBoolean();
}
static void collect(JSContext* cx, FixtureNative& native) {
  native.in_gc = true;
  JS_GC(cx);
  native.in_gc = false;
}
static bool checkpoint(JSContext* cx) {
  return reaction_records->checkpoint(cx) && promise_records->checkpoint(cx);
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  JS::Prefs::set_use_js_microtask_queue(false);
  if (!JS_Init()) return 3;
  JSContext* cx = JS_NewContext(32 * 1024 * 1024);
  if (!cx) return 4;
  FixtureJobs jobs;
  FixtureNative native;
  PromiseRecords promises(native);
  ReactionRecords reactions(native, jobs);
  promise_records = &promises;
  reaction_records = &reactions;
  JobQueue queue(jobs, transfer_reaction);
  int status = 1;
  {
    if (!js::UseInternalJobQueues(cx) || !JS::InitSelfHostedCode(cx)) return 5;
    JS::SetJobQueue(cx, &queue);
    static const JSClass global_class = {
        "LSFIntrinsicPromiseControls", JSCLASS_GLOBAL_FLAGS, &JS::DefaultGlobalClassOps};
    JS::RealmOptions options;
    JS::RootedObject global(cx, JS_NewGlobalObject(cx, &global_class, nullptr,
                                                 JS::FireOnNewGlobalHook, options));
    if (!global) return 6;
    JSAutoRealm realm(cx, global);
    if (!JS::InitRealmStandardClasses(cx)) return 7;
    static const JS::ActivationPromiseHooks hooks{
        before_promise, PromiseRecords::allocationFailed, created_promise,
        settled_promise, before_reaction, ReactionRecords::allocationFailed,
        created_reaction, reaction_record};
    if (!JS_AddWeakPointerZonesCallback(cx, weak_sweep, nullptr) ||
        !JS_AddFinalizeCallback(cx, collection_completed, nullptr) ||
        !JS::SetActivationPromiseHooks(cx, &hooks)) return 8;
    JS::RootedValue output(cx);
    const char* selected = argv[1];
    if (!std::strcmp(selected, "pending-reactions")) {
      if (!evaluate(cx, "globalThis.called=0; globalThis.root=new Promise(resolve=>{globalThis.finish=resolve;});"
          "root.then(()=>called++); root.then(()=>called++);", &output)) return 9;
      status = promises.hasPendingPromises() && reactions.hasPendingReactions() &&
               queue.empty() && jobs.queued == 2 && jobs.tasks == 2 &&
               jobs.entries == 0 && reactions_created == 2 && expect(cx, "called===0") ? 0 : 1;
    } else if (!std::strcmp(selected, "reaction-exhaustion")) {
      jobs.limit = 1;
      bool evaluated = evaluate(cx, "globalThis.called=0; globalThis.root=new Promise(()=>{});"
          "root.then(()=>called++); root.then(()=>called++);", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && reactions_created == 1 &&
               jobs.queued == 1 && jobs.tasks == 1 && jobs.entries == 0 && queue.empty() ? 0 : 1;
      JS_ClearPendingException(cx);
    } else if (!std::strcmp(selected, "native-preallocation")) {
      native.limit = 0;
      bool evaluated = evaluate(cx, "new Promise(()=>{});", &output);
      status = !evaluated && JS_IsExceptionPending(cx) && promises_created == 0 &&
               native.owners == 0 && native.admissions == 0 ? 0 : 1;
      JS_ClearPendingException(cx);
    } else if (!std::strcmp(selected, "settlement-not-refund")) {
      if (!evaluate(cx, "globalThis.root=new Promise(resolve=>resolve(42));", &output)) return 9;
      status = promises_created == 1 && promises_settled == 1 &&
               !promises.hasPendingPromises() && native.owners == 1 &&
               checkpoint(cx) && native.owners == 1 && native.acknowledgements == 0 ? 0 : 1;
    } else if (!std::strcmp(selected, "gc-ack-retained")) {
      if (!evaluate(cx, "globalThis.root=new Promise(resolve=>resolve(42));", &output)) return 9;
      output.setUndefined();
      if (!evaluate(cx, "globalThis.root=null;", &output)) return 9;
      output.setUndefined();
      native.refuse_retirement = true;
      collect(cx, native);
      bool retained = promises_finalized == 1 && native.owners == 1 &&
                      native.acknowledgements == 0 && !checkpoint(cx) && native.owners == 1;
      native.refuse_retirement = false;
      status = retained && checkpoint(cx) && native.owners == 0 &&
               native.acknowledgements == 1 && !native.hostcall_in_gc ? 0 : 1;
    } else if (!std::strcmp(selected, "transfer-same-owners")) {
      if (!evaluate(cx, "globalThis.answer=0; globalThis.root=new Promise(resolve=>{globalThis.finish=resolve;});"
          "root.then(value=>{answer=value;});", &output)) return 9;
      bool before = jobs.admitted == 1 && jobs.queued == 1 && jobs.tasks == 1 && queue.empty();
      if (!evaluate(cx, "finish(42);", &output)) return 9;
      bool queued = jobs.admitted == 1 && jobs.queued == 1 && jobs.tasks == 1 && !queue.empty();
      js::RunJobs(cx);
      status = before && queued && !JS_IsExceptionPending(cx) && queue.empty() &&
               jobs.admitted == 1 && jobs.entries == 1 && jobs.exits == 1 &&
               jobs.tasks == 0 && jobs.queued == 0 && expect(cx, "answer===42") ? 0 : 1;
    } else if (!std::strcmp(selected, "nested-await")) {
      if (!evaluate(cx, "globalThis.answer=0; globalThis.order=[];"
          "(async()=>{order.push('before');await Promise.resolve();order.push('after');return 42;})()"
          ".then(value=>{answer=value;});order.push('sync');", &output)) return 9;
      js::RunJobs(cx);
      status = !JS_IsExceptionPending(cx) && queue.empty() && jobs.tasks == 0 && jobs.queued == 0 &&
               jobs.admitted == jobs.entries && jobs.entries == jobs.exits && reactions_created >= 2 &&
               expect(cx, "answer===42&&order.join(',')==='before,sync,after'") ? 0 : 1;
    } else if (!std::strcmp(selected, "gc-pending-ack")) {
      if (!evaluate(cx, "globalThis.root=new Promise(()=>{});root.then(()=>42);", &output)) return 9;
      output.setUndefined();
      if (!evaluate(cx, "globalThis.root=null;", &output)) return 9;
      output.setUndefined();
      jobs.refuse_retirement = true;
      collect(cx, native);
      bool retained = reactions_finalized == 1 && jobs.tasks == 1 && jobs.queued == 1 &&
                      !checkpoint(cx) && jobs.tasks == 1 && jobs.queued == 1 && jobs.entries == 0;
      jobs.refuse_retirement = false;
      status = retained && checkpoint(cx) && jobs.tasks == 0 && jobs.queued == 0 &&
               native.owners == 0 && jobs.entries == 0 && !native.hostcall_in_gc ? 0 : 1;
    }
    // Remove all ordinary control captures, retire actual native frames, then
    // collect their real objects. Neither cancellation nor GC alone refunds.
    JS_ClearPendingException(cx);
    jobs.refuse_retirement = native.refuse_retirement = false;
    output.setUndefined();
    if (!evaluate(cx, "globalThis.root=null;globalThis.finish=null;globalThis.order=null;", &output)) return 10;
    output.setUndefined();
    bool cancelled = queue.cancelQueued(cx);
    collect(cx, native);
    bool cleaned = cancelled && checkpoint(cx) && queue.empty() && jobs.tasks == 0 &&
                   jobs.queued == 0 && native.owners == 0 && !native.hostcall_in_gc;
    if (!cleaned) status = 1;
    std::printf("{\"case\":\"%s\",\"status\":%d,\"tasks\":%u,\"queued\":%u,"
        "\"native\":%u,\"jobsAdmitted\":%u,\"entries\":%u,\"exits\":%u,"
        "\"promisesCreated\":%u,\"promisesSettled\":%u,\"promisesFinalized\":%u,"
        "\"reactionsCreated\":%u,\"reactionsFinalized\":%u,\"hostcallInGC\":%s}\n",
        selected,status,jobs.tasks,jobs.queued,native.owners,jobs.admitted,jobs.entries,jobs.exits,
        promises_created,promises_settled,promises_finalized,reactions_created,reactions_finalized,
        native.hostcall_in_gc ? "true" : "false");
  }
  // Physical records outlive the Context's last finalization, while all owners
  // were already observed retired above. No dangling callback target on teardown.
  JS_DestroyContext(cx);
  JS_ShutDown();
  return status;
}
