// Captured from the pinned ComponentizeJS/source-splicer generated Fetch binding.
// Source-only semantic control, not signed execution evidence.
async function export_api_1_0_0$run(arg0, arg1, arg2, arg3) {
  var ptr0 = arg1;
  var len0 = arg2;
  var result0 = TEXT_DECODER_UTF8.decode(new Uint8Array($memory.buffer, ptr0, len0));
  _debugLog(' [Instruction::CallInterface] (sync, @ enter)');
  let hostProvided = true;

  let parentTask;
  let task;
  let subtask;

  const createTask = () => {
    const results = createNewCurrentTask({
      componentIdx: -1,
      isAsync: false,
      entryFnName: 'api100Run',
      getCallbackFn: () => null,
      callbackFnName: null,
      errHandling: 'none',
      callingWasmExport: false,
    });
    task = results[0];
  };

  taskCreation: {
    parentTask = getCurrentTask(
    -1,
    _getGlobalCurrentTaskMeta(-1)?.taskID,
    )?.task;

    if (!parentTask) {
      createTask();
      break taskCreation;
    }

    createTask();

    if (hostProvided) {
      subtask = parentTask.getLatestSubtask();
      if (!subtask) {
        throw new Error(`Missing subtask (in parent task [${parentTask.id()}]) for host import, has the import been lowered? (ensure asyncImports are set properly)`);
      }
      task.setParentSubtask(subtask);
    }
  }


  const started = await task.enter({ isHost: hostProvided });
  if (!started) {
    _debugLog('[Instruction::CallInterface] failed to enter task', {
      taskID: task.id(),
      subtaskID: currentSubtask?.id(),
    });
    throw new Error("failed to enter task");
  }


  let ret;

  try {
    ret = await  _withGlobalCurrentTaskMetaAsync({
      componentIdx: task.componentIdx(),
      taskID: task.id(),
      fn: () => api100Run(arg0 >>> 0, result0),
    })
    ;
  } catch (err) {

    task.setErrored(err);
    task.reject(err);
    task.exit();
    return task.completionPromise();

  }


  var encodeRes = _utf8AllocateAndEncode(ret, $realloc, $memory);
  var ptr1= encodeRes.ptr;
  var len1 = encodeRes.len;

  dataView($memory).setUint32(arg3 + 4, len1, true);
  dataView($memory).setUint32(arg3 + 0, ptr1, true);
  _debugLog('[Instruction::Return]', {
    funcName: 'run',
    paramCount: 0,
    async: false,
    postReturn: false
  });
  task.resolve([ret]);
  task.exit();
}
