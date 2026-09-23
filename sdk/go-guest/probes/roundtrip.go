// SPDX-License-Identifier: Apache-2.0
package export_lsf_go_probe_probe

import (
    "runtime"
    "strings"
    witTypes "go.bytecodealliance.org/pkg/wit/types"
    "wit_component/lsf_go_probe_probe"
)

var calls uint32

// Check is real compiled application code, not the generator's panic stub.
// A second call in one instance exposes unintended persistent guest state.
func Check(input lsf_go_probe_probe.Payload) witTypes.Result[lsf_go_probe_probe.Payload, string] {
    calls++
    if calls != 1 || input.Text == "panic" { panic("probe trap") }
    if strings.TrimSpace(input.Text) == "" {
        return witTypes.Err[lsf_go_probe_probe.Payload, string]("Please enter text.")
    }
    if len(input.Text) > 4096 || len(input.Bytes) > 1024 {
        return witTypes.Err[lsf_go_probe_probe.Payload, string]("Input exceeds the probe bound.")
    }
    runtime.GC()
    return witTypes.Ok[lsf_go_probe_probe.Payload, string](input)
}
