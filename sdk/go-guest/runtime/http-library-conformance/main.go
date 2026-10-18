package export_examples_go_standard_http_api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/carlmjohnson/requests"
	"github.com/dghubble/sling"
	private "@private-module@"
)

type domain struct {
	ID int `json:"id"`
	Name string `json:"name"`
	Items []string `json:"items"`
	Empty string `json:"empty"`
	Status int `json:"status"`
	Message string `json:"message"`
	Body string `json:"bodyBase64"`
	Method string `json:"method"`
}

var invocations uint32

func Run(which uint32, address string) string {
	invocations++
	if invocations != 1 { return "stale-state" }
	if private.Marker() != "captured-private-worker" { return "private-worker-error" }
	library, mode := which/100, which%100
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if mode == 4 { var expire context.CancelFunc; ctx, expire = context.WithTimeout(ctx,20*time.Millisecond); defer expire() }
	if mode == 6 { cancel() }
	if mode == 7 || mode == 5 && library == 0 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	var value domain
	var err error
	status := 0
	if library == 0 {
		client := sling.New().Get(address)
		if mode == 1 { client = client.Post(address).Body(bytes.NewReader([]byte{0,1,2,3})).Set("Content-Type","application/octet-stream") }
		if mode == 3 { client = client.Set("Authorization","must-not-leave-guest") }
		request, requestErr := client.Request()
		if requestErr != nil { return "request-error" }
		var response *http.Response
		response, err = client.Do(request.WithContext(ctx),&value,&value)
		if response != nil { status = response.StatusCode }
	} else if library == 1 {
		client := requests.URL(address).AddValidator(func(response *http.Response) error {
			status = response.StatusCode
			if mode == 5 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
			return nil
		}).ToJSON(&value)
		if mode == 1 { client = client.BodyBytes([]byte{0,1,2,3}).ContentType("application/octet-stream") }
		if mode == 3 { client = client.Header("Authorization","must-not-leave-guest") }
		err = client.Fetch(ctx)
	} else { return "unknown-library" }
	if err != nil {
		if ctx.Err() != nil { return "cancelled" }
		var syntax *json.SyntaxError
		var incompatible *json.UnmarshalTypeError
		if errors.As(err,&syntax) || errors.As(err,&incompatible) { return "invalid-json" }
		if errors.Is(err,io.ErrUnexpectedEOF) { return "transport-error" }
		return "transport-error"
	}
	if mode == 1 {
		if value.Method != "POST" { return "invalid-json" }
		return strconv.Itoa(status)+":echo:"+value.Body
	}
	if status >= 400 {
		if value.Status != status { return "invalid-json" }
		return strconv.Itoa(status)+":error:"+value.Message
	}
	if value.ID != 7 || len(value.Items) != 2 || value.Empty != "" { return "invalid-domain" }
	return strconv.Itoa(status)+":domain:"+strconv.Itoa(value.ID)+":"+value.Name+":"+value.Items[0]+"|"+value.Items[1]
}
