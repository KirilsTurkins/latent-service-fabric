package main

import (
	"go/parser"
	"go/token"
	"strings"
	"testing"

	"google.golang.org/protobuf/compiler/protogen"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/pluginpb"
)

func fixturePlugin(test *testing.T, clientStreaming, serverStreaming bool) *protogen.Plugin {
	test.Helper()
	request := &pluginpb.CodeGeneratorRequest{
		FileToGenerate: []string{"fixture.proto"}, Parameter: proto.String("module=latent.dev/sdk/go"),
		ProtoFile: []*descriptorpb.FileDescriptorProto{{
			Name: proto.String("fixture.proto"), Package: proto.String("fixture.v1"), Syntax: proto.String("proto3"),
			Options:     &descriptorpb.FileOptions{GoPackage: proto.String("latent.dev/sdk/go/internal/rpc/fixturev1")},
			MessageType: []*descriptorpb.DescriptorProto{{Name: proto.String("Request")}, {Name: proto.String("Response")}},
			Service: []*descriptorpb.ServiceDescriptorProto{{Name: proto.String("ProfileService"),
				Method: []*descriptorpb.MethodDescriptorProto{{Name: proto.String("Execute"),
					InputType: proto.String(".fixture.v1.Request"), OutputType: proto.String(".fixture.v1.Response"),
					ClientStreaming: proto.Bool(clientStreaming), ServerStreaming: proto.Bool(serverStreaming)}}}},
		}},
	}
	plugin, failure := (protogen.Options{}).New(request)
	if failure != nil {
		test.Fatal(failure)
	}
	return plugin
}

func TestPrivateUnaryBindingsFollowAuthoritativeDescriptors(test *testing.T) {
	plugin := fixturePlugin(test, false, false)
	if failure := generate(plugin); failure != nil {
		test.Fatal(failure)
	}
	response := plugin.Response()
	if response.GetError() != "" || len(response.File) != 1 || response.GetSupportedFeatures() != 1 {
		test.Fatal("generation lost optional presence or produced unexpected files")
	}
	source := response.File[0].GetContent()
	for _, expected := range []string{"/fixture.v1.ProfileService/Execute", "type ProfileServiceClient interface",
		"func NewProfileServiceClient", "request *Request", "response := new(Response)", "client.connection.Invoke(ctx,"} {
		if !strings.Contains(source, expected) {
			test.Fatalf("generated unary binding lacks %q", expected)
		}
	}
	if strings.Contains(source, "google.golang.org/grpc") || strings.Contains(source, "Retry") {
		test.Fatal("private unary glue acquired an external transport or replay behavior")
	}
	if _, failure := parser.ParseFile(token.NewFileSet(), "fixture_rpc.pb.go", source, parser.AllErrors); failure != nil {
		test.Fatal(failure)
	}
}

func TestStreamingDescriptorsAreRejected(test *testing.T) {
	for _, flags := range [][2]bool{{true, false}, {false, true}, {true, true}} {
		if failure := generate(fixturePlugin(test, flags[0], flags[1])); failure == nil {
			test.Fatal("streaming descriptor entered the unary-only generator")
		}
	}
}
