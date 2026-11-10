package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Preserves the user's original version when an edit has become stale. */
public final class Phase4RealStaleQuery {
    private Phase4RealStaleQuery() { }
    private static String required(String key) { String v=System.getenv(key); if (v==null || v.isEmpty()) throw new IllegalArgumentException("missing fixture field: "+key); return v; }
    private static void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private static byte[] bytes(ByteBuffer value) { var copy=value.asReadOnlyBuffer(); byte[] result=new byte[copy.remaining()]; copy.get(result); return result; }
    public static void main(String[] args) throws Exception {
        String tenant=required("LSF_401_TENANT"), key="java-sdk-stale-edit";
        byte[] version=HexFormat.of().parseHex(required("LSF_401_EXPECTED_VERSION_HEX")); check(version.length>0,"original version");
        var ns=new Transactions.NamespaceSelector(tenant,required("LSF_401_NAMESPACE"),required("LSF_401_INCARNATION"));
        var selector=new Transactions.CommandSelector(Optional.of(ns),"update",Optional.empty(),key,Optional.empty());
        var target=new Management.InvocationTarget(tenant,"examples/transaction-java-aggregate","examples:transactional-aggregate/api@1.0.0","update",Optional.of("transaction-java-aggregate"));
        var budget=new Management.ResourceBudget(1000000000L,67108864L,0,0,4194304L,2097152L,0,0,0,1,Optional.of(120000L));
        var invocation=new Management.InvokeRequest(Optional.of(key),Optional.empty(),Optional.empty(),Optional.of(target),ByteBuffer.wrap("[{\"delta\":1,\"reject\":false}]".getBytes(StandardCharsets.UTF_8)),"application/vnd.latent.wit-values.v1+json",Optional.empty(),0,Optional.empty(),Optional.of(budget),Map.of());
        var expected=new Transactions.ExpectedVersion(ByteBuffer.wrap("aggregate/count".getBytes(StandardCharsets.UTF_8)),Optional.empty(),Optional.of(ByteBuffer.wrap(version)));
        var request=new Transactions.InvokeCommandRequest(Optional.of(Transactions.currentProfile()),Optional.of(invocation),Optional.of(selector),"lsf-wit-values-v1",List.of(expected),Optional.empty());
        var client=new RpcClient(ClientConfig.loopback("http://"+required("LSF_401_ENDPOINT"),tenant,required("LSF_401_TOKEN")));
        try {
            var response=client.invokeCommand(request,new Management.CallOptions(Optional.of(15000L))).get(20,TimeUnit.SECONDS);
            check(java.util.Arrays.equals(bytes(response.metadata().identity().expectedVersions().get(0).version().orElseThrow()),version),"original version retained");
            var command=response.value().command().orElseThrow();
            check(command.outcome().equals(Transactions.CommandOutcome.ABORTED) && command.metadataDurable() && !command.applicationStateCommitted(),"durable abort");
            check(command.commit().isEmpty() && command.provenAbort().isPresent(),"abort fence");
            System.out.println("JAVA_STALE_EDIT_ABORTED");
        } finally { check(client.shutdown(Duration.ofSeconds(5)).clean(),"client retirement"); }
    }
}
