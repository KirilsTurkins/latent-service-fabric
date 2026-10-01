using System.Diagnostics;
using System.Text;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

namespace Latent.Sdk.Transport;

internal sealed class CallState
{
    internal Profile.RequestIdentity Identity;
    internal Profile.OutcomeKnowledge Outcome = Profile.OutcomeKnowledge.Unknown;
    internal Profile.AuditAck? AuditAck;
    internal string? AuditStatus;
    internal ulong? AuditAttemptSequence;
    internal int? GrpcStatus;
    internal bool Dispatched;
    internal readonly int RequestLimit;
    internal readonly int ResponseLimit;
    internal readonly bool Recovery;
    internal readonly bool RecoveryRead;
    internal readonly TimeSpan Timeout;
    internal readonly long Deadline;
    internal readonly CancellationToken Caller;
    internal CancellationToken Expiry;
    internal readonly bool Transactional;
    internal Tx.RecoveryIdentity TransactionIdentity = new();
    internal Tx.ObservedOutcome? ObservedTransaction;
    internal Action<object>? ValidateTransactionResponse;

    internal CallState(ClientOptions config, object request, Profile.CallOptions options, CancellationToken caller, bool transactional = false)
    {
        Caller = caller;
        Transactional = transactional;
        if (transactional) TransactionIdentity = TransactionRules.IdentitySnapshot(request);
        RequestLimit = Math.Min(config.MaxRequestBytes, 128 * 1024);
        ResponseLimit = Math.Min(config.MaxResponseBytes, 1024 * 1024);
        Identity = new(null, null);
        switch (request)
        {
            case Profile.InvokeRequest invoke:
                Identity = new(Known(invoke.ActivationId), null);
                RequestLimit = config.MaxRequestBytes;
                ResponseLimit = config.MaxResponseBytes;
                break;
            case Profile.CancelRequest cancel:
                Identity = new(Known(cancel.ActivationId), null);
                Recovery = true;
                break;
            case Profile.GetActivationRequest activation:
                Identity = new(Known(activation.ActivationId), null);
                Recovery = true;
                RecoveryRead = true;
                break;
            case Profile.ApplyPolicyRequest policy:
                Identity = new(null, Known(policy.OperationId));
                break;
            case Profile.GetPolicyOperationRequest operation:
                Identity = new(null, Known(operation.OperationId));
                Recovery = true;
                RecoveryRead = true;
                break;
            case Profile.ListCapabilitiesRequest:
                RequestLimit = Math.Min(config.MaxRequestBytes, 8192);
                ResponseLimit = Math.Min(config.MaxResponseBytes, 128 * 1024);
                break;
        }
        if (transactional)
        {
            Identity = new(TransactionIdentity.ActivationId, TransactionIdentity.OperationId);
            RequestLimit = Math.Min(config.MaxRequestBytes, 2 * 1024 * 1024);
            ResponseLimit = Math.Min(config.MaxResponseBytes, 2 * 1024 * 1024);
            Recovery = request is Tx.LookupCommandRequest or Tx.LookupCommitRequest or Tx.GetEffectRequest or Tx.ListEffectHistoryRequest or Tx.CancelCommandRequest or Tx.GetStateOperationReceiptRequest;
            RecoveryRead = Recovery && request is not Tx.CancelCommandRequest;
        }
        Timeout = config.DefaultTimeout;
        if (options is null) throw Error(Profile.FailureCategory.InvalidRequest, "call options are required");
        if (options.TimeoutMillis is ulong milliseconds)
        {
            if (milliseconds > long.MaxValue / TimeSpan.TicksPerMillisecond)
                throw Error(Profile.FailureCategory.InvalidRequest, "local timeout cannot be represented");
            if (milliseconds > 30000) throw Error(Profile.FailureCategory.Limit, "local timeout exceeds the 30 second ceiling");
            var requested = TimeSpan.FromTicks(checked((long)milliseconds * TimeSpan.TicksPerMillisecond));
            Timeout = transactional && requested > Timeout ? Timeout : requested;
        }
        if (transactional && TransactionRules.WallDeadline(request) is { } wall)
        {
            ulong current = checked((ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            ulong remaining = wall > current ? wall - current : 0;
            if (remaining < (ulong)Math.Ceiling(Timeout.TotalMilliseconds)) Timeout = TimeSpan.FromMilliseconds(remaining);
        }
        Deadline = checked(Stopwatch.GetTimestamp() + (long)(Timeout.TotalSeconds * Stopwatch.Frequency));
    }

    internal TimeSpan Remaining => TimeSpan.FromSeconds(Math.Max(0, Deadline - Stopwatch.GetTimestamp()) / (double)Stopwatch.Frequency);

    internal Profile.ResponseMetadata Metadata => new(Identity, Outcome, AuditAck, AuditStatus, AuditAttemptSequence);

    internal Profile.ClientFailure Failure(Profile.FailureCategory category, string message) => new(category, message, GrpcStatus, null,
        Dispatched, Dispatched ? Outcome : Profile.OutcomeKnowledge.NotDispatched, Identity, AuditAck, AuditStatus, null, AuditAttemptSequence);

    internal Tx.TransactionMetadata TransactionMetadata => new(Metadata, TransactionIdentity, ObservedTransaction);

    internal Exception Wrap(Profile.ClientFailure failure) => Transactional
        ? new Tx.TransactionException(new(failure, TransactionIdentity, ObservedTransaction)) : new Profile.ClientException(failure);

    internal Exception Error(Profile.FailureCategory category, string message) => Wrap(Failure(category, message));

    internal Exception Cancelled(CancellationToken cancellationToken)
    {
        if (Caller.IsCancellationRequested)
            return Cancellation(Failure(Profile.FailureCategory.LocalCancelled, "local wait cancelled; remote outcome may remain unknown"), Caller);
        if (Expiry.IsCancellationRequested || Remaining == TimeSpan.Zero)
            return Cancellation(Failure(Profile.FailureCategory.Deadline, "original local deadline expired; recover by the original identity"), cancellationToken);
        return Error(Profile.FailureCategory.Transport, "client connection closed; recover by the original identity");
    }

    private Exception Cancellation(Profile.ClientFailure failure, CancellationToken token) => Transactional
        ? new Tx.TransactionCancellationException(new(failure, TransactionIdentity, ObservedTransaction), token)
        : new Profile.ClientCancellationException(failure, token);

    private static string? Known(string? value) => value is not null && Encoding.UTF8.GetByteCount(value) <= 256 ? value : null;
}
