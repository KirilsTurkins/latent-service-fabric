using Mono.Cecil;
using Mono.Cecil.Cil;

internal static class ManagedHttpWork
{
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
