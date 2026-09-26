package export_tests_http_api

import (
	wit "go.bytecodealliance.org/pkg/wit/types"
	http "wit_component/lsf/http"
)

func Run(which uint32, url string, _ uint64) uint64 {
	method := http.MethodPost
	if which == 0 {
		method = http.MethodGet
	}
	if which == 1 {
		method = http.MethodHead
	}
	r := http.Send(http.Request{Method: method, Url: url, Headers: []http.Header{},
		Body: wit.Some([]byte("payload")), BodyMediaType: wit.Some("text/plain"),
		IdempotencyKey: wit.None[string](), TimeoutMillis: wit.Some[uint64](1000)})
	if r.IsOk() {
		return uint64(r.Ok().Status) + 1000*uint64(len(r.Ok().Body))
	}
	switch r.Err().Tag() {
	case http.HttpErrorPermissionDenied:
		return 10
	case http.HttpErrorUncertain:
		return 11
	default:
		panic("unexpected HTTP outcome")
	}
}
