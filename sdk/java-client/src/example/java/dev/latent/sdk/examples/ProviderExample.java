package dev.latent.sdk.examples;

import com.google.gson.Gson;
import dev.latent.sdk.Management;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

public final class ProviderExample {
    private ProviderExample() { }

    public static void main(String[] args) throws Exception {
        ProviderInput.require(args.length == 4 && args[0].equals("--config") && args[2].equals("--activation-prefix")
                && args[3].matches("[a-z][a-z0-9-]{1,32}"), "example-arguments");
        var input = new ProviderInput(Path.of(args[1]));
        var results = new ArrayList<Map<String, String>>();
        try (var client = input.client(input.field("tenant"), false, false)) {
            for (String provider : new String[] {"http", "blob"}) {
                String identity = args[3] + "-" + provider;
                var response = client.invoke(input.request(provider, identity, null, input.field("tenant"), false),
                        new Management.CallOptions(Optional.of(3000L))).get(4, TimeUnit.SECONDS).value();
                input.identity(response, provider, identity);
                ProviderInput.guest(response);
                results.add(Map.of("provider", provider, "activationId", identity, "publicationId", response.publicationId().orElseThrow()));
            }
        }
        System.out.println(new Gson().toJson(Map.of("invocations", results)));
    }
}
