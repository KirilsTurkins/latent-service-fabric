        // Diagnostic-only private source derivation, never the shipped SDK.
        // The actual original catch still calls FailFast with the same object.
        var diagnosticFailFast = handler.Body.Instructions.Single(instruction => instruction.Operand is MethodReference method
            && method.FullName == "System.Void System.Environment::FailFast(System.String,System.Exception)");
        var diagnosticAnchor = diagnosticFailFast.Previous.Previous;
        Require(diagnosticAnchor.OpCode == OpCodes.Ldstr && (string)diagnosticAnchor.Operand == "TimerQueue.TimerHandler failed"
            && diagnosticFailFast.Previous.OpCode == OpCodes.Ldloc_1);
        var diagnosticOriginal = handler.Body.Variables.Single(variable => variable.VariableType.FullName == "System.Exception");
        var diagnosticException = new VariableDefinition(diagnosticOriginal.VariableType);
        handler.Body.Variables.Add(diagnosticException);
        var diagnosticMessage = Type("System.Exception").Methods.Single(method => method.Name == "get_Message" && method.Parameters.Count == 0);
        var diagnosticInner = Type("System.Exception").Methods.Single(method => method.Name == "get_InnerException" && method.Parameters.Count == 0);
        var diagnosticEqual = Type("System.String").Methods.Single(method => method.Name == "op_Equality" && method.Parameters.Count == 2);
        const string diagnosticConsoleIdentity="System.Console, Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a";
        Require(typeof(Console).Assembly.FullName == diagnosticConsoleIdentity);
        var diagnosticConsoleScope=module.AssemblyReferences.SingleOrDefault(reference => reference.FullName==diagnosticConsoleIdentity);
        if (diagnosticConsoleScope is null) { diagnosticConsoleScope=AssemblyNameReference.Parse(diagnosticConsoleIdentity);module.AssemblyReferences.Add(diagnosticConsoleScope); }
        var diagnosticConsoleType=new TypeReference("System","Console",module,diagnosticConsoleScope);
        var diagnosticConsole=new MethodReference("get_Error",Type("System.IO.TextWriter"),diagnosticConsoleType) { HasThis=false };
        var diagnosticWrite = Type("System.IO.TextWriter").Methods.Single(method => method.Name == "WriteLine" && method.Parameters.Count == 1
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.String);
        string[] diagnosticCodes = [
            "activation-timer-driver-completion",
            "activation-timer-driver-epoch-limit",
            "activation-timer-driver-task-identity",
            "managed-timer-accepted-owner",
            "managed-timer-callback-limit",
            "managed-timer-change-owner",
            "managed-timer-change-state",
            "managed-timer-dispatch-owner",
            "managed-timer-dispatch-state",
            "managed-timer-missing-record",
            "managed-timer-mutation-limit",
            "managed-timer-record-limit",
            "managed-timer-return-owner",
            "managed-timer-return-state",
            "managed-work-admission-refused",
            "managed-work-captured-parent-retired",
            "managed-work-closing-state",
            "managed-work-context-owner",
            "managed-work-double-settle",
            "managed-work-duplicate-enqueue",
            "managed-work-execution-parent",
            "managed-work-finalization-continuations",
            "managed-work-finalization-owners",
            "managed-work-finalization-queue",
            "managed-work-finalization-state",
            "managed-work-finalization-timers",
            "managed-work-independent-admission-closed",
            "managed-work-installation",
            "managed-work-missing-record",
            "managed-work-parent-retired",
            "managed-work-queue-record-limit",
            "managed-work-record-limit",
            "managed-work-required-continuation-limit",
            "managed-work-transport-parent",
            "managed-work-unproven-quiescence",
            "managed-work-unregistered-dequeue",
            "managed-work-untracked-startup-work",
        ];
        var diagnosticShortBranches = handler.Body.Instructions.Where(instruction => instruction.OpCode.OperandType == OperandType.ShortInlineBrTarget).ToArray();
        Require(diagnosticShortBranches.Length == 2 && diagnosticShortBranches.All(instruction => instruction.OpCode == OpCodes.Leave_S));
        foreach (var branch in diagnosticShortBranches) branch.OpCode=OpCodes.Leave;
        var diagnosticIl = handler.Body.GetILProcessor();
        void Diagnostic(Instruction instruction) => diagnosticIl.InsertBefore(diagnosticAnchor, instruction);
        var diagnosticStart = diagnosticIl.Create(OpCodes.Ldloc, diagnosticOriginal);
        var diagnosticClassify = diagnosticIl.Create(OpCodes.Nop);
        var diagnosticCatch = diagnosticIl.Create(OpCodes.Pop);
        Diagnostic(diagnosticStart); Diagnostic(diagnosticIl.Create(OpCodes.Stloc, diagnosticException));
        Diagnostic(diagnosticIl.Create(OpCodes.Ldloc, diagnosticException));
        Diagnostic(diagnosticIl.Create(OpCodes.Isinst, Type("System.Threading.Tasks.TaskSchedulerException")));
        Diagnostic(diagnosticIl.Create(OpCodes.Brfalse, diagnosticClassify));
        Diagnostic(diagnosticIl.Create(OpCodes.Ldloc, diagnosticException)); Diagnostic(diagnosticIl.Create(OpCodes.Callvirt, diagnosticInner));
        Diagnostic(diagnosticIl.Create(OpCodes.Brfalse, diagnosticClassify));
        Diagnostic(diagnosticIl.Create(OpCodes.Ldloc, diagnosticException)); Diagnostic(diagnosticIl.Create(OpCodes.Callvirt, diagnosticInner));
        Diagnostic(diagnosticIl.Create(OpCodes.Stloc, diagnosticException)); Diagnostic(diagnosticClassify);
        var diagnosticMarkers = Enumerable.Range(0, diagnosticCodes.Length+1).Select(code => diagnosticIl.Create(OpCodes.Call, diagnosticConsole)).ToArray();
        for (int code=0;code<diagnosticCodes.Length;code++) {
            Diagnostic(diagnosticIl.Create(OpCodes.Ldloc, diagnosticException)); Diagnostic(diagnosticIl.Create(OpCodes.Callvirt, diagnosticMessage));
            Diagnostic(diagnosticIl.Create(OpCodes.Ldstr, diagnosticCodes[code])); Diagnostic(diagnosticIl.Create(OpCodes.Call, diagnosticEqual));
            Diagnostic(diagnosticIl.Create(OpCodes.Brtrue, diagnosticMarkers[code+1]));
        }
        Diagnostic(diagnosticIl.Create(OpCodes.Br, diagnosticMarkers[0]));
        for (int code=0;code<diagnosticMarkers.Length;code++) {
            Diagnostic(diagnosticMarkers[code]); Diagnostic(diagnosticIl.Create(OpCodes.Ldstr, $"LSF-PERIODIC-CODE:{code:D4}"));
            Diagnostic(diagnosticIl.Create(OpCodes.Callvirt, diagnosticWrite)); Diagnostic(diagnosticIl.Create(OpCodes.Leave, diagnosticAnchor));
        }
        Diagnostic(diagnosticCatch); Diagnostic(diagnosticIl.Create(OpCodes.Leave, diagnosticAnchor));
        handler.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Catch) {
            TryStart=diagnosticStart,TryEnd=diagnosticCatch,HandlerStart=diagnosticCatch,HandlerEnd=diagnosticAnchor,
            CatchType=Type("System.Exception") });
        handler.Body.MaxStackSize=Math.Max(handler.Body.MaxStackSize,3);
