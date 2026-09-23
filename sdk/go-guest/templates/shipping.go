// lsf-example-begin: capsule
package export_examples_shipping_api

import wit "go.bytecodealliance.org/pkg/wit/types"

func Quote(items uint32, express bool) wit.Result[uint32, string] {
    if items < 1 || items > 100 { return wit.Err[uint32, string]("Choose between 1 and 100 items.") }
    base := uint32(500)
    if express { base = 1200 }
    return wit.Ok[uint32, string](base + items * 75)
}
// lsf-example-end: capsule
