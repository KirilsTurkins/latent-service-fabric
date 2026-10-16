package export_tests_go_standard_http_api

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"time"
)

type domain struct {
	ID int `json:"id"`
	Name string `json:"name"`
	Items []string `json:"items"`
	Empty string `json:"empty"`
}

type localTransport struct{}
func (localTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return &http.Response{StatusCode:200, Header:make(http.Header),
		Body:io.NopCloser(bytes.NewBufferString(`{"id":7,"name":"café","items":["λ",""],"empty":""}`)), Request:request}, nil
}

func Run(which uint32, address string) string {
	client := &http.Client{Timeout:time.Second}
	defer client.CloseIdleConnections()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	method := http.MethodGet
	var body io.Reader
	if which == 1 { method = http.MethodPost; body = bytes.NewReader([]byte{0,1,2,3}) }
	request, err := http.NewRequestWithContext(ctx, method, address, body)
	if err != nil { return "request-error" }
	if which == 1 { request.Header.Set("Content-Type", "application/octet-stream") }
	if which == 3 { request.Header.Set("Authorization", "must-not-leave-guest") }
	if which == 4 { var timeout context.CancelFunc; ctx, timeout = context.WithTimeout(ctx, 20*time.Millisecond); defer timeout(); request = request.WithContext(ctx) }
	if which == 6 { cancel() }
	if which == 7 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	if which == 8 { client.Transport = &http.Transport{DisableCompression:true} }
	if which == 9 { client.Transport = http.DefaultTransport.(*http.Transport).Clone() }
	if which == 10 { client.Transport = localTransport{} }
	response, err := client.Do(request)
	if err != nil { if ctx.Err() != nil { return "cancelled" }; return "transport-error" }
	defer response.Body.Close()
	if which == 2 { first := make([]byte,4); count, _ := response.Body.Read(first); return "early:"+strconv.Itoa(count) }
	if which == 5 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	if which == 1 {
		var echo struct { Body string `json:"bodyBase64"`; Method string `json:"method"` }
		if json.NewDecoder(response.Body).Decode(&echo) != nil || echo.Method != "POST" { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":echo:"+echo.Body
	}
	if response.StatusCode >= 400 {
		var failure struct { Status int `json:"status"`; Message string `json:"message"` }
		if json.NewDecoder(response.Body).Decode(&failure) != nil || failure.Status != response.StatusCode { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":error:"+failure.Message
	}
	var value domain
	if err := json.NewDecoder(response.Body).Decode(&value); err != nil {
		if ctx.Err() != nil { return "cancelled" }; return "invalid-json"
	}
	if value.ID != 7 || len(value.Items) != 2 || value.Empty != "" { return "invalid-domain" }
	return strconv.Itoa(response.StatusCode)+":domain:"+strconv.Itoa(value.ID)+":"+value.Name+":"+value.Items[0]+"|"+value.Items[1]
}
