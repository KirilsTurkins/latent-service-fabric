using System.Diagnostics;
using System.Text;
using Profile = Latent.Sdk.Profile;

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
    internal readonly TimeSpan Timeout;
    internal readonly long Deadline;
    internal readonly CancellationToken Caller;

    internal CallState(ClientOptions config, object request, Profile.CallOptions options, CancellationToken caller)
    {
        Caller = caller;
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
                break;
            case Profile.ApplyPolicyRequest policy:
                Identity = new(null, Known(policy.OperationId));
                break;
            case Profile.GetPolicyOperationRequest operation:
                Identity = new(null, Known(operation.OperationId));
                Recovery = true;
                break;
            case Profile.ListCapabilitiesRequest:
                RequestLimit = Math.Min(config.MaxRequestBytes, 8192);
                ResponseLimit = Math.Min(config.MaxResponseBytes, 128 * 1024);
                break;
        }
        Timeout = config.DefaultTimeout;
        if (options is null) throw Error(Profile.FailureCategory.InvalidRequest, "call options are required");
        if (options.TimeoutMillis is ulong milliseconds)
        {
            if (milliseconds > long.MaxValue / TimeSpan.TicksPerMillisecond)
                throw Error(Profile.FailureCategory.InvalidRequest, "local timeout cannot be represented");
            if (milliseconds > 30000) throw Error(Profile.FailureCategory.Limit, "local timeout exceeds the 30 second ceiling");
            Timeout = TimeSpan.FromTicks(checked((long)milliseconds * TimeSpan.TicksPerMillisecond));
        }
        Deadline = checked(Stopwatch.GetTimestamp() + (long)(Timeout.TotalSeconds * Stopwatch.Frequency));
    }

    internal TimeSpan Remaining => TimeSpan.FromSeconds(Math.Max(0, Deadline - Stopwatch.GetTimestamp()) / (double)Stopwatch.Frequency);

    internal Profile.ResponseMetadata Metadata => new(Identity, Outcome, AuditAck, AuditStatus, AuditAttemptSequence);

    internal Profile.ClientFailure Failure(Profile.FailureCategory category, string message) => new(category, message, GrpcStatus, null,
        Dispatched, Dispatched ? Outcome : Profile.OutcomeKnowledge.NotDispatched, Identity, AuditAck, AuditStatus, null, AuditAttemptSequence);

    internal Profile.ClientException Error(Profile.FailureCategory category, string message) => new(Failure(category, message));

    internal Exception Cancelled(CancellationToken cancellationToken)
    {
        if (Caller.IsCancellationRequested)
            return new Profile.ClientCancellationException(Failure(Profile.FailureCategory.LocalCancelled, "local wait cancelled; remote outcome may remain unknown"), Caller);
        if (Remaining == TimeSpan.Zero)
            return new Profile.ClientCancellationException(Failure(Profile.FailureCategory.Deadline, "original local deadline expired; recover by the original identity"), cancellationToken);
        return Error(Profile.FailureCategory.Transport, "client connection closed; recover by the original identity");
    }

    private static string? Known(string? value) => value is not null && Encoding.UTF8.GetByteCount(value) <= 256 ? value : null;
}
