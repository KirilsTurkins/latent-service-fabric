package export_tests_go_http_context_api

import (
	"context"
	"encoding/json"
	"sync"
	"time"
	stream "wit_component/lsf/streaming"
	wit "go.bytecodealliance.org/pkg/wit/types"
)

// This fixture exercises the typed SDK prerequisite. It is not net/http.
func Run(which uint32, url string) string {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if which == 0 { cancel() }
	if which == 4 {
		deadline, stop := context.WithTimeout(ctx, 20*time.Millisecond)
		defer stop()
		ctx = deadline
	}
	var sibling sync.WaitGroup
	progressed := make(chan struct{})
	if which == 2 {
		sibling.Add(1)
		go func() {
			defer sibling.Done()
			time.Sleep(20*time.Millisecond)
			close(progressed)
			cancel()
		}()
	}
	defer sibling.Wait()
	uploadResult := stream.OpenContext(ctx, stream.Request{Method: stream.MethodGet, Url: url,
		Headers: []stream.Header{}, BodyLength: wit.Some[uint64](0),
		BodyMediaType: wit.None[string](), IdempotencyKey: wit.None[string](),
		TimeoutMillis: wit.None[uint64]()})
	if uploadResult.IsErr() { return failure(ctx) }
	upload := uploadResult.Ok()
	defer upload.Close()
	if written := upload.WriteContext(ctx, []byte{}); written.IsErr() { return failure(ctx) }
	responseResult := upload.FinishContext(ctx)
	if responseResult.IsErr() {
		if which == 2 { <-progressed }
		return failure(ctx)
	}
	response := responseResult.Ok()
	defer response.Body.Close()
	var bytes []byte
	for {
		read := response.Body.ReadContext(ctx, 4096)
		if read.IsErr() { return failure(ctx) }
		if read.Ok().IsNone() { break }
		chunk := read.Ok().Some()
		value := chunk.BytesContext(ctx)
		chunk.Close()
		if value.IsErr() { return failure(ctx) }
		bytes = append(bytes, value.Ok()...)
		if len(bytes) > 32768 { return "too-large" }
		if which == 3 { cancel() }
	}
	if trailers := response.Body.TrailersContext(ctx); trailers.IsErr() { return failure(ctx) }
	var value struct { ID int `json:"id"`; Name string `json:"name"` }
	if json.Unmarshal(bytes, &value) != nil { return "invalid-json" }
	if response.Status != 200 { return "status-error" }
	if value.ID != 7 || value.Name != "café" { return "domain-error" }
	return "ok"
}

func failure(ctx context.Context) string {
	if ctx.Err() != nil { return "cancelled" }
	return "transport-error"
}
