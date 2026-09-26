package transport

import (
	"net"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"time"

	"latent.dev/sdk/go/profile"
)

type Config struct {
	Endpoint         string
	BearerToken      string
	ConnectTimeout   time.Duration
	DefaultTimeout   time.Duration
	MaxInFlight      int
	ReservedRecovery int
	MaxQueued        int
	MaxRequestBytes  int
	MaxResponseBytes int
	MaxHeaderBytes   uint32
	MaxGraphBytes    int
	MaxGraphNodes    int
}

func (Config) String() string   { return "latent Go transport configuration (redacted)" }
func (Config) GoString() string { return "transport.Config{redacted}" }

func DefaultConfig(endpoint, bearerToken string) Config {
	return Config{
		Endpoint: endpoint, BearerToken: bearerToken,
		ConnectTimeout: 2 * time.Second, DefaultTimeout: 5 * time.Second,
		MaxInFlight: 8, ReservedRecovery: 2, MaxQueued: 8,
		MaxRequestBytes: 1024 * 1024, MaxResponseBytes: 1024 * 1024,
		MaxHeaderBytes: 16 * 1024, MaxGraphBytes: 8 * 1024 * 1024, MaxGraphNodes: 8192,
	}
}

func (config Config) validate() (*url.URL, error) {
	endpoint, failure := url.Parse(config.Endpoint)
	if failure != nil || endpoint.Scheme != "http" || endpoint.User != nil ||
		endpoint.Path != "" || endpoint.RawPath != "" || endpoint.RawQuery != "" ||
		endpoint.ForceQuery || endpoint.Fragment != "" || endpoint.Opaque != "" {
		return nil, invalidConfig()
	}
	address, failure := netip.ParseAddr(endpoint.Hostname())
	port, portFailure := strconv.ParseUint(endpoint.Port(), 10, 16)
	if failure != nil || !address.IsLoopback() || address.Zone() != "" || portFailure != nil || port == 0 ||
		endpoint.Host != net.JoinHostPort(address.String(), strconv.FormatUint(port, 10)) {
		return nil, invalidConfig()
	}
	if len(config.BearerToken) == 0 || len(config.BearerToken) > 512 ||
		strings.IndexFunc(config.BearerToken, func(value rune) bool { return value < 33 || value > 126 }) >= 0 {
		return nil, invalidConfig()
	}
	if config.ConnectTimeout <= 0 || config.ConnectTimeout > 30*time.Second ||
		config.DefaultTimeout <= 0 || config.DefaultTimeout > 30*time.Second ||
		config.MaxInFlight < 2 || config.MaxInFlight > 32 ||
		config.ReservedRecovery < 1 || config.ReservedRecovery >= config.MaxInFlight ||
		config.MaxQueued < 0 || config.MaxQueued > 64 ||
		config.MaxRequestBytes < 1 || config.MaxRequestBytes > 4*1024*1024 ||
		config.MaxResponseBytes < 1 || config.MaxResponseBytes > 4*1024*1024 ||
		config.MaxHeaderBytes < 1024 || config.MaxHeaderBytes > 32*1024 ||
		config.MaxGraphBytes < 1024 || config.MaxGraphBytes > 32*1024*1024 ||
		config.MaxGraphNodes < 32 || config.MaxGraphNodes > 16384 {
		return nil, invalidConfig()
	}
	return endpoint, nil
}

func invalidConfig() error {
	return localFailure(profile.FailureCategoryInvalidRequest, "invalid bounded loopback client configuration")
}

func localFailure(category profile.FailureCategory, message string) *profile.ClientFailure {
	return &profile.ClientFailure{Category: category, Message: message, Outcome: profile.OutcomeKnowledgeNotDispatched}
}
