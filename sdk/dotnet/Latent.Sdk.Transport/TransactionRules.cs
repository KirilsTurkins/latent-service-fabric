using System.Collections;
using System.Globalization;
using System.Reflection;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

namespace Latent.Sdk.Transport;

internal sealed class TransactionWireValueException(string field, string value) : FormatException("unsupported transaction wire value")
{
    internal Profile.UnsupportedWireValue Value { get; } = new(field, value);
}

internal static class TransactionRules
{
    private static readonly HashSet<string> PlatformCodes = new(StringComparer.Ordinal)
    {
        "unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied", "unauthenticated",
        "invalid-argument", "not-found", "already-exists", "incompatible-contract", "state-conflict", "dependency-failed",
        "guest-trap", "corrupt-artifact", "route-unavailable", "admission-rejected", "internal"
    };

    internal static void Require(bool valid) { if (!valid) throw new FormatException("invalid bounded transaction value"); }
    private static T Present<T>(T? value) where T : class => value ?? throw new FormatException("missing transaction value");
    private static void Text(string? value, int maximum = 256, bool required = true, bool controls = true)
    {
        Require(value is not null && (!required || value.Length != 0) && GraphBudget.Utf8.GetByteCount(value) <= maximum &&
            (!controls || !value.Any(char.IsControl)));
    }
    private static void Identity(string value) { Text(value, controls: false); Require(!value.Contains('\0')); }
    private static void Bytes(ReadOnlyMemory<byte> value, int maximum = 256, bool required = true) => Require(value.Length <= maximum && (!required || !value.IsEmpty));
    private static void Enum(int value, int maximum)
    {
        if (value < 1 || value > maximum) throw new TransactionWireValueException("transaction.enum", value.ToString(CultureInfo.InvariantCulture));
    }
    private static void Digest(string value) => Require(value.Length == 71 && value.StartsWith("sha256:", StringComparison.Ordinal) && value[7..].All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f'));
    private static ulong Incarnation(string value)
    {
        Require(ulong.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out ulong parsed) && parsed != 0 && parsed.ToString(CultureInfo.InvariantCulture) == value);
        return parsed;
    }
    private static Tx.NamespaceSelector Namespace(Tx.NamespaceSelector? raw, string? tenant = null)
    {
        var value = Present(raw); Text(value.Tenant); Text(value.Namespace); Incarnation(value.Incarnation);
        Require(tenant is null || tenant == value.Tenant); return value;
    }
    private static void Publication(Profile.PublicationRef? raw, string tenant)
    {
        var value = Present(raw); Require(value.Tenant == tenant && value.Id.StartsWith("publication:", StringComparison.Ordinal)); Digest(value.Id[12..]);
    }
    private static Tx.CommandSelector Selector(Tx.CommandSelector? raw, string? tenant = null)
    {
        var value = Present(raw); Namespace(value.Namespace, tenant); Identity(value.Operation); Identity(value.ClientKey);
        if (value.Entity is not null) Identity(value.Entity);
        if (value.SharedRecoveryScope is not null) Identity(value.SharedRecoveryScope);
        return value;
    }
    private static void Selected(Tx.TransactionProfile? value) => Require(value == Tx.CurrentTransactionProfile.Create());
    private static Tx.NamespaceSelector Inspect(Tx.InspectNamespaceRequest? raw)
    {
        var value = Present(raw); Selected(value.Profile); var ns = Namespace(value.Namespace); Publication(value.AuthorizationPublication, ns.Tenant); return ns;
    }
    private static void Lookup(Tx.TransactionProfile? profile, Tx.CommandSelector? command, Profile.PublicationRef? publication)
    {
        Selected(profile); var selected = Selector(command); Publication(publication, selected.Namespace!.Tenant);
    }
    private static void Lookup(Tx.LookupCommandRequest? raw)
    {
        var value = Present(raw); Lookup(value.Profile, value.Command, value.AuthorizationPublication); if (value.AttemptId is not null) Text(value.AttemptId);
    }
    private static void Fence(Tx.AbortFence? raw)
    {
        var value = Present(raw); Text(value.CommandId); Text(value.AttemptId); Text(value.TransactionId); Bytes(value.OwnerFence);
    }
    private static Tx.PageRequest Page(Tx.PageRequest? raw)
    {
        var value = Present(raw); Require(value.Limit is >= 1 and <= 128); if (value.Cursor is { } cursor) Bytes(cursor); return value;
    }
    private static void Metadata(IReadOnlyDictionary<string, string> value, bool caller = false)
    {
        Require(value is not null && value.Count <= 32); long bytes = 0;
        foreach (var (key, item) in value!)
        {
            Text(key); Text(item, 1024, false);
            Require(!caller || !key.StartsWith("latent.auth.", StringComparison.OrdinalIgnoreCase) && !key.StartsWith("latent.principal.", StringComparison.OrdinalIgnoreCase));
            bytes += GraphBudget.Utf8.GetByteCount(key) + GraphBudget.Utf8.GetByteCount(item);
        }
        Require(bytes <= 8192);
    }
    private static void Media(string value) { Text(value, 128); Require(value.All(c => c is >= ' ' and <= '~')); }
    private static void Invocation(Profile.InvokeRequest? raw, string tenant)
    {
        var value = Present(raw); var target = Present(value.Target); Present(value.Budget);
        foreach (var id in new[] { value.ActivationId, value.ParentActivationId, value.RootActivationId, value.IdempotencyKey, target.Route }) if (id is not null) Text(id);
        Require(value.ParentActivationId is null || value.RootActivationId is not null);
        Require(target.Tenant == tenant); foreach (var id in new[] { target.Tenant, target.Service, target.Contract, target.Function }) Text(id);
        Bytes(value.Payload, 1024 * 1024, false); Media(value.MediaType); Metadata(value.Metadata, true); Require(value.Priority is >= 0 and <= 255);
    }
    private static void Quota(Tx.NamespaceQuota? raw)
    {
        var value = Present(raw);
        foreach (var count in new[] { value.StateKeys, value.ResultRows, value.EffectRows }) Require(count is >= 1 and <= 1000000);
        foreach (var bytes in new[] { value.StateBytes, value.ResultBytes, value.EffectBytes, value.PayloadBytes, value.RecoveryBytes }) Require(bytes is >= 1 and <= 1073741824);
        Require(value.RecoveryBytes <= value.ResultBytes);
    }

    // Runs before native conversion. Counts are checked before another graph is allocated.
    internal static void Collections(object? value, GraphBudget budget, int depth = 0, string field = "")
    {
        if (depth > 16) throw new GraphLimitException();
        budget.Spend();
        switch (value)
        {
            case null: return;
            case string text: budget.Spend(4L * GraphBudget.Utf8.GetByteCount(text)); return;
            case ReadOnlyMemory<byte> bytes: budget.Spend(3L * bytes.Length); return;
            case IReadOnlyDictionary<string, string> map:
                if (map.Count > 32) throw new GraphLimitException();
                foreach (var (key, item) in map) { Collections(key, budget, depth + 1); Collections(item, budget, depth + 1); }
                return;
            case IEnumerable sequence:
                int count = 0, maximum = field == "RequiredRecordIds" ? 256 : 128;
                foreach (var item in sequence) { if (++count > maximum) throw new GraphLimitException(); Collections(item, budget, depth + 1); }
                return;
        }
        Type type = value.GetType();
        if (type.IsPrimitive || type.IsEnum || type.IsValueType && type.GetProperty("Value") is not null) return;
        foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            Collections(property.GetValue(value), budget, depth + 1, property.Name);
    }

    internal static void Request(object request)
    {
        switch (request)
        {
            case Tx.InvokeCommandRequest value:
                Selected(value.Profile); var selected = Selector(value.Command); Invocation(value.Invocation, selected.Namespace!.Tenant); Identity(value.InputFormat);
                var keys = new HashSet<string>(StringComparer.Ordinal); Require(value.ExpectedVersions.Count <= 128);
                foreach (var entry in value.ExpectedVersions)
                {
                    Bytes(entry.Key, 1024, false); Require(keys.Add(Convert.ToHexString(entry.Key.Span)) && (entry.Absent.HasValue != entry.Version.HasValue));
                    if (entry.Absent.HasValue) Require(entry.Absent == true);
                    if (entry.Version is { } version) Bytes(version);
                }
                if (value.RetryAttempt is { } attempt) { Text(attempt.RequestId); Fence(attempt.ExpectedAbort); }
                break;
            case Tx.QueryRequest value:
                Selected(value.Profile); var ns = Namespace(value.Namespace); Invocation(value.Invocation, ns.Tenant);
                if (value.Entity is not null) Identity(value.Entity); if (value.MinimumViewVersion is { } minimum) Bytes(minimum);
                break;
            case Tx.LookupCommandRequest value: Lookup(value); break;
            case Tx.LookupCommitRequest value: Lookup(value.Profile, value.Command, value.AuthorizationPublication); Text(value.ReceiptId); break;
            case Tx.GetEffectRequest value: Lookup(value.Profile, value.Command, value.AuthorizationPublication); Text(value.EffectId); break;
            case Tx.ListEffectHistoryRequest value: var effect = Present(value.Effect); Request(effect); Page(value.Page); break;
            case Tx.CancelCommandRequest value: Lookup(value.Command); Text(value.Reason, 1024); break;
            case Tx.InspectNamespaceRequest value: Inspect(value); break;
            case Tx.SelectEntityRequest value: Inspect(value.Namespace); Page(value.Page); if (value.Prefix is { } prefix) Bytes(prefix, 256, false); break;
            case Tx.GetStateOperationReceiptRequest value: Inspect(value.Namespace); Text(value.OperationId); break;
            case Tx.MutateStateRequest value:
                Inspect(value.Namespace); Text(value.OperationId); Bytes(value.ExpectedVersion); Digest(value.ExpectedPolicyDigest); Text(value.Reason, 1024); Enum(value.Mutation.Value, 4);
                Require((value.Mutation.Value == 4) == (value.RecordId is null)); if (value.RecordId is not null) Text(value.RecordId);
                break;
            case Tx.MutateNamespaceRequest value:
                var target = Inspect(value.Namespace); Text(value.OperationId); Enum(value.Mutation.Value, 5); Require(value.ExpectedGeneration.HasValue);
                Require((value.Mutation.Value == 1) == (value.ExpectedGeneration == 0) && (value.Mutation.Value != 1 || target.Incarnation == "1"));
                if (value.Mutation.Value is 1 or 5) { var config = Present(value.Configuration); Text(config.StateSchema); Quota(config.Quota); }
                else Require(value.Configuration is null);
                break;
            case Tx.InspectDispatcherRequest value: Selected(value.Profile); Enum(value.Scope.Value, 1); break;
            case Tx.ControlDispatcherRequest value: DispatcherControl(value); break;
            case Tx.GetDispatcherOperationRequest value: DispatcherControl(Present(value.Original)); break;
            default: throw new FormatException("unsupported transaction operation");
        }
    }

    private static Tx.DispatcherGeneration DispatcherGeneration(Tx.DispatcherGeneration? raw)
    {
        var generation = Present(raw); Require(generation.OwnerEpoch != 0 && generation.Revision != 0); return generation;
    }

    private static void DispatcherControl(Tx.ControlDispatcherRequest value)
    {
        Selected(value.Profile); Enum(value.Scope.Value, 1); Text(value.OperationId); Enum(value.Action.Value, 2);
        Require(DispatcherGeneration(value.ExpectedGeneration).Revision != ulong.MaxValue);
    }

    private static void DispatcherReceipt(Tx.DispatcherOperationReceipt? raw, Tx.ControlDispatcherRequest original)
    {
        var receipt = Present(raw); Text(receipt.OperationId); Text(receipt.ReceiptId); Text(receipt.AuthenticatedOperator); Text(receipt.ActorTenant);
        Enum(receipt.Action.Value, 2); Enum(receipt.Disposition.Value, 5);
        var before = DispatcherGeneration(receipt.BeforeGeneration); var after = DispatcherGeneration(receipt.AfterGeneration);
        Require(receipt.OperationId == original.OperationId && receipt.Action == original.Action && before == original.ExpectedGeneration);
        Require(receipt.Disposition == Tx.StateOperationDisposition.Committed);
        Require(after.OwnerEpoch == before.OwnerEpoch && before.Revision != ulong.MaxValue && after.Revision == before.Revision + 1);
        Require(receipt.Action != Tx.DispatcherAction.Resume || receipt.ClockContinuityProven && !receipt.RestoreReviewRequired);
    }

    private static void Source(Tx.SourceIdentity? raw)
    {
        var value = Present(raw); Require(value.PublicationId.StartsWith("publication:", StringComparison.Ordinal)); Digest(value.PublicationId[12..]);
        foreach (var id in new[] { value.RevisionId, value.InputFormat, value.ResultFormat }) Identity(id);
        foreach (var digest in new[] { value.ReleaseDigest, value.ComponentDigest, value.ContractDigest, value.StateSchema }) Digest(digest);
        Require(value.RouteGeneration != 0);
    }
    private static void Retention(Tx.LinkedRetention? value)
    {
        if (value is null) return; Text(value.RecordFormat); Require(value.RecordVersion != 0 && value.RequiredRecordIds.Count <= 256);
        foreach (var id in value.RequiredRecordIds) Text(id);
    }
    private static void Success(Profile.Success value)
    {
        Bytes(value.Payload, 1024 * 1024, false); Media(value.MediaType); Metadata(value.Metadata);
        if (value.CommittedStateVersion is not null) Text(value.CommittedStateVersion);
        Require(value.EffectIds.Count <= 128); foreach (var id in value.EffectIds) Text(id);
    }
    private static void Rejection(Profile.DeclaredError value)
    {
        Text(value.Code); Text(value.Message, 4096, false, false); Bytes(value.Payload, 1024 * 1024, false); Media(value.MediaType); Metadata(value.Metadata);
    }
    private static void Failure(Profile.PlatformError value)
    {
        Text(value.Code); if (!PlatformCodes.Contains(value.Code)) throw new TransactionWireValueException("platform_error.code", value.Code);
        Text(value.Message, 1024, false, false); Require(value.DetailItems.Count <= 16);
        foreach (var detail in value.DetailItems) { Text(detail.Kind); Metadata(detail.Fields); }
    }
    private static Tx.CommandInspection Command(Tx.CommandInspection? raw, Tx.CommandSelector? requested)
    {
        var value = Present(raw); var selector = Present(requested); var key = Present(value.Key);
        Namespace(key.Namespace, selector.Namespace!.Tenant); Identity(key.RecoveryScope); Identity(key.Operation); Identity(key.ClientKey); if (key.Entity is not null) Identity(key.Entity);
        Require(key.Namespace == selector.Namespace && key.Operation == selector.Operation && key.Entity == selector.Entity && key.ClientKey == selector.ClientKey);
        Enum(value.Outcome.Value, 7); bool known = value.Outcome.Value is not (5 or 6);
        if (known || value.CommandId.Length != 0) Text(value.CommandId); if (known || value.AttemptId.Length != 0) Text(value.AttemptId);
        Bytes(value.FingerprintSha256, 32, known); Require(!known || value.FingerprintSha256.Length == 32);
        if (known || value.Source is not null) Source(value.Source); Retention(value.Retention);
        int results = (value.Success is null ? 0 : 1) + (value.BusinessRejection is null ? 0 : 1) + (value.TechnicalFailure is null ? 0 : 1); Require(results <= 1);
        if (value.Success is { } success) Success(success); if (value.BusinessRejection is { } reject) Rejection(reject);
        if (value.TechnicalFailure is { } failed) Failure(failed); if (value.CleanupFailure is { } cleanup) Failure(cleanup);
        if (value.Commit is { } commit)
        {
            foreach (var id in new[] { commit.CommandId, commit.AttemptId, commit.TransactionId, commit.ReceiptId }) Text(id);
            Bytes(commit.CommittedVersion); Source(commit.Source); Require(commit.EffectIds.Count <= 128 && commit.EffectIds.Distinct(StringComparer.Ordinal).Count() == commit.EffectIds.Count);
            foreach (var id in commit.EffectIds) Text(id);
            Require(commit.CommandId == value.CommandId && commit.AttemptId == value.AttemptId && commit.Source == value.Source);
        }
        if (value.ProvenAbort is { } abort) { Fence(abort); Require(abort.CommandId == value.CommandId && abort.AttemptId == value.AttemptId); }
        bool omitted = results == 0 && value.Retention?.PayloadAvailable == false;
        Require(value.Outcome.Value switch
        {
            2 => value.MetadataDurable && value.ApplicationStateCommitted && value.Commit is not null && value.ProvenAbort is null && (value.Success is not null || omitted),
            3 => value.MetadataDurable && !value.ApplicationStateCommitted && value.Commit is null && value.ProvenAbort is null && (value.BusinessRejection is not null || omitted),
            4 => value.MetadataDurable && !value.ApplicationStateCommitted && value.Commit is null && value.ProvenAbort is not null && value.Success is null && value.BusinessRejection is null,
            7 => value.MetadataDurable && value.ProvenAbort is null && results == 0 && value.ApplicationStateCommitted == (value.Commit is not null),
            _ => !value.ApplicationStateCommitted && value.Commit is null && value.ProvenAbort is null && results == 0
        });
        return value;
    }
    private static void Effect(Tx.EffectReceipt? raw, string requested)
    {
        var value = Present(raw); foreach (var id in new[] { value.EffectId, value.CommandId, value.CommandAttemptId, value.ProviderProfile }) Text(id);
        foreach (var id in new[] { value.ProviderReceipt, value.FailureCode, value.ManagementOperationReceiptId }) if (id is not null) Text(id);
        Enum(value.Disposition.Value, 8); Require(value.EffectId == requested); Retention(value.Retention);
    }
    private static void PageResponse(Tx.PageResponse? raw, Tx.PageRequest? requested, int count)
    {
        var value = Present(raw); var request = Present(requested); Require(value.ReturnedCount == count && count <= request.Limit && value.EncodedBytes <= 1024 * 1024);
        if (value.NextCursor is { } cursor) { Bytes(cursor); Require(request.Cursor is not { } previous || !cursor.Span.SequenceEqual(previous.Span)); }
    }
    private static void View(Tx.ViewIdentity? raw, Tx.NamespaceSelector? expected)
    {
        var value = Present(raw); Namespace(value.Namespace, expected!.Tenant); Require(value.Namespace == expected); Bytes(value.Version); Text(value.StateSchema);
    }
    private static void InvocationResponse(Profile.InvokeResponse? raw, Tx.SourceIdentity? captured, string? expectedActivation = null)
    {
        var value = Present(raw); var source = Present(captured); Source(source); Text(value.ActivationId); Present(value.Consumption);
        Require(expectedActivation is null || expectedActivation == value.ActivationId);
        Require(value.PublicationId == source.PublicationId && value.RevisionId == source.RevisionId && value.ReleaseDigest == source.ComponentDigest && value.RouteGeneration == source.RouteGeneration);
        Require((value.Success is null ? 0 : 1) + (value.DeclaredError is null ? 0 : 1) + (value.PlatformFailure is null ? 0 : 1) == 1);
        if (value.Success is { } success) Success(success); if (value.DeclaredError is { } reject) Rejection(reject); if (value.PlatformFailure is { } failed) Failure(failed);
    }
    private static void Receipt(Tx.StateOperationReceipt? raw, Tx.InspectNamespaceRequest? target, string operation)
    {
        var value = Present(raw); Require(value.Namespace == target!.Namespace && value.OperationId == operation); Namespace(value.Namespace);
        foreach (var id in new[] { value.OperationId, value.ReceiptId, value.AuthenticatedOperator }) Text(id);
        Bytes(value.BeforeVersion); Bytes(value.AfterVersion); Digest(value.PolicyDigest); Enum(value.Disposition.Value, 5); Enum(value.Mutation.Value, 4);
        if (value.RecordId is not null) Text(value.RecordId);
    }
    private static void Receipt(Tx.NamespaceOperationReceipt? raw, Tx.InspectNamespaceRequest? target, string operation)
    {
        var value = Present(raw); var ns = Namespace(value.Namespace); Require(ns.Tenant == target!.Namespace!.Tenant && ns.Namespace == target.Namespace.Namespace && value.OperationId == operation);
        foreach (var id in new[] { value.OperationId, value.ReceiptId, value.AuthenticatedOperator, value.StateSchema }) Text(id);
        Enum(value.Disposition.Value, 5); Enum(value.Mutation.Value, 5); Enum(value.Status.Value, 4); Require(value.Disposition.Value != 1 || value.AfterGeneration != 0);
    }
    private static bool EqualBytes(ReadOnlyMemory<byte> left, ReadOnlyMemory<byte> right) => left.Span.SequenceEqual(right.Span);
    private static bool EqualMetadata(IReadOnlyDictionary<string, string> left, IReadOnlyDictionary<string, string> right) => left.Count == right.Count && left.All(pair => right.TryGetValue(pair.Key, out string? value) && value == pair.Value);
    private static bool EqualSuccess(Profile.Success left, Profile.Success right) => EqualBytes(left.Payload, right.Payload) && left.MediaType == right.MediaType &&
        left.CommittedStateVersion == right.CommittedStateVersion && left.EffectIds.SequenceEqual(right.EffectIds) && EqualMetadata(left.Metadata, right.Metadata);
    private static bool EqualRejection(Profile.DeclaredError left, Profile.DeclaredError right) => left.Code == right.Code && left.Message == right.Message && EqualBytes(left.Payload, right.Payload) && left.MediaType == right.MediaType && EqualMetadata(left.Metadata, right.Metadata);

    internal static void Response(object response, object original, CallState state)
    {
        switch (response, original)
        {
            case (Tx.InvokeCommandResponse value, Tx.InvokeCommandRequest requested):
                var command = Command(value.Command, requested.Command); InvocationResponse(value.Invocation, command.Source, requested.Invocation?.ActivationId);
                if (command.Success is { } success) Require(value.Invocation!.Success is { } other && EqualSuccess(success, other));
                if (command.BusinessRejection is { } reject) Require(value.Invocation!.DeclaredError is { } other && EqualRejection(reject, other));
                Require(command.Success is not null || command.BusinessRejection is not null || command.TechnicalFailure is not null || value.Invocation!.PlatformFailure is not null);
                break;
            case (Tx.LookupCommandResponse value, Tx.LookupCommandRequest requested):
                var lookup = Command(value.Command, requested.Command); Require(requested.AttemptId is null || lookup.AttemptId == requested.AttemptId); break;
            case (Tx.LookupCommitResponse value, Tx.LookupCommitRequest requested): Require(Command(value.Command, requested.Command).Commit?.ReceiptId == requested.ReceiptId); break;
            case (Tx.GetEffectResponse value, Tx.GetEffectRequest requested): Effect(value.Effect, requested.EffectId); break;
            case (Tx.ListEffectHistoryResponse value, Tx.ListEffectHistoryRequest requested):
                foreach (var receipt in value.Receipts) Effect(receipt, requested.Effect!.EffectId); PageResponse(value.Page, requested.Page, value.Receipts.Count); break;
            case (Tx.CancelCommandResponse value, Tx.CancelCommandRequest requested):
                Enum(value.Disposition.Value, 5); if (value.Command is null) Require(value.Disposition.Value == 4);
                else { var inspected = Command(value.Command, requested.Command!.Command); Require(value.Disposition.Value != 2 || inspected.Outcome.Value == 2); }
                break;
            case (Tx.QueryResponse value, Tx.QueryRequest requested): View(value.View, requested.Namespace); InvocationResponse(value.Invocation, value.Source, requested.Invocation?.ActivationId); break;
            case (Tx.InspectNamespaceResponse value, Tx.InspectNamespaceRequest requested):
                var inspectedNs = Present(value.Namespace); View(inspectedNs.View, requested.Namespace); Enum(inspectedNs.Status.Value, 4); Require(inspectedNs.Generation != 0);
                Quota(inspectedNs.Quota); Text(inspectedNs.EngineProfile); Digest(inspectedNs.EngineProfileDigest); foreach (var format in inspectedNs.RetainedFormats) Retention(format); break;
            case (Tx.SelectEntityResponse value, Tx.SelectEntityRequest requested):
                var names = new HashSet<string>(StringComparer.Ordinal); foreach (var entity in value.Entities) { Identity(entity.Entity); Bytes(entity.Version); Require(names.Add(entity.Entity)); }
                PageResponse(value.Page, requested.Page, value.Entities.Count); break;
            case (Tx.MutateStateResponse value, Tx.MutateStateRequest requested):
                Receipt(value.Receipt, requested.Namespace, requested.OperationId); var acceptedState = value.Receipt!;
                Require(acceptedState.Mutation == requested.Mutation && acceptedState.RecordId == requested.RecordId && EqualBytes(acceptedState.BeforeVersion, requested.ExpectedVersion) && acceptedState.PolicyDigest == requested.ExpectedPolicyDigest);
                break;
            case (Tx.MutateNamespaceResponse value, Tx.MutateNamespaceRequest requested):
                Receipt(value.Receipt, requested.Namespace, requested.OperationId); var accepted = value.Receipt!;
                Require(accepted.Mutation == requested.Mutation && accepted.BeforeGeneration == (requested.Mutation.Value == 1 ? null : requested.ExpectedGeneration));
                if (accepted.Disposition.Value == 1)
                {
                    ulong before = requested.ExpectedGeneration!.Value, incarnation = Incarnation(requested.Namespace!.Namespace!.Incarnation);
                    Require(before != ulong.MaxValue && (requested.Mutation.Value != 5 || incarnation != ulong.MaxValue));
                    Require(accepted.AfterGeneration == before + 1 && accepted.Namespace!.Incarnation == (incarnation + (requested.Mutation.Value == 5 ? 1UL : 0UL)).ToString(CultureInfo.InvariantCulture));
                    Require(accepted.Status.Value == (requested.Mutation.Value is 1 or 5 ? 1 : requested.Mutation.Value));
                    Require(requested.Configuration is null || requested.Configuration.StateSchema == accepted.StateSchema);
                }
                break;
            case (Tx.GetStateOperationReceiptResponse value, Tx.GetStateOperationReceiptRequest requested):
                Require((value.Receipt is null) != (value.NamespaceReceipt is null));
                if (value.Receipt is not null) Receipt(value.Receipt, requested.Namespace, requested.OperationId);
                else Receipt(value.NamespaceReceipt, requested.Namespace, requested.OperationId);
                break;
            case (Tx.InspectDispatcherResponse value, Tx.InspectDispatcherRequest):
                var snapshot = Present(value.Dispatcher); DispatcherGeneration(snapshot.Generation); Enum(snapshot.Failure.Value, 7);
                Require(!(snapshot.PendingControl || snapshot.RestoreReviewRequired) || snapshot.Paused);
                break;
            case (Tx.ControlDispatcherResponse value, Tx.ControlDispatcherRequest requested):
                DispatcherReceipt(value.Receipt, requested);
                Require(!(value.Replayed && value.Published));
                Require(requested.Action != Tx.DispatcherAction.Pause || !value.Published || value.Paused);
                break;
            case (Tx.GetDispatcherOperationResponse value, Tx.GetDispatcherOperationRequest requested):
                DispatcherReceipt(value.Receipt, requested.Original!); break;
            default: throw new FormatException("response owner does not match the original operation");
        }
        state.ObservedTransaction = Observe(response);
        state.TransactionIdentity = Extend(state.TransactionIdentity, state.ObservedTransaction);
        state.Outcome = Known(state.ObservedTransaction) ? Profile.OutcomeKnowledge.Observed : Profile.OutcomeKnowledge.Unknown;
        // A malformed independent audit value cannot erase an already validated durable receipt.
        Profile.AuditAck? audit = response switch
        {
            Tx.MutateStateResponse value => value.AuditAck, Tx.MutateNamespaceResponse value => value.AuditAck,
            Tx.InspectDispatcherResponse value => value.AuditAck, Tx.ControlDispatcherResponse value => value.AuditAck,
            Tx.GetDispatcherOperationResponse value => value.AuditAck, _ => null
        };
        if (audit is not null) Enum(audit.Status.Value, 4);
    }

    private static Tx.ObservedOutcome? Observe(object response)
    {
        Tx.CommandInspection? command = response switch
        {
            Tx.InvokeCommandResponse value => value.Command, Tx.LookupCommandResponse value => value.Command,
            Tx.LookupCommitResponse value => value.Command, Tx.CancelCommandResponse value => value.Command, _ => null
        };
        if (command is not null) return new() { Command = command with { Success = null, BusinessRejection = null, TechnicalFailure = null, CleanupFailure = null } };
        return response switch
        {
            Tx.GetEffectResponse value => new() { Effect = value.Effect }, Tx.MutateStateResponse value => new() { State = value.Receipt },
            Tx.MutateNamespaceResponse value => new() { Namespace = value.Receipt }, Tx.GetStateOperationReceiptResponse value => new() { State = value.Receipt, Namespace = value.NamespaceReceipt },
            Tx.ControlDispatcherResponse value => new() { Dispatcher = value.Receipt }, Tx.GetDispatcherOperationResponse value => new() { Dispatcher = value.Receipt }, _ => null
        };
    }
    private static bool Known(Tx.ObservedOutcome? value) => value?.Command is { MetadataDurable: true } command && command.Outcome.Value is 2 or 3 or 4 ||
        value?.State?.Disposition.Value is 1 or 2 or 3 || value?.Namespace?.Disposition.Value is 1 or 2 or 3 || value?.Dispatcher?.Disposition.Value is 1 or 2 or 3;
    private static Tx.RecoveryIdentity Extend(Tx.RecoveryIdentity original, Tx.ObservedOutcome? observed)
    {
        if (observed?.Command is { } command) return original with
        {
            CommandId = command.CommandId.Length == 0 ? original.CommandId : command.CommandId,
            AttemptId = original.AttemptId ?? (command.AttemptId.Length == 0 ? null : command.AttemptId),
            ReceiptId = original.ReceiptId ?? command.Commit?.ReceiptId,
            FingerprintSha256 = command.FingerprintSha256.IsEmpty ? original.FingerprintSha256 : command.FingerprintSha256.ToArray()
        };
        return original with { ReceiptId = observed?.State?.ReceiptId ?? observed?.Namespace?.ReceiptId ?? observed?.Dispatcher?.ReceiptId ?? original.ReceiptId };
    }

    internal static Tx.RecoveryIdentity IdentitySnapshot(object original)
    {
        try
        {
            Tx.CommandSelector? command = original switch
            {
                Tx.InvokeCommandRequest value => value.Command, Tx.LookupCommandRequest value => value.Command,
                Tx.LookupCommitRequest value => value.Command, Tx.GetEffectRequest value => value.Command,
                Tx.ListEffectHistoryRequest value => value.Effect?.Command, Tx.CancelCommandRequest value => value.Command?.Command, _ => null
            };
            Tx.InspectNamespaceRequest? inspect = original switch
            {
                Tx.InspectNamespaceRequest value => value, Tx.SelectEntityRequest value => value.Namespace, Tx.MutateNamespaceRequest value => value.Namespace,
                Tx.MutateStateRequest value => value.Namespace, Tx.GetStateOperationReceiptRequest value => value.Namespace, _ => null
            };
            Tx.NamespaceSelector? ns = command?.Namespace ?? inspect?.Namespace ?? (original as Tx.QueryRequest)?.Namespace;
            if (ns is not null) Namespace(ns); if (command is not null) Selector(command);
            var invoke = original as Tx.InvokeCommandRequest; var state = original as Tx.MutateStateRequest; var lifecycle = original as Tx.MutateNamespaceRequest;
            var dispatcher = original as Tx.ControlDispatcherRequest ?? (original as Tx.GetDispatcherOperationRequest)?.Original;
            if (dispatcher is not null) { Text(dispatcher.OperationId); Enum(dispatcher.Action.Value, 2); DispatcherGeneration(dispatcher.ExpectedGeneration); }
            if (state is not null) Bytes(state.ExpectedVersion);
            if (invoke is not null)
            {
                Require(invoke.ExpectedVersions is not null && invoke.ExpectedVersions.Count <= 128);
                foreach (var entry in invoke.ExpectedVersions!) { Bytes(entry.Key, 1024, false); if (entry.Version is { } originalVersion) Bytes(originalVersion); }
                if (invoke.RetryAttempt is { } retry) Fence(retry.ExpectedAbort);
            }
            Profile.PublicationRef? publication = original switch
            {
                Tx.LookupCommandRequest value => value.AuthorizationPublication, Tx.LookupCommitRequest value => value.AuthorizationPublication,
                Tx.GetEffectRequest value => value.AuthorizationPublication, Tx.ListEffectHistoryRequest value => value.Effect?.AuthorizationPublication,
                Tx.CancelCommandRequest value => value.Command?.AuthorizationPublication, _ => inspect?.AuthorizationPublication
            };
            var snapshot = new Tx.RecoveryIdentity
            {
                Namespace = ns, Command = command,
                ActivationId = invoke?.Invocation?.ActivationId ?? (original as Tx.QueryRequest)?.Invocation?.ActivationId,
                OperationId = lifecycle?.OperationId ?? state?.OperationId ?? (original as Tx.GetStateOperationReceiptRequest)?.OperationId ?? dispatcher?.OperationId,
                AttemptId = (original as Tx.LookupCommandRequest)?.AttemptId ?? invoke?.RetryAttempt?.ExpectedAbort?.AttemptId ?? (original as Tx.CancelCommandRequest)?.Command?.AttemptId,
                ReceiptId = (original as Tx.LookupCommitRequest)?.ReceiptId,
                EffectId = (original as Tx.GetEffectRequest)?.EffectId ?? (original as Tx.ListEffectHistoryRequest)?.Effect?.EffectId,
                ExpectedGeneration = lifecycle?.ExpectedGeneration,
                DispatcherAction = dispatcher?.Action, DispatcherExpectedGeneration = dispatcher?.ExpectedGeneration,
                ExpectedVersion = state is null ? (ReadOnlyMemory<byte>?)null : new ReadOnlyMemory<byte>(state.ExpectedVersion.ToArray()), ExpectedPolicyDigest = state?.ExpectedPolicyDigest,
                AuthorizationPublication = publication, RetryRequestId = invoke?.RetryAttempt?.RequestId,
                ExpectedAbort = invoke?.RetryAttempt?.ExpectedAbort is { } abort ? abort with { OwnerFence = abort.OwnerFence.ToArray() } : null,
                ExpectedVersions = invoke?.ExpectedVersions.Count <= 128 ? invoke.ExpectedVersions.Select(v => v with
                {
                    Key = v.Key.ToArray(), Version = v.Version is { } presentVersion ? new ReadOnlyMemory<byte>(presentVersion.ToArray()) : (ReadOnlyMemory<byte>?)null
                }).ToArray() : null
            };
            Collections(snapshot, new GraphBudget(384 * 1024, 4096, CancellationToken.None));
            foreach (var id in new[] { snapshot.ActivationId, snapshot.OperationId, snapshot.AttemptId, snapshot.ReceiptId, snapshot.EffectId, snapshot.RetryRequestId }) if (id is not null) Text(id);
            if (snapshot.ExpectedAbort is not null) Fence(snapshot.ExpectedAbort); if (snapshot.ExpectedVersion is { } version) Bytes(version);
            foreach (var expected in snapshot.ExpectedVersions ?? []) { Bytes(expected.Key, 1024, false); if (expected.Version is { } expectedVersion) Bytes(expectedVersion); }
            return snapshot;
        }
        catch (Exception failure) when (failure is FormatException or GraphLimitException or ArgumentException or OverflowException or NullReferenceException) { return new(); }
    }

    internal static ulong? WallDeadline(object request) => request switch
    {
        Tx.InvokeCommandRequest value => value.Invocation?.DeadlineUnixMillis,
        Tx.QueryRequest value => value.Invocation?.DeadlineUnixMillis, _ => null
    };
}
