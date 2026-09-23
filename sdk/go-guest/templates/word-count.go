// lsf-example-begin: capsule
package export_examples_word_count_api

import (
    "strings"
    wit "go.bytecodealliance.org/pkg/wit/types"
)

func Count(text string) wit.Result[uint32, string] {
    if len(text) > 4096 { return wit.Err[uint32, string]("Use text of at most 4096 bytes.") }
    return wit.Ok[uint32, string](uint32(len(strings.Fields(text))))
}
// lsf-example-end: capsule
