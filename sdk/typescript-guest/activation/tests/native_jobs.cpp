// Actual pinned SpiderMonkey integration controls. The fixture broker below
// deliberately does not claim host admission or signed-component qualification.
#include "../native_job_queue.h"
#include "js/CompilationAndEvaluation.h"
#include "js/Initialization.h"
#include "js/Prefs.h"
#include "js/SourceText.h"
#include "jsfriendapi.h"

#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;

struct FixtureAccounting final : Accounting {
  unsigned tasks = 0, queued = 0, entries = 0, exits = 0, admissions = 0;
  unsigned max_tasks = 0, max_queued = 0;
  unsigned task_limit = 8, queue_limit = 8;
  bool reject_completion = false, reject_rollback = false;
  bool reject_queue = false;
  JobQueue* queue = nullptr;
  uint64_t next = 1;

  bool admit(JSContext* cx, JobOwners& owners) override {
    if (tasks >= task_limit) {
      JS_ReportErrorASCII(cx, "fixture-task-exhausted");
      return false;
    }
    owners.task = {1, next++};
    owners.task_live = true;
    ++tasks;
    if (tasks > max_tasks) max_tasks = tasks;
    if (reject_queue || queued >= queue_limit) {
      JS_ReportErrorASCII(cx, "fixture-queue-exhausted");
      return false;
    }
    owners.queued = {1, next++};
    owners.queued_live = true;
    ++queued;
    if (queued > max_queued) max_queued = queued;
    ++admissions;
    return true;
  }
  bool rollback(JSContext*, JobOwners& owners) override {
    if (reject_rollback) return false;
    release(owners);
    return true;
  }
  bool started(JSContext* cx, JobOwners& owners) override {
    // A checkpoint requested from the entry hook must not run a sibling inside
    // the current job. This also exercises the native reentrancy guard.
    if (queue) queue->runJobs(cx);
    if (owners.queued_live) {
      --queued;
      owners.queued_live = false;
    }
    ++entries;
    return true;
  }
  bool completed(JSContext*, JobOwners& owners) override {
    if (reject_completion) return false;
    if (owners.task_live) {
      --tasks;
      owners.task_live = false;
      ++exits;
    }
    return true;
  }
  bool cancelled(JSContext*, JobOwners& owners) override {
    release(owners);
    return true;
  }
  void release(JobOwners& owners) {
    if (owners.queued_live) {
      --queued;
      owners.queued_live = false;
    }
    if (owners.task_live) {
      --tasks;
      owners.task_live = false;
    }
  }
};

static bool evaluate(JSContext* cx, const char* source, JS::MutableHandleValue result) {
  JS::CompileOptions options(cx);
  options.setFileAndLine("native-promise-controls.js", 1);
  JS::SourceText<mozilla::Utf8Unit> text;
  if (!text.init(cx, source, std::strlen(source), JS::SourceOwnership::Borrowed)) return false;
  return JS::Evaluate(cx, options, text, result);
}

static bool expect(JSContext* cx, const char* source) {
  JS::RootedValue result(cx);
  return evaluate(cx, source, &result) && result.isBoolean() && result.toBoolean();
}

static bool native_failure(JSContext* cx, unsigned, JS::Value*) {
  JS_ReportErrorASCII(cx, "expected-native-callback-error");
  return false;
}

// An actual JS::Call invokes this native callback while the production queue
// owns its frame. The fixture broker is still not a host activation ledger.
static FixtureAccounting* cancelling_accounting = nullptr;
static const char* cancellation_case = nullptr;
static bool cancellation_observed = false;
static bool reentrant_cancel(JSContext* cx, unsigned argc, JS::Value* vp) {
  auto& accounting = *cancelling_accounting;
  auto& queue = *accounting.queue;
  const auto admissions = accounting.admissions;
  const auto entries = accounting.entries;
  const auto tasks = accounting.tasks;
  const auto queued = accounting.queued;
  const bool refused = !queue.cancelQueued(cx);
  const bool fenced = queue.isDrainingStopped();
  const bool retained = accounting.tasks == tasks && accounting.queued == queued &&
                        tasks == 2 && queued == 1 && accounting.exits == 0;
  JS::RootedFunction late(cx, JS_NewFunction(cx, native_failure, 0, 0, "lateJob"));
  if (!late) return false;
  JS::RootedObject callable(cx, JS_GetFunctionObject(late));
  JS::RootedObject none(cx);
  const bool rejected = !queue.enqueuePromiseJob(cx, none, callable, none, none);
  const bool rejection_reported = JS_IsExceptionPending(cx);
  JS_ClearPendingException(cx);
  queue.runJobs(cx);
  cancellation_observed = refused && fenced && retained && rejected && rejection_reported &&
      accounting.admissions == admissions && accounting.entries == entries &&
      accounting.tasks == tasks && accounting.queued == queued;
  JS::CallArgsFromVp(argc, vp).rval().setUndefined();
  if (std::strstr(cancellation_case, "exception")) {
    JS_ReportErrorASCII(cx, "expected-reentrant-callback-error");
    return false;
  }
  return cancellation_observed && !std::strstr(cancellation_case, "false");
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  // The pinned engine's alternate JSMicroTask queue bypasses enqueuePromiseJob.
  // Select the original callback queue before JS initialization, explicitly.
  JS::Prefs::set_use_js_microtask_queue(false);
  if (!JS_Init()) return 3;
  JSContext* cx = JS_NewContext(32 * 1024 * 1024);
  if (!cx) return 4;
  int status = 1;
  {
    FixtureAccounting accounting;
    JobQueue queue(accounting);
    accounting.queue = &queue;
    if (!js::UseInternalJobQueues(cx) || !JS::InitSelfHostedCode(cx)) return 5;
    JS::SetJobQueue(cx, &queue);
    static const JSClass global_class = {
        "LSFNativeJobControls", JSCLASS_GLOBAL_FLAGS, &JS::DefaultGlobalClassOps};
    JS::RealmOptions options;
    JS::RootedObject global(cx, JS_NewGlobalObject(cx, &global_class, nullptr,
                                                 JS::FireOnNewGlobalHook, options));
    if (!global) return 6;
    JSAutoRealm realm(cx, global);
    if (!JS::InitRealmStandardClasses(cx)) return 7;
    JS::RootedValue result(cx);

    const char* selected = argv[1];
    if (!std::strcmp(selected, "ordering")) {
      if (!evaluate(cx,
          "globalThis.order=[]; globalThis.answer=0;"
          "globalThis.root=new Promise(resolve => { globalThis.finish=resolve; });"
          "root.then(value => { order.push('root'); answer=value; });"
          "Promise.resolve().then(() => { order.push('first');"
          "  Promise.resolve().then(() => { order.push('nested'); finish(42); }); });"
          "Promise.resolve().then(() => order.push('second'));"
          "order.push('sync');", &result)) return 8;
      bool before = accounting.queued == 2 && accounting.tasks == 2 &&
                    accounting.entries == 0 && expect(cx, "answer===0");
      js::RunJobs(cx);
      status = before && !JS_IsExceptionPending(cx) && queue.empty() &&
               accounting.tasks == 0 && accounting.queued == 0 &&
               accounting.admissions == accounting.entries && accounting.entries == accounting.exits &&
               accounting.entries == 4 &&
               expect(cx, "answer===42 && order.join(',')==='sync,first,second,nested,root'") ? 0 : 1;
    } else if (!std::strcmp(selected, "thenable")) {
      if (!evaluate(cx,
          "globalThis.answer=0; globalThis.calls=0;"
          "Promise.resolve({then(resolve) { calls++; resolve(42); resolve(99); }})"
          ".then(value => { answer=value; });", &result)) return 8;
      js::RunJobs(cx);
      status = queue.empty() && accounting.admissions == 2 &&
               accounting.entries == 2 && accounting.exits == 2 &&
               accounting.tasks == 0 && accounting.queued == 0 &&
               expect(cx, "answer===42 && calls===1") ? 0 : 1;
    } else if (!std::strcmp(selected, "async-await")) {
      if (!evaluate(cx,
          "globalThis.answer=0; globalThis.order=[];"
          "(async () => { order.push('before'); await Promise.resolve();"
          " order.push('after'); return 42; })().then(value => { answer=value; });"
          "order.push('sync');", &result)) return 8;
      js::RunJobs(cx);
      status = queue.empty() && accounting.admissions >= 2 &&
               accounting.admissions == accounting.entries && accounting.entries == accounting.exits &&
               accounting.tasks == 0 && accounting.queued == 0 &&
               expect(cx, "answer===42 && order.join(',')==='before,sync,after'") ? 0 : 1;
    } else if (!std::strcmp(selected, "exhaustion")) {
      accounting.queue_limit = 1;
      const bool evaluated = evaluate(cx,
          "globalThis.called=0; Promise.resolve().then(() => { called++; });"
          "Promise.resolve().then(() => { called++; });", &result);
      const bool rejected = !evaluated && JS_IsExceptionPending(cx) &&
                            accounting.queued == 1 && accounting.tasks == 1 &&
                            accounting.max_queued == 1 && accounting.entries == 0;
      JS_ClearPendingException(cx);
      status = rejected && queue.cancelQueued(cx) && accounting.tasks == 0 &&
               accounting.queued == 0 && queue.empty() && expect(cx, "called===0") ? 0 : 1;
    } else if (!std::strcmp(selected, "retirement-ack")) {
      accounting.reject_completion = true;
      if (!evaluate(cx, "globalThis.called=0; Promise.resolve().then(() => { called++; });", &result)) return 8;
      js::RunJobs(cx);
      const bool retained = queue.isDrainingStopped() && !queue.empty() &&
                            accounting.tasks == 1 && accounting.queued == 0 &&
                            accounting.entries == 1 && accounting.exits == 0 &&
                            expect(cx, "called===1");
      const bool refused = !queue.cancelQueued(cx) && accounting.tasks == 1;
      accounting.reject_completion = false;
      status = retained && refused && queue.cancelQueued(cx) && queue.empty() &&
               accounting.tasks == 0 && accounting.exits == 1 &&
               expect(cx, "called===1") ? 0 : 1;
    } else if (!std::strcmp(selected, "partial-admission-ack")) {
      accounting.reject_queue = true;
      accounting.reject_rollback = true;
      const bool evaluated = evaluate(cx,
          "globalThis.called=0; Promise.resolve().then(() => { called++; });", &result);
      const bool retained = !evaluated && JS_IsExceptionPending(cx) &&
                            accounting.tasks == 1 && accounting.queued == 0 &&
                            !queue.empty() && queue.isDrainingStopped();
      JS_ClearPendingException(cx);
      const bool refused = !queue.cancelQueued(cx) && accounting.tasks == 1;
      accounting.reject_rollback = false;
      status = retained && refused && queue.cancelQueued(cx) && queue.empty() &&
               accounting.tasks == 0 && expect(cx, "called===0") ? 0 : 1;
    } else if (!std::strcmp(selected, "rejection")) {
      if (!evaluate(cx,
          "globalThis.answer=0; Promise.resolve().then(() => { throw new Error('expected'); })"
          ".catch(error => { answer=error.message==='expected' ? 42 : 0; });", &result)) return 8;
      js::RunJobs(cx);
      status = queue.empty() && accounting.tasks == 0 && accounting.queued == 0 &&
               accounting.admissions == accounting.entries && accounting.entries == accounting.exits &&
               expect(cx, "answer===42") ? 0 : 1;
    } else if (!std::strcmp(selected, "reentrant-cancel-success") ||
               !std::strcmp(selected, "reentrant-cancel-false") ||
               !std::strcmp(selected, "reentrant-cancel-exception") ||
               !std::strcmp(selected, "reentrant-cancel-ack-refusal")) {
      cancelling_accounting = &accounting;
      cancellation_case = selected;
      accounting.reject_completion = std::strstr(selected, "refusal") != nullptr;
      JS::RootedFunction first(cx, JS_NewFunction(cx, reentrant_cancel, 0, 0, "cancelJob"));
      JS::RootedFunction sibling(cx, JS_NewFunction(cx, native_failure, 0, 0, "siblingJob"));
      if (!first || !sibling) return 8;
      JS::RootedObject callable(cx, JS_GetFunctionObject(first));
      JS::RootedObject other(cx, JS_GetFunctionObject(sibling));
      JS::RootedObject none(cx);
      if (!queue.enqueuePromiseJob(cx, none, callable, none, none) ||
          !queue.enqueuePromiseJob(cx, none, other, none, none)) return 8;
      js::RunJobs(cx);
      bool correct = cancellation_observed && queue.isDrainingStopped() && !queue.empty() &&
                     accounting.entries == 1 && accounting.queued == 1 &&
                     JS_IsExceptionPending(cx) == (std::strstr(selected, "exception") != nullptr);
      if (accounting.reject_completion) {
        correct = correct && accounting.tasks == 2 && accounting.exits == 0 &&
                  !queue.cancelQueued(cx) && accounting.tasks == 2 && accounting.queued == 1;
        accounting.reject_completion = false;
      }
      correct = correct && queue.cancelQueued(cx) && queue.empty() &&
                accounting.tasks == 0 && accounting.queued == 0 && accounting.exits == 1 &&
                accounting.entries == 1 && queue.cancelQueued(cx);
      status = correct ? 0 : 1;
      cancelling_accounting = nullptr;
    } else if (!std::strcmp(selected, "native-frame-error")) {
      JS::RootedFunction callback(cx, JS_NewFunction(cx, native_failure, 0, 0,
                                                   "nativeFailure"));
      if (!callback) return 8;
      JS::RootedObject callable(cx, JS_GetFunctionObject(callback));
      JS::RootedObject none(cx);
      if (!queue.enqueuePromiseJob(cx, none, callable, none, none)) return 8;
      js::RunJobs(cx);
      status = JS_IsExceptionPending(cx) && queue.isDrainingStopped() &&
               queue.empty() && accounting.tasks == 0 && accounting.queued == 0 &&
               accounting.entries == 1 && accounting.exits == 1 ? 0 : 1;
    }
    std::printf("{\"case\":\"%s\",\"status\":%d,\"nativeAdmissions\":%u,"
                "\"nativeEntries\":%u,\"nativeExits\":%u,\"tasks\":%u,\"queued\":%u,"
                "\"hostAdmissionQualified\":false}\n", selected, status,
                accounting.admissions, accounting.entries, accounting.exits,
                accounting.tasks, accounting.queued);
    JS_ClearPendingException(cx);
    if (!queue.cancelQueued(cx)) status = 1;
    JS::SetJobQueue(cx, nullptr);
  }
  JS_DestroyContext(cx);
  JS_ShutDown();
  return status;
}
