using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Wire = global::Latent.Control.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static async Task TargetInspection()
    {
        await using Peer peer=await Peer.Start(async context => {
            Check(context.Request.Path=="/latent.control.v1.NodeService/InspectHttpTarget","target RPC changed");
            var input=await Peer.Read<Wire.InspectHttpTargetRequest>(context);
            var response=new Wire.InspectHttpTargetResponse { SchemaVersion=1,Tenant=input.Function=="foreign" ? "foreign" : "tenant-a",Service=input.Service,Contract=input.Contract,Function=input.Function,
                Route=input.HasRoute ? input.Route : "default",State=(Wire.TargetObservationState)(input.Function=="future" ? 777 : 1),CatalogTransaction=ulong.MaxValue };
            var candidate=new Wire.TargetCandidate { DeploymentId="deployment-a",RevisionId=input.Function=="drift" ? "revision-b" : "revision-a",ComponentDigest="sha256:"+new string('a',64),Publication=input.Publication,
                Preparation=new() { State=(Wire.TargetPreparationState)(input.Function=="unmeasured" ? 1 : input.Function=="future" ? 779 : input.IncludePreparation ? 3 : 4) } };
            candidate.Reasons.Add((Wire.TargetReason)777); response.Candidates.Add(candidate);
            await Peer.Reply(context,response);
        });
        await using var client=await BoundedClient.ConnectAsync(Options(peer.Endpoint));
        var input=new Profile.InspectHttpTargetRequest("service-a","domain:api/contract@1.0.0","get",null,"revision-a",new("publication:sha256:"+new string('b',64),"tenant-a"),null,true,0);
        var result=await client.InspectHttpTargetAsync(input,Defaults);
        Check(result.Value.CatalogTransaction==ulong.MaxValue && result.Value.Candidates[0].Reasons[0].Value==777 && result.Metadata.Identity.OperationId is null && !result.Value.LiveGrantsChecked,"target narrowed or fabricated identity/authority");
        foreach (string function in new[] { "foreign","drift","unmeasured" }) await Failure(client.InspectHttpTargetAsync(input with { Function=function },Defaults).AsTask(),Profile.FailureCategory.Decode,true);
        result=await client.InspectHttpTargetAsync(input with { Function="future" },Defaults);
        Check(result.Value.State.Value==777 && result.Value.Candidates[0].Preparation!.State.Value==779 && !result.Value.Candidates[0].Eligible,"future target state established authority");
        await Failure(client.InspectHttpTargetAsync(input with { MaximumWaitMillis=30001 },Defaults).AsTask(),Profile.FailureCategory.InvalidRequest,false);
        Check(peer.Requests.Single().Value==5 && peer.Connections.Count==1,"inspection dispatched invalid wait, retried or created other operations");
    }
}
