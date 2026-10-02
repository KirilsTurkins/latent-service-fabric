using Tx = Latent.Sdk.Transactions;

namespace Latent.Sdk.Transport;

internal static partial class TransactionRules
{
    // A checked plan carries original preconditions, not authority or provider proof.
    private static void EffectVersion(ReadOnlyMemory<byte> value)
    {
        Require(value.Length == 32 && value.Span.ContainsAnyExcept((byte)0));
    }

    private static Tx.PlanEffectMutationRequest EffectMutation(Tx.PlanEffectMutationRequest? raw)
    {
        var value = Present(raw); var target = Present(value.Effect);
        Lookup(target.Profile, target.Command, target.AuthorizationPublication);
        Require(target.EffectId.Length == 64 && target.EffectId.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f'));
        Text(value.OperationId); EffectVersion(value.ExpectedVersion); Digest(value.ExpectedPolicyDigest); Text(value.Reason, 1024);
        Enum(value.Mutation.Value, 5);
        Require(value.Mutation.Value == 1 && value.RetryDelayMillis is >= 1 and <= 60000 || value.Mutation.Value is 2 or 5 && value.RetryDelayMillis == 0);
        return value;
    }

    private static Tx.EffectManagementPlan EffectPlan(Tx.EffectManagementPlan? raw)
    {
        var plan = Present(raw); var original = EffectMutation(plan.Original); EffectVersion(plan.PlanDigest);
        bool attempted = plan.OwnerEpoch != 0 && plan.ClaimGeneration != 0 && plan.DispatchAttempt != 0;
        Require(plan.ManagementSequence is >= 1 and <= 128 && plan.DispatchAttempt <= 128 &&
            (attempted || plan.OwnerEpoch == 0 && plan.ClaimGeneration == 0 && plan.DispatchAttempt == 0) &&
            plan.PreparedAtUnixMillis != 0 && plan.ExpiresAtUnixMillis > plan.PreparedAtUnixMillis && plan.ExpiresAtUnixMillis - plan.PreparedAtUnixMillis <= 30000);
        Enum(plan.Before.Value, 10); Enum(plan.Safety.Value, 4);
        Require(original.Mutation.Value == 1 && attempted && (plan.Safety.Value == 1 && plan.Before.Value == 4 || plan.Safety.Value == 2 && plan.Before.Value is 4 or 5) ||
            original.Mutation.Value == 5 && attempted && plan.Safety.Value == 3 && plan.Before.Value is 4 or 5 ||
            original.Mutation.Value == 2 && plan.Safety.Value == 4 && plan.Before.Value is 1 or 4 or 5 or 7 or 9);
        Require((plan.Safety.Value == 2) == plan.DedupValidUntilUnixMillis.HasValue);
        if (plan.DedupValidUntilUnixMillis is { } horizon) Require(horizon > plan.ExpiresAtUnixMillis);
        // Historical receipt validation intentionally uses no current-clock comparison.
        return plan;
    }

    private static bool EqualEffectMutation(Tx.PlanEffectMutationRequest left, Tx.PlanEffectMutationRequest right) =>
        left.Effect == right.Effect && left.OperationId == right.OperationId && left.Mutation == right.Mutation &&
        EqualBytes(left.ExpectedVersion, right.ExpectedVersion) && left.ExpectedPolicyDigest == right.ExpectedPolicyDigest &&
        left.Reason == right.Reason && left.RetryDelayMillis == right.RetryDelayMillis;

    private static bool EqualEffectPlan(Tx.EffectManagementPlan left, Tx.EffectManagementPlan right) =>
        EqualEffectMutation(Present(left.Original), Present(right.Original)) && EqualBytes(left.PlanDigest, right.PlanDigest) &&
        left.ManagementSequence == right.ManagementSequence && left.OwnerEpoch == right.OwnerEpoch && left.ClaimGeneration == right.ClaimGeneration &&
        left.DispatchAttempt == right.DispatchAttempt && left.ExpiresAtUnixMillis == right.ExpiresAtUnixMillis &&
        left.PreparedAtUnixMillis == right.PreparedAtUnixMillis && left.Before == right.Before && left.Safety == right.Safety &&
        left.DedupValidUntilUnixMillis == right.DedupValidUntilUnixMillis;

    private static void EffectPlanAssociation(Tx.InspectNamespaceRequest? current, string operation, Tx.EffectManagementPlan raw, Tx.MutateStateRequest? mutation = null)
    {
        var plan = EffectPlan(raw); var original = plan.Original!; var target = original.Effect!; var selected = Present(current);
        Require(selected.Namespace == target.Command!.Namespace && selected.Profile == target.Profile && operation == original.OperationId);
        if (mutation is not null) Require(selected.AuthorizationPublication == target.AuthorizationPublication && mutation.RecordId == target.EffectId &&
            mutation.Mutation == original.Mutation && EqualBytes(mutation.ExpectedVersion, original.ExpectedVersion) &&
            mutation.ExpectedPolicyDigest == original.ExpectedPolicyDigest && mutation.Reason == original.Reason);
    }

    private static void EffectPlanReceipt(Tx.StateOperationReceipt value, Tx.EffectManagementPlan expected)
    {
        var details = Present(value.Effect); var plan = EffectPlan(details.OriginalPlan); var original = plan.Original!;
        Require(EqualEffectPlan(plan, expected) && details.Before == plan.Before && value.OperationId == original.OperationId && value.Mutation == original.Mutation &&
            value.RecordId == original.Effect!.EffectId && EqualBytes(value.BeforeVersion, original.ExpectedVersion) && value.PolicyDigest == original.ExpectedPolicyDigest);
        EffectVersion(value.BeforeVersion); EffectVersion(value.AfterVersion);
        Require(value.Disposition.Value == 1 && value.CompletedAtUnixMillis >= plan.PreparedAtUnixMillis && value.CompletedAtUnixMillis < plan.ExpiresAtUnixMillis);
        Enum(details.Fact.Value, 3); Enum(details.After.Value, 10);
        Require(details.Fact.Value == 1 && original.Mutation.Value == 1 && details.After.Value == 9 ||
            details.Fact.Value == 2 && original.Mutation.Value == 5 && details.After.Value == 3 ||
            details.Fact.Value == 3 && original.Mutation.Value == 2 && details.After.Value is 8 or 10);
        Require((details.Fact.Value == 2) == (details.ProviderReceipt is not null) && (details.ProviderReceipt is not null) == details.ProviderObservedAtUnixMillis.HasValue);
        if (details.ProviderReceipt is { } receipt) Text(receipt);
        if (details.ProviderObservedAtUnixMillis is { } observed) Require(observed != 0 && observed <= value.CompletedAtUnixMillis);
    }
}
