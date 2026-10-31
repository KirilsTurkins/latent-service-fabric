using Mono.Cecil;

internal static class ManagedWorkPort
{
    internal static (MethodDefinition[] Changed, object Receipt) Install(ModuleDefinition module,
        IReadOnlyDictionary<string, string> originalBodies)
    {
        var references = module.AssemblyReferences.Select(reference => reference.FullName).ToArray();
        var typeMetadata = module.GetTypes().ToDictionary(type => type.FullName, type => new {
            type.Attributes, Interfaces = type.Interfaces.Select(item => item.InterfaceType.FullName).ToArray(),
        });
        using var tool = ModuleDefinition.ReadModule(typeof(Lsf.CompilerOwned.ManagedWorkRuntime).Assembly.Location);
        var registry = new ManagedWorkCopy(module).Copy(tool);
        ManagedWorkContext.Install(module, registry);
        var hooks = new ManagedWorkHooks(module, registry).Install(originalBodies);
        if (!references.SequenceEqual(module.AssemblyReferences.Select(reference => reference.FullName)))
            throw new InvalidDataException("managed-work-new-assembly-reference");
        string[] contextTypes = ["System.Threading.Tasks.Task", "System.Threading.QueueUserWorkItemCallback",
            "System.Threading.QueueUserWorkItemCallback`1", "System.Threading.QueueUserWorkItemCallbackDefaultContext",
            "System.Threading.QueueUserWorkItemCallbackDefaultContext`1"];
        foreach (var type in module.GetTypes().Where(type => typeMetadata.ContainsKey(type.FullName)))
        {
            var before = typeMetadata[type.FullName];
            var interfaces = contextTypes.Contains(type.FullName)
                ? before.Interfaces.Append("Lsf.CompilerOwned.ManagedWorkRuntime/ContextSource") : before.Interfaces;
            if (type.Attributes != before.Attributes || !interfaces.SequenceEqual(type.Interfaces.Select(item => item.InterfaceType.FullName)))
                throw new InvalidDataException("managed-work-original-type-metadata");
        }
        var changed = hooks.Changed.ToDictionary(method => method.FullName,
            method => originalBodies[method.DeclaringType.FullName + "#" + method.DeclaringType.Methods.IndexOf(method)]);
        if (changed.Count != 23 || registry.Count != 58)
            throw new InvalidDataException("managed-work-selected-method-count");
        return (hooks.Changed, new {
            patch = "latent.dotnet.managed-accepted-work.v3",
            readiness = "original-prefetched-slot-or-counted-queues-and-polls",
            readinessControls = "four-actual-generated-slot-models",
            modifiedOriginalMethods = changed,
            copiedRegistryMethods = registry.Count,
            taskIdentity = "actual-task-unwrap-promise-and-inner",
            requiredContinuationIdentity = "actual-state-machine-box-before-await-registration",
            queueAdmission = "before-original-enqueue-with-fault-rollback",
            completion = "after-original-finish-continuations",
            context = "private-key-original-immutable-map-original-notifications",
            contextSourceTypes = contextTypes,
            closing = "original-native-close-and-live-parent-only",
            join = "original-task-wait-dispatch-with-readiness-each-iteration",
            unobservedFaults = "original-task-exception-retained-result-owner",
            privateRootBridge = "exact-Task-UnsafeAccessor-static-forwarders",
            structuralRecordLimit = 32, structuralQueueLimit = 64, structuralTimerLimit = 32,
            timerAdmission = "original-TimerQueueTimer-before-active-list-mutation",
            timerRetirement = "original-disarmed-no-accepted-queued-running-or-required-callback",
            timerCallbackContext = "original-ExecutionContext-values-with-private-live-timer-owner",
            authoritativeLimits = "original-activation-owner-ledger",
            newAssemblyReferences = 0,
            qualified = false,
        });
    }
}
