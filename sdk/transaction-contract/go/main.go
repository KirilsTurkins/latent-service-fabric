package export_tests_transaction_contract_api

import (
    wit "go.bytecodealliance.org/pkg/wit/types"
    state "wit_component/latent_state_key_value"
    intents "wit_component/latent_intents_staging"
)

// The maintained compiler suspends stackful calls; no independent event loop.
func Run(mode uint32) uint64 {
    if mode == 0 {
        view := state.AcquireQuery().Ok()
        defer view.Drop()
        identity := state.QueryInfo(view).Ok()
        value := state.GetQuery(view, []byte("k")).Ok()
        page := state.ScanQuery(view, []byte{}, 1, wit.None[[]byte]()).Ok()
        defer page.Drop()
        bounds := state.DescribePage(page).Ok()
        item := state.PageNext(page).Ok()
        count := uint64(len(identity.Version)) + uint64(bounds.EntryCount)
        if value.IsSome() { count++ }
        if item.IsSome() { count++ }
        return count
    }
    transaction := state.AcquireCommand().Ok()
    defer transaction.Drop()
    identity := state.Info(transaction).Ok()
    existing := state.Get(transaction, []byte("k")).Ok()
    payload := state.Value{Bytes: []byte{}, MediaType: "application/octet-stream", Metadata: nil}
    state.Put(transaction, []byte("k"), payload).Ok()
    state.Delete(transaction, []byte("k")).Ok()
    page := state.Scan(transaction, []byte{}, 1, wit.None[[]byte]()).Ok()
    defer page.Drop()
    bounds := state.DescribePage(page).Ok()
    item := state.PageNext(page).Ok()
    staged := intents.Stage(transaction, intents.Intent{Binding: "approved-mail", Operation: "send",
        Payload: payload, ExpiresAtUnixMillis: wit.Some[uint64](^uint64(0))}).Ok()
    count := uint64(staged.Sequence) + uint64(bounds.EntryCount) + uint64(len(identity.CommandId))
    if existing.IsSome() { count++ }
    if item.IsSome() { count++ }
    return count
}
