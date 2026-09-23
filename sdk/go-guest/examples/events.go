package export_tests_nats_events_api

import (
	wit "go.bytecodealliance.org/pkg/wit/types"
	"strconv"
	events "wit_component/lsf/events"
)

func Run(_ uint32, topic string, handle uint64) uint64 {
	r := events.Publish(events.Event{Topic: topic, Key: wit.None[string](), Payload: []byte("payload"),
		MediaType: "text/plain", Attributes: []wit.Tuple2[string, string]{},
		IdempotencyKey: "guest-sdk-" + strconv.FormatUint(handle, 10)})
	if r.IsOk() {
		value := r.Ok()
		if value.EventId == "" || value.StreamName == "" {
			panic("incomplete publication receipt")
		}
		return value.Sequence
	}
	switch r.Err().Tag() {
	case events.EventErrorPermissionDenied:
		return 10
	case events.EventErrorUncertain:
		return 11 // preserve uncertainty; never retry
	default:
		panic("unexpected event outcome")
	}
}
