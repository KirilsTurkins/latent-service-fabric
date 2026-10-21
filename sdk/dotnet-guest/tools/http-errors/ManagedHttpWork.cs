using Mono.Cecil;
using Mono.Cecil.Cil;

internal static class ManagedHttpWork
{
    internal static object AbortCleanup(ModuleDefinition module)
    {
        var output = module.GetTypes().Single(type => type.FullName == "System.Net.Http.WasiOutputStream");
        var wrapper = module.GetTypes().Single(type => type.FullName == "System.Net.Http.WasiRequestWrapper");
        var cleanup = wrapper.Methods.Single(method => method.Name == "Dispose");
        var close = output.Methods.Single(method => method.Name == "Close");
        var dispose = output.Methods.Single(method => method.Name == "Dispose");
        const string original = "63c5a116d410596de909966cc8c43e574d39491496edeeaa8db44ed31e65be8f";
        const string originalClose = "f7bdf561babff64617ae550ac89eeeba27dd08d9cd5d09f15e2475951f49cd5a";
        const string originalDispose = "242ab25d6c4af1de65c1b1c83742a554a892e2873282048e51cbfb6e1694ff33";
        if (TaskWait.BodyIdentity(cleanup) != original || TaskWait.BodyIdentity(close) != originalClose
            || TaskWait.BodyIdentity(dispose) != originalDispose || !dispose.IsFamily
            || dispose.IsStatic || dispose.Parameters.Count != 1
            || dispose.Parameters[0].ParameterType.MetadataType != MetadataType.Boolean
            || output.Methods.Any(method => method.Name == "LsfAbortFailedRequestOutput"))
            throw new InvalidDataException("managed-http-abort-cleanup-preimage");
        var calls = cleanup.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Call
            && instruction.Operand is MethodReference method
            && method.FullName == "System.Void System.IO.Stream::Dispose()").ToArray();
        if (calls.Length != 2 || calls[0].Offset != 0x1b || calls[1].Offset != 0x2c
            || !cleanup.Body.Instructions.Any(instruction => instruction.Offset == 0x10
                && instruction.Operand is FieldReference field && field.Name == "wasiOutputStream"
                && field.FieldType.FullName == output.FullName))
            throw new InvalidDataException("managed-http-abort-cleanup-callsite");
        var suppress = wrapper.Methods.Single(method => method.Name == "Finalize").Body.Instructions
            .Select(instruction => instruction.Operand).OfType<MethodReference>()
            .Single(method => method.FullName == "System.Void System.GC::SuppressFinalize(System.Object)");
        // Wrapper disposal is abandonment/error cleanup, including its finalizer.
        // The original successful SendContent.Close path still performs Finish.
        // Calling Stream.Dispose here would instead dispatch virtual Close and
        // let a failed Finish mask the primary request exception.
        var helper = new MethodDefinition("LsfAbortFailedRequestOutput",
            MethodAttributes.Assembly | MethodAttributes.HideBySig, module.TypeSystem.Void);
        output.Methods.Add(helper); helper.Body.MaxStackSize = 2;
        var il = helper.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Call, dispose);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, suppress); il.Emit(OpCodes.Ret);
        calls[0].Operand = helper;
        return new {
            profile = "dotnet-request-abort-cleanup-v1", method = cleanup.FullName,
            originalBodyDigest = "sha256:" + original,
            successfulCloseBodyDigest = "sha256:" + originalClose,
            protectedDisposeBodyDigest = "sha256:" + originalDispose,
            cleanup = "original-protected-Dispose(true)-then-GC-suppression",
            body = "abort-not-successful-finish", originalFailure = "original-handler-rethrow",
            inputAndFutureCleanup = "unchanged", modifiedOriginalMethods = 1,
            generatedHelpers = 1, newHostImports = 0, qualified = false,
        };
    }

    internal static object Apply(ModuleDefinition module)
    {
        var method = module.GetTypes().Single(type => type.FullName == "System.Net.Http.WasiRequestWrapper/<SendRequestAsync>d__4")
            .Methods.Single(candidate => candidate.Name == "MoveNext");
        var send = method.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Call
            && instruction.Operand is MethodReference reference && reference.FullName ==
                "System.Threading.Tasks.Task System.Net.Http.WasiRequestWrapper::SendContent(System.Net.Http.HttpContent,WasiHttpWorld.wit.imports.wasi.http.v0_2_0.ITypes/OutgoingRequest,System.Threading.CancellationToken)");
        if (send.Next.OpCode != OpCodes.Pop || method.IsStatic || method.Parameters.Count != 0)
            throw new InvalidDataException("managed-http-work-original-producer");
        var original = TaskWait.BodyIdentity(method);
        var corelib = module.AssemblyReferences.Single(reference => reference.FullName ==
            "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e");
        var registry = new TypeReference("Lsf.CompilerOwned", "ManagedWorkRuntime", module, corelib);
        var retain = new MethodReference("RequiredTransport", module.TypeSystem.Void, registry);
        retain.Parameters.Add(new ParameterDefinition(((MethodReference)send.Operand).ReturnType));
        send.Next.OpCode = OpCodes.Call; send.Next.Operand = retain;
        ManagedWorkHooks.Widen(method);
        return new {
            profile = "dotnet-required-http-content-work-v1", method = method.FullName,
            originalBodyDigest = "sha256:" + original, modifiedOriginalMethods = 1,
            task = "actual-original-SendContent-return", error = "unchanged-request-future",
            transport = "unchanged-original-WASI-handler", completion = "actual-content-task-before-physical-drain",
            qualified = false,
        };
    }
}
