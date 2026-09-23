package export_tests_streaming_http_api

import (
	http "wit_component/lsf/streaming"
	wit "go.bytecodealliance.org/pkg/wit/types"
)

func Run(which uint32, url string, _ uint64) uint64 {
	r := http.Open(http.Request{Method: http.MethodPost, Url: url, Headers: []http.Header{},
		BodyLength: wit.Some[uint64](4), BodyMediaType: wit.Some("text/plain"),
		IdempotencyKey: wit.None[string](), TimeoutMillis: wit.Some[uint64](1000)})
	if r.IsErr() {
		if r.Err().Tag() == http.HttpErrorPermissionDenied { return 10 }
		panic("unexpected streaming open error")
	}
	upload := r.Ok(); defer upload.Close()
	if which == 1 { return 1 }
	if upload.Write([]byte("data")).IsErr() { panic("streaming write failed") }
	response := upload.Finish().Ok()
	defer response.Body.Close()
	if which == 2 { return 2 }
	if which == 3 {
		chunk := response.Body.Read(4).Ok().Some()
		defer chunk.Close()
		response.Body.Close()
		return uint64(len(chunk.Bytes().Ok()))
	}
	var count uint64
	for {
		next := response.Body.Read(4).Ok()
		if next.IsNone() { break }
		count += uint64(len(next.Some().Bytes().Ok()))
	}
	response.Body.Trailers().Ok()
	if response.Body.Trailers().Err().Tag() != http.HttpErrorInvalidState { panic("repeated trailers accepted") }
	return count
}
