package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import dev.latent.guest.Text;

// lsf-example-begin: capsule
public final class Capsule implements Bindings.Exports {
    public Result<Long, String> count(String text) {
        if (Text.utf8Length(text) > 4096) return Result.err("Use text of at most 4096 bytes.");
        long count = 0;
        boolean inside = false;
        for (int offset = 0; offset < text.length();) {
            int character = text.codePointAt(offset);
            boolean word = !Text.whitespace(character);
            if (word && !inside) count++;
            inside = word;
            offset += Character.charCount(character);
        }
        return Result.ok(count);
    }
}
// lsf-example-end: capsule
