using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

// Execute the actual rewritten handler. Only clock, queue and FailFast are
// explicit ports; the projection, nested handler and Console calls are copied.
internal static class Program
{
    private static void Need(bool value) { if(!value) throw new InvalidDataException("periodic-handler-control"); }
    private static int Main(string[] args)
    {
        if(args is ["graft",var source,var output]) {
            using var from=ModuleDefinition.ReadModule(source);
            using var target=ModuleDefinition.ReadModule(typeof(Program).Assembly.Location);
            var original=from.Types.Single(t=>t.FullName=="System.Threading.TimerQueue").Methods.Single(m=>m.Name=="TimerHandler");
            var queue=target.Types.Single(t=>t.FullName=="Queue");var copied=queue.Methods.Single(m=>m.Name=="TimerHandler");
            copied.Body=new MethodBody(copied){InitLocals=original.Body.InitLocals,MaxStackSize=original.Body.MaxStackSize};
            var variables=original.Body.Variables.ToDictionary(v=>v,v=>new VariableDefinition(target.ImportReference(v.VariableType)));
            foreach(var value in variables.Values)copied.Body.Variables.Add(value);
            MethodReference Method(MethodReference m) => m.DeclaringType.FullName=="System.Threading.TimerQueue" || m.DeclaringType.FullName=="System.Environment" && m.Name=="FailFast"
                ? queue.Methods.Single(x=>x.Name==m.Name && x.Parameters.Count==m.Parameters.Count) : target.ImportReference(m);
            var rows=original.Body.Instructions.ToDictionary(i=>i,_=>Instruction.Create(OpCodes.Nop));
            foreach(var i in original.Body.Instructions) {
                var row=rows[i];row.OpCode=i.OpCode;
                row.Operand=i.Operand switch {
                    Instruction branch=>rows[branch],Instruction[] branches=>branches.Select(b=>rows[b]).ToArray(),
                    VariableDefinition v=>variables[v],ParameterDefinition p=>copied.Parameters[p.Index],
                    MethodReference m=>Method(m),FieldReference f=>queue.Fields.Single(x=>x.Name==f.Name),
                    TypeReference t=>target.ImportReference(t),null or string or int or long=>i.Operand,
                    _=>throw new InvalidDataException("periodic-handler-closed-copy")
                };copied.Body.Instructions.Add(row);
            }
            foreach(var h in original.Body.ExceptionHandlers)copied.Body.ExceptionHandlers.Add(new ExceptionHandler(h.HandlerType){
                TryStart=rows[h.TryStart],TryEnd=h.TryEnd is null?null:rows[h.TryEnd],HandlerStart=rows[h.HandlerStart],
                HandlerEnd=h.HandlerEnd is null?null:rows[h.HandlerEnd],CatchType=h.CatchType is null?null:target.ImportReference(h.CatchType)});
            var consoleCalls=original.Body.Instructions.Where(i=>i.Operand is MethodReference m && m.DeclaringType.FullName=="System.Console")
                .Select(i=>(MethodReference)i.Operand).ToArray();
            Need(consoleCalls.Length==38 && consoleCalls.All(m=>m.Name=="get_Error" && m.ReturnType.FullName=="System.IO.TextWriter"
                && m.ReturnType.Scope==from && m.DeclaringType.Scope.ToString()=="System.Console, Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a"));
            Need(copied.Body.ExceptionHandlers.Count==2);
            Need(copied.Body.Instructions.Count(i=>i.Operand is MethodReference m && m.Name=="FailFast")==1);
            Directory.CreateDirectory(output);target.Write(Path.Combine(output,"Control.dll"));
            foreach(var name in new[]{"Control.runtimeconfig.json","Control.deps.json","Mono.Cecil.dll"})
                File.Copy(Path.Combine(Path.GetDirectoryName(typeof(Program).Assembly.Location)!,name),Path.Combine(output,name));
            Console.WriteLine(JsonSerializer.Serialize(new{sourceDigest=Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(source))),
                copiedActualHandlers=1,originalFailFastCalls=1,nestedDiagnosticCatch=1,guestQualified=false}));return 0;
        }
        Need(args.Length==3 && args[0]=="execute");var code=int.Parse(args[1]);var text=args[2];
        var originalError=Console.Error;using var sink=new StringWriter();
        Queue.Error=text=="success"?null:text.StartsWith("wrapped:",StringComparison.Ordinal)?new System.Threading.Tasks.TaskSchedulerException(new InvalidOperationException(text[8..])):
            new InvalidOperationException(text);
        try { Console.SetError(text=="writer-fails"?new RefusedWriter():sink);Queue.TimerHandler(null!); }
        finally { Console.SetError(originalError); }
        Need(Queue.FailFastCalls==(text=="success"?0:1));
        Need(Queue.OriginalErrorPreserved && (text=="success"?Queue.RearmCalls==1:Queue.RearmCalls==0));
        string expected=text is "writer-fails" or "success"?"":$"LSF-PERIODIC-CODE:{code:D4}"+Environment.NewLine;
        Need(sink.ToString()==expected);
        Console.WriteLine(JsonSerializer.Serialize(new{code,passed=true,copiedActualHandlers=1,
            originalExceptionPreserved=true,projectionFailureCannotMaskOriginal=true,guestQualified=false}));return 0;
    }
    private sealed class RefusedWriter:TextWriter { public override System.Text.Encoding Encoding=>System.Text.Encoding.UTF8;
        public override void WriteLine(string? value)=>throw new IOException("public-control-refusal"); }
}
internal static class Queue
{
    internal static long s_shortestDueTimeMs,s_lsfTimerDriverEpoch;
    internal static Exception? Error;
    internal static int FailFastCalls,RearmCalls;
    internal static bool OriginalErrorPreserved=true;
    internal static long get_TickCount64()=>100;
    internal static long PumpTimerQueue(long now) { if(Error is not null)throw Error;return now+1; }
    internal static void LsfTimerDriverRearm(long next,long now,long epoch) { if(next!=101 || now!=100 || epoch!=s_lsfTimerDriverEpoch)throw new Exception("control-rearm");RearmCalls++; }
    internal static void FailFast(string message,Exception error) { OriginalErrorPreserved&=message=="TimerQueue.TimerHandler failed" && ReferenceEquals(error,Error);FailFastCalls++; }
    internal static void TimerHandler(object value)=>throw new Exception("ungrafted-control");
}
