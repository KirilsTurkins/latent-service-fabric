package export_examples_go_standard_network_api

import (
	"encoding/json"

	smtp "github.com/emersion/go-smtp"
)

// The peer is a controlled local fixture. The published client constructs
// its ordinary connection and performs one submission without a retry loop.
func Run(which uint32, input string) string {
	if which > 1 {
		return "unsupported-fixture-mode"
	}
	var config struct{ Address string }
	if json.Unmarshal([]byte(input), &config) != nil || config.Address == "" {
		return "fixture-input-error"
	}
	client, err := smtp.Dial(config.Address)
	if err != nil {
		return "published-smtp-dial-error"
	}
	defer client.Close()
	if which == 1 {
		if client.Noop() != nil || client.Quit() != nil {
			return "published-smtp-fresh-error"
		}
		return "published-smtp-fresh"
	}
	if client.Mail("sender@example.invalid", nil) != nil ||
		client.Rcpt("recipient@example.invalid", nil) != nil {
		return "published-smtp-envelope-error"
	}
	data, err := client.Data()
	if err != nil {
		return "published-smtp-data-error"
	}
	message := []byte("Subject: controlled fixture\r\n\r\nOne controlled message.\r\n")
	if n, err := data.Write(message); err != nil || n != len(message) {
		return "published-smtp-body-error"
	}
	if data.Close() == nil {
		return "published-smtp-unexpected-ack"
	}
	// The caller sees an error after it has attempted submission. Only the
	// independent peer observation can say whether it accepted the message.
	return "published-smtp-delivery-unknown"
}
