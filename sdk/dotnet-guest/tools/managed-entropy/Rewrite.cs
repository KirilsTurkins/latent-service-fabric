using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;
internal static class Rewrite {
 const string Original = "7264a768f8e344533902eb61582fef1f737699bd5f11305b7f752193c809b8b4";
 const string Cecil = "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7";
 static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
 static void Need(bool condition) { if(!condition) throw new InvalidDataException("managed-entropy-preimage-or-shape"); }
 static string Shape(MethodDefinition m) => JsonSerializer.Serialize(new { m.FullName, m.Attributes, m.ImplAttributes,
  instructions = m.HasBody ? m.Body.Instructions.Select(i => i.OpCode.Code + ":" + i.Operand).ToArray() : [],
  locals = m.HasBody ? m.Body.Variables.Select(v=>v.VariableType.FullName).ToArray() : [],
  handlers = m.HasBody ? m.Body.ExceptionHandlers.Select(h=>new { h.HandlerType, h.TryStart.Offset, end=h.TryEnd?.Offset,
      start=h.HandlerStart.Offset, stop=h.HandlerEnd?.Offset, filter=h.FilterStart?.Offset, type=h.CatchType?.FullName }).ToArray() : [] });
 static string Signature(MethodReference m, bool skipReceiver=false) => m.Name+"`"+m.GenericParameters.Count+"("+
  string.Join(",",m.Parameters.Skip(skipReceiver?1:0).Select(p=>p.ParameterType.FullName))+")";
 public static int Main(string[] args) {
  try {
   Need(args.Length==4 && args.All(a=>a.Length is >0 and <=4096));
   var input=Path.GetFullPath(args[0]); var helperPath=Path.GetFullPath(args[1]);var output=Path.GetFullPath(args[2]);var receipt=Path.GetFullPath(args[3]);
   Need(new[]{input,helperPath,output,receipt}.Distinct().Count()==4 && !File.Exists(output) && !Directory.Exists(output) && !File.Exists(receipt));
   Need(new FileInfo(input).Length==284672 && Hash(input)==Original && Hash(typeof(ModuleDefinition).Assembly.Location)==Cecil);
   Need(new FileInfo(helperPath).Length is >0 and <=262144);
   using var module=ModuleDefinition.ReadModule(input);using var helper=ModuleDefinition.ReadModule(helperPath);
   Need(module.Assembly.Name.FullName=="System.Security.Cryptography, Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a");
   Need(helper.Assembly.Name.Name=="Lsf.StandardEntropy" && helper.Assembly.Name.Version==new Version(1,0,0,0));
   var rng=module.Types.Single(t=>t.FullName=="System.Security.Cryptography.RandomNumberGenerator");
   var implementation=helper.Types.Single(t=>t.FullName=="Lsf.StandardEntropy.RandomNumberGenerator");
   var bridges=helper.Types.Single(t=>t.FullName=="Lsf.StandardEntropy.BaseMethods");
   var all=module.GetTypes().SelectMany(t=>t.Methods).ToArray();var before=all.ToDictionary(m=>m,Shape);
   var replaced=new List<string>();
   foreach(var method in rng.Methods) {
    if(method.IsAbstract || (method.Name=="Create" && method.Parameters.Count==1) ||
       (method.Name=="Dispose" && method.Parameters.Count==1)) continue;
    if(method.IsConstructor) {
     Need(method.Body.Instructions.Count==5 && method.Body.Instructions[1].Operand is MethodReference c && c.FullName=="System.Void System.Object::.ctor()");
     var ctor=method.Body.Instructions[1].Operand as MethodReference;
     method.Body=new MethodBody(method);var il=method.Body.GetILProcessor();il.Emit(OpCodes.Ldarg_0);il.Emit(OpCodes.Call,ctor!);il.Emit(OpCodes.Ret);
    } else if(method.Name=="Dispose") {
     Need(method.Body.Instructions.Count==1 && method.Body.Instructions[0].OpCode==OpCodes.Ret);
     var dispose=rng.Methods.Single(m=>m.Name=="Dispose"&&m.Parameters.Count==1);
     var gc=new TypeReference("System","GC",module,module.TypeSystem.Object.Scope);
     var suppress=new MethodReference("SuppressFinalize",module.TypeSystem.Void,gc);suppress.Parameters.Add(new ParameterDefinition(module.TypeSystem.Object));
     method.Body=new MethodBody(method);var il=method.Body.GetILProcessor();il.Emit(OpCodes.Ldarg_0);il.Emit(OpCodes.Ldc_I4_1);il.Emit(OpCodes.Callvirt,dispose);il.Emit(OpCodes.Ldarg_0);il.Emit(OpCodes.Call,suppress);il.Emit(OpCodes.Ret);
    } else {
     Need(method.HasBody && method.Body.Instructions.Count==3 && method.Body.Instructions[2].OpCode==OpCodes.Throw &&
       method.Body.Instructions[1].Operand is MethodReference e && e.DeclaringType.FullName=="System.PlatformNotSupportedException");
     var target=(method.IsStatic?implementation:bridges).Methods.Single(m=>m.IsStatic && Signature(m,!method.IsStatic)==Signature(method));
     var reference=module.ImportReference(target,method);
     MethodReference call=reference;
     if(method.HasGenericParameters) { var g=new GenericInstanceMethod(reference);foreach(var param in method.GenericParameters)g.GenericArguments.Add(param);call=g; }
     method.Body=new MethodBody(method);var il=method.Body.GetILProcessor();
     if(!method.IsStatic)il.Emit(OpCodes.Ldarg_0);
     foreach(var param in method.Parameters)il.Emit(OpCodes.Ldarg,param);
     il.Emit(OpCodes.Call,call);il.Emit(OpCodes.Ret);
    }
    replaced.Add(method.FullName);
   }
   Need(replaced.Count==17);
   Need(all.Where(m=>!replaced.Contains(m.FullName)).All(m=>Shape(m)==before[m]));
   module.Write(output);Need(Hash(input)==Original);
   using var selected=ModuleDefinition.ReadModule(output);
   var selectedMethods=selected.GetTypes().SelectMany(t=>t.Methods).ToArray();Need(selectedMethods.Length==all.Length);
   Need(selectedMethods.Where(m=>!replaced.Contains(m.FullName)).All(m=>Shape(m)==before[all.Single(a=>a.FullName==m.FullName)]));
   File.WriteAllText(receipt,JsonSerializer.Serialize(new { patch="latent.dotnet.standard-rng-managed.v1",sourceDigest="sha256:"+Original,
    helperDigest="sha256:"+Hash(helperPath),outputDigest="sha256:"+Hash(output),cecilDigest="sha256:"+Cecil,
    replaced, unchangedMethods=all.Length-replaced.Count, namedAlgorithmFactorySupported=false, applicationAssemblyEdits=0,
    sharedPackageModified=false }));
   return 0;
  } catch(Exception e) { Console.Error.WriteLine(e is InvalidDataException ? e.Message : "managed-entropy-rewrite-failed");return 1; }
 }
}
