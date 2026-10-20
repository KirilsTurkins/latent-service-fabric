package outside.resources;

import outside.resourcechild.Data;

public final class Library {
    private Library() {}

    public static String read(String mode) {
        return "resource|" + Data.read(mode);
    }
}
