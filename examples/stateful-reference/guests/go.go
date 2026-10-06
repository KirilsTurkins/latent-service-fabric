// lsf-example-begin: order-draft
package export_examples_order_draft_api

import (
    "bytes"
    "encoding/binary"
    wit "go.bytecodealliance.org/pkg/wit/types"
    api "wit_component/examples_order_draft_api"
    "wit_component/lsf/state"
    "wit_component/lsf/intents"
)

const media = "application/vnd.lsf.order-draft-v1"
func keys(id string) ([]byte, []byte, bool) {
    if len(id) == 0 || len(id) > 32 { return nil, nil, false }
    for i, c := range []byte(id) {
        if !(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && !(i > 0 && c == '-') {
            return nil, nil, false
        }
    }
    return []byte("drafts/" + id + "/draft"), []byte("drafts/" + id + "/summary"), true
}
func decode(primary, summary wit.Option[state.VersionedValue]) (uint64, uint32, bool) {
    if !primary.IsSome() && !summary.IsSome() { return 0, 0, true }
    if !primary.IsSome() || !summary.IsSome() { return 0, 0, false }
    a, b := primary.Some().Value, summary.Some().Value
    for _, value := range []state.Value{a, b} {
        if value.MediaType != media || len(value.Metadata) != 0 || len(value.Bytes) != 12 { return 0, 0, false }
    }
    if !bytes.Equal(a.Bytes, b.Bytes) { return 0, 0, false }
    revision, units := binary.LittleEndian.Uint64(a.Bytes), binary.LittleEndian.Uint32(a.Bytes[8:])
    return revision, units, revision != 0 && units <= 10000
}
func version(value wit.Option[state.VersionedValue]) wit.Option[[]byte] {
    if value.IsSome() { return wit.Some(value.Some().Version) }
    return wit.None[[]byte]()
}
func Edit(request api.EditRequest) wit.Result[api.Draft, api.BusinessError] {
    a, b, valid := keys(request.DraftId)
    if !valid { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorInvalidDraft) }
    if request.Units > 10000 { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorInvalidUnits) }
    command := state.AcquireCommand().Ok(); defer command.Close()
    if command.Info().Ok().View.Namespace != "order-drafts-" + request.DraftId {
        return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorInvalidDraft)
    }
    primary := command.Get(a).Ok()
    previous, _, valid := decode(primary, command.Get(b).Ok())
    if !valid { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorMalformedState) }
    if previous != request.ExpectedRevision { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorStaleEdit) }
    if previous == ^uint64(0) { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorRevisionOverflow) }
    revision := previous + 1
    valueBytes := make([]byte, 12)
    binary.LittleEndian.PutUint64(valueBytes, revision)
    binary.LittleEndian.PutUint32(valueBytes[8:], request.Units)
    value := state.Value{Bytes: valueBytes, MediaType: media, Metadata: nil}
    command.Put(a, value).Ok(); command.Put(b, value).Ok()
    event := append([]byte("draft-change-v1:"), []byte(request.DraftId)...)
    payload := state.Value{Bytes: event, MediaType: "application/octet-stream", Metadata: nil}
    intents.New("draft-change", "event", payload).Stage(command).Ok()
    intents.New("draft-http", "put-once", payload).Stage(command).Ok()
    if request.Reject { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorRejected) }
    return wit.Ok[api.Draft, api.BusinessError](api.Draft{DraftId: request.DraftId, Revision: revision, Units: request.Units,
        NamespaceView: command.Info().Ok().View.Version, KeyVersion: version(primary)})
}
func Query(id string) wit.Result[api.Draft, api.BusinessError] {
    a, b, valid := keys(id)
    if !valid { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorInvalidDraft) }
    query := state.AcquireQuery().Ok(); defer query.Close()
    if query.Info().Ok().Namespace != "order-drafts-" + id {
        return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorInvalidDraft)
    }
    primary := query.Get(a).Ok()
    revision, units, valid := decode(primary, query.Get(b).Ok())
    if !valid { return wit.Err[api.Draft, api.BusinessError](api.BusinessErrorMalformedState) }
    return wit.Ok[api.Draft, api.BusinessError](api.Draft{DraftId: id, Revision: revision, Units: units,
        NamespaceView: query.Info().Ok().Version, KeyVersion: version(primary)})
}
// lsf-example-end: order-draft
