// lsf-example-begin: capsule
package export_examples_transactional_aggregate_api

import (
    "encoding/binary"
    wit "go.bytecodealliance.org/pkg/wit/types"
    "wit_component/lsf/state"
    "wit_component/lsf/intents"
)

var key = []byte("aggregate/count")
const media = "application/vnd.lsf.aggregate-v1"
func count(value wit.Option[state.VersionedValue]) (uint64, bool) {
    if !value.IsSome() { return 0, true }
    payload := value.Some().Value
    if payload.MediaType != media || len(payload.Metadata) != 0 || len(payload.Bytes) != 8 { return 0, false }
    return binary.LittleEndian.Uint64(payload.Bytes), true
}
func Update(request UpdateRequest) wit.Result[Aggregate, BusinessError] {
    command := state.AcquireCommand().Ok(); defer command.Close()
    old, valid := count(command.Get(key).Ok())
    if !valid { return wit.Err[Aggregate, BusinessError](BusinessErrorMalformedState) }
    next := old + uint64(request.Delta)
    if next < old { return wit.Err[Aggregate, BusinessError](BusinessErrorOverflow) }
    bytes := make([]byte, 8); binary.LittleEndian.PutUint64(bytes, next)
    payload := state.Value{Bytes: bytes, MediaType: media, Metadata: nil}
    command.Put(key, payload).Ok()
    intents.New("approved-event", "event", payload).Stage(command).Ok()
    if request.Reject { return wit.Err[Aggregate, BusinessError](BusinessErrorRejected) }
    staged := command.Get(key).Ok().Some()
    return wit.Ok[Aggregate, BusinessError](Aggregate{Count: next, Version: staged.Version})
}
func Query() wit.Result[Aggregate, BusinessError] {
    query := state.AcquireQuery().Ok(); defer query.Close()
    count, valid := count(query.Get(key).Ok())
    if !valid { return wit.Err[Aggregate, BusinessError](BusinessErrorMalformedState) }
    return wit.Ok[Aggregate, BusinessError](Aggregate{Count: count, Version: query.Info().Ok().Version})
}
func Scan(prefix []byte, limit uint32, cursor wit.Option[[]byte]) wit.Result[ScanResult, BusinessError] {
    query := state.AcquireQuery().Ok(); defer query.Close()
    page := query.Scan(prefix, limit, cursor).Ok(); defer page.Close()
    info := page.Info().Ok(); var count uint32
    for page.Next().Ok().IsSome() { count++ }
    if count != info.EntryCount { panic("page count mismatch") }
    return wit.Ok[ScanResult, BusinessError](ScanResult{Count: count, EncodedBytes: info.EncodedBytes,
        ViewVersion: info.View.Version, NextCursor: info.NextCursor})
}
// lsf-example-end: capsule
