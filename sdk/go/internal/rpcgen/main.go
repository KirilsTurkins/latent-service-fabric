package main

import (
	"fmt"
	"strings"

	"google.golang.org/protobuf/compiler/protogen"
	"google.golang.org/protobuf/types/pluginpb"
)

func main() {
	protogen.Options{}.Run(generate)
}

func generate(plugin *protogen.Plugin) error {
	plugin.SupportedFeatures = uint64(pluginpb.CodeGeneratorResponse_FEATURE_PROTO3_OPTIONAL)
	for _, source := range plugin.Files {
		if !source.Generate || len(source.Services) == 0 {
			continue
		}
		output := plugin.NewGeneratedFile(source.GeneratedFilenamePrefix+"_rpc.pb.go", source.GoImportPath)
		output.P("package ", source.GoPackageName)
		for _, service := range source.Services {
			if failure := generateService(output, service); failure != nil {
				return failure
			}
		}
	}
	return nil
}

func generateService(output *protogen.GeneratedFile, service *protogen.Service) error {
	contextType := protogen.GoIdent{GoName: "Context", GoImportPath: "context"}
	messageType := protogen.GoIdent{GoName: "Message", GoImportPath: "google.golang.org/protobuf/proto"}
	clientType := service.GoName + "Client"
	implementation := strings.ToLower(service.GoName[:1]) + service.GoName[1:] + "Client"
	invoker := implementation + "Invoker"
	output.P("type ", invoker, " interface {")
	output.P("Invoke(", contextType, ", string, ", messageType, ", ", messageType, ") error")
	output.P("}")
	output.P("type ", clientType, " interface {")
	for _, method := range service.Methods {
		if method.Desc.IsStreamingClient() || method.Desc.IsStreamingServer() {
			return fmt.Errorf("streaming RPC %s is outside the bounded unary profile", method.Desc.FullName())
		}
		output.P(method.GoName, "(", contextType, ", *", method.Input.GoIdent, ") (*", method.Output.GoIdent, ", error)")
	}
	output.P("}")
	output.P("type ", implementation, " struct { connection ", invoker, " }")
	output.P("func New", clientType, "(connection ", invoker, ") ", clientType, " {")
	output.P("return &", implementation, "{connection: connection}")
	output.P("}")
	for _, method := range service.Methods {
		constant := service.GoName + "_" + method.GoName + "_FullMethodName"
		output.P("const ", constant, " = ", fmt.Sprintf("%q", "/"+string(service.Desc.FullName())+"/"+string(method.Desc.Name())))
		output.P("func (client *", implementation, ") ", method.GoName,
			"(ctx ", contextType, ", request *", method.Input.GoIdent, ") (*", method.Output.GoIdent, ", error) {")
		output.P("response := new(", method.Output.GoIdent, ")")
		output.P("if failure := client.connection.Invoke(ctx, ", constant, ", request, response); failure != nil {")
		output.P("return nil, failure")
		output.P("}")
		output.P("return response, nil")
		output.P("}")
	}
	return nil
}
