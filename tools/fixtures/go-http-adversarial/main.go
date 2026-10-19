package export_examples_go_standard_http_api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
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
var invocations uint32
func (localTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return &http.Response{StatusCode:200, Header:make(http.Header),
		Body:io.NopCloser(bytes.NewBufferString(`{"id":7,"name":"cafÃƒÂ©","items":["ÃŽÂ»",""],"empty":""}`)), Request:request}, nil
}

func Run(which uint32, address string) string {
	invocations++
	if invocations != 1 { return "stale-state" }
	if which == 25 { return "entered" }
	client := &http.Client{Timeout:time.Second}
	defer client.CloseIdleConnections()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	method := http.MethodGet
	var body io.Reader
	if which == 1 { method = http.MethodPost; body = bytes.NewReader([]byte{0,1,2,3}) }
	request, err := http.NewRequestWithContext(ctx, method, address, body)
	if err != nil { return "request-error" }
	if which == 26 { return "request-ready" }
	if which == 1 { request.Header.Set("Content-Type", "application/octet-stream") }
	if which == 3 { request.Header.Set("Authorization", "must-not-leave-guest") }
	if which == 4 { var timeout context.CancelFunc; ctx, timeout = context.WithTimeout(ctx, 20*time.Millisecond); defer timeout(); request = request.WithContext(ctx) }
	if which == 6 { cancel() }
	if which == 7 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	if which == 8 { client.Transport = &http.Transport{DisableCompression:true} }
	if which == 9 { client.Transport = http.DefaultTransport.(*http.Transport).Clone() }
	if which == 10 { client.Transport = localTransport{} }
	dialed := false
	if which == 11 { client.Transport = &http.Transport{DisableCompression:true,
		DialContext:func(context.Context,string,string)(net.Conn,error){ dialed = true; return nil,errors.New("custom dialer invoked") }} }
	if which == 12 { client.Transport = &http.Transport{DisableCompression:true,DisableKeepAlives:true} }
	if which == 13 { client.Transport = &http.Transport{DisableCompression:true,MaxResponseHeaderBytes:-1} }
	if which == 14 { request.Close = true }
	if which == 15 { request.ContentLength = -2 }
	if which == 16 { request.ContentLength = 1 }
	if which == 17 { client.Transport = &http.Transport{DisableCompression:true,ResponseHeaderTimeout:time.Millisecond} }
	if which == 18 { client.Transport = &http.Transport{DisableCompression:true,MaxResponseHeaderBytes:1024} }
	if which == 19 { client.Transport = &http.Transport{DisableCompression:true,ReadBufferSize:4} }
	if which == 20 { client.Transport = &http.Transport{DisableCompression:true,WriteBufferSize:4} }
	if which == 22 { request.Header.Set("User-Agent", "") }
	if which == 23 { request.Header["User-Agent"] = []string{" fixture-agent/1 ", "must-not-be-sent"} }
	if which == 24 { request.Header["user-agent"] = []string{"noncanonical-field"} }
	if which == 28 { client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse } }
	if which == 29 {
		jar, jarErr := cookiejar.New(nil)
		if jarErr != nil { return "cookie-jar-error" }
		jar.SetCookies(request.URL, []*http.Cookie{{Name:"must-not-leave-guest",Value:"forbidden"}})
		client.Jar = jar
	}
	proxied := false
	if which == 30 { client.Transport = &http.Transport{DisableCompression:true,
		Proxy:func(*http.Request)(*url.URL,error){ proxied = true; return &url.URL{Scheme:"http",Host:"unavailable.invalid:3128"},nil }} }
	if which == 31 {
		for i := 0; i < 2; i++ {
			response, readErr := client.Do(request.Clone(ctx))
			if readErr != nil { return "transport-error" }
			data, readErr := io.ReadAll(response.Body)
			closeErr := response.Body.Close()
			var value domain
			if readErr != nil || closeErr != nil || response.StatusCode != 200 || json.Unmarshal(data,&value) != nil || value.ID != 7 { return "repeat-error" }
		}
		return "200:twice"
	}
	if which == 32 || which == 33 {
		ready := make(chan error,1)
		go func(){
			response, openErr := client.Do(request)
			if openErr != nil { ready <- openErr; return }
			defer response.Body.Close()
			ready <- nil
			_, _ = io.ReadAll(response.Body)
		}()
		if <-ready != nil { return "pending-open-error" }
		if which == 33 { panic("root-with-pending-http-body") }
		return "root-returned-with-pending-body"
	}
	response, err := client.Do(request)
	if which == 30 {
		if err == nil { response.Body.Close(); return "proxy-destination-accepted" }
		var wrapped *url.Error
		if proxied && errors.As(err,&wrapped) && wrapped.Err.Error() == "lsf net/http profile does not support HTTP proxy" { return "proxy-destination-denied" }
		return "unexpected-proxy-error"
	}
	if which == 11 { if dialed { return "custom-dialer-invoked" }; if err == nil { response.Body.Close(); return "custom-dialer-accepted" }; return "custom-dialer-denied" }
	if err != nil { if ctx.Err() != nil { return "cancelled" }; return "transport-error" }
	defer response.Body.Close()
	if which == 28 { return strconv.Itoa(response.StatusCode)+":redirect-stopped" }
	if which == 2 { first := make([]byte,4); count, _ := io.ReadFull(response.Body, first); return "early:"+strconv.Itoa(count) }
	if which == 5 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	data, err := io.ReadAll(response.Body)
	if err != nil { if ctx.Err() != nil { return "cancelled" }; return "transport-error" }
	if which == 27 {
		var redirect struct { Redirected bool `json:"redirected"` }
		if response.StatusCode != 200 || json.Unmarshal(data,&redirect) != nil || !redirect.Redirected { return "invalid-redirect" }
		return "200:redirected"
	}
	if which == 1 {
		var echo struct { Body string `json:"bodyBase64"`; Method string `json:"method"` }
		if json.Unmarshal(data, &echo) != nil || echo.Method != "POST" { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":echo:"+echo.Body
	}
	if response.StatusCode >= 400 {
		var failure struct { Status int `json:"status"`; Message string `json:"message"` }
		if json.Unmarshal(data, &failure) != nil || failure.Status != response.StatusCode { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":error:"+failure.Message
	}
	var value domain
	if err := json.Unmarshal(data, &value); err != nil {
		if ctx.Err() != nil { return "cancelled" }; return "invalid-json"
	}
	if value.ID != 7 || len(value.Items) != 2 || value.Empty != "" { return "invalid-domain" }
	return strconv.Itoa(response.StatusCode)+":domain:"+strconv.Itoa(value.ID)+":"+value.Name+":"+value.Items[0]+"|"+value.Items[1]
}
