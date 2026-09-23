// lsf-example-begin: capsule
package export_examples_greeting_api

import (
    "strings"
    wit "go.bytecodealliance.org/pkg/wit/types"
)

func Greet(name string) wit.Result[string, string] {
    name = strings.TrimSpace(name)
    if len(name) == 0 { return wit.Err[string, string]("Please enter a name.") }
    if len(name) > 100 { return wit.Err[string, string]("Use a name of at most 100 bytes.") }
    return wit.Ok[string, string]("Hello, " + name + "!")
}
// lsf-example-end: capsule
