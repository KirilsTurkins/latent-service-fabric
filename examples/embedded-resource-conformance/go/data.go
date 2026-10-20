package data

import (
    "bytes"
    "embed"
    "encoding/hex"
    "errors"
    "io"
    "io/fs"
)

//go:embed text.txt binary.bin empty.txt empty.bin
var resources embed.FS

func read(name string) []byte {
    value, err := resources.ReadFile(name)
    if err != nil { panic("declared embedded file unavailable") }
    return value
}

func Read(mode string) string {
    switch mode {
    case "text":
        value := read("text.txt")
        if string(value) != "Gr\u00fc\u00dfe\x00\u96ea\n" { panic("embedded text changed") }
        return "resource|text=" + string(value)
    case "binary":
        value := read("binary.bin")
        if !bytes.Equal(value, []byte{0,255,128,65,13,10}) { panic("embedded binary changed") }
        return "resource|binary=" + hex.EncodeToString(value)
    case "empty":
        if len(read("empty.txt")) != 0 || len(read("empty.bin")) != 0 { panic("empty asset changed") }
        file, err := resources.Open("empty.bin")
        if err != nil { panic("empty asset missing") }
        var buffer [1]byte
        n, readErr := file.Read(buffer[:])
        if n != 0 || readErr != io.EOF || file.Close() != nil { panic("empty stream semantics changed") }
        return "resource|empty=0+0|eof=1"
    case "missing":
        file, err := resources.Open("absent.bin")
        if file != nil || !errors.Is(err, fs.ErrNotExist) { panic("missing resource category changed") }
        return "resource|missing=not-exist"
    case "independent":
        first, err := resources.Open("binary.bin")
        if err != nil { panic("first embedded stream missing") }
        second, err := resources.Open("binary.bin")
        if err != nil { panic("second embedded stream missing") }
        var a, b [2]byte
        na, ea := io.ReadFull(first,a[:]); nb, eb := io.ReadFull(second,b[:])
        if na != 2 || nb != 2 || ea != nil || eb != nil || !bytes.Equal(a[:],b[:]) || first.Close() != nil { panic("embedded positions changed") }
        n, err := io.ReadFull(second,b[:])
        if n != 2 || err != nil || b != [2]byte{128,65} || second.Close() != nil { panic("other stream closed or moved") }
        return "resource|independent=2,2|close=other-readable"
    case "copies":
        first, second := read("binary.bin"), read("binary.bin")
        first[0] = 42
        if second[0] != 0 || read("binary.bin")[0] != 0 { panic("ReadFile returned shared mutable storage") }
        return "resource|copies=independent"
    case "trap":
        _ = read("binary.bin")
        panic("requested resource trap")
    default: panic("unknown fixed resource case")
    }
}
