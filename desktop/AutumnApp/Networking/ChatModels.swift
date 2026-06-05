import Foundation

struct ProcessRequest: Encodable {
    let input: String
    let route: String?
}

struct ProcessResponse: Decodable {
    let output: String
}

struct WorkflowTrace: Decodable, Equatable {
    let output: String
    let inputType: String
    let route: String?
    let stages: [WorkflowStage]

    enum CodingKeys: String, CodingKey {
        case output
        case inputType = "input_type"
        case route
        case stages
    }
}

struct WorkflowStage: Decodable, Identifiable, Equatable {
    let id: String
    let title: String
    let detail: String
    let workspace: String
    let status: String
}

struct StreamPayload: Decodable {
    let chunk: String?
    let error: String?
}

struct HealthResponse: Decodable {
    let status: String
    let configured: Bool
}

struct ProviderConfigRequest: Codable {
    let apiKey: String
    let baseURL: String
    let model: String?
    let apiProtocol: String

    enum CodingKeys: String, CodingKey {
        case apiKey = "api_key"
        case baseURL = "base_url"
        case model
        case apiProtocol = "protocol"
    }
}

struct ApplyConfigRequest: Encodable {
    let a1: ProviderConfigRequest
    let a2: ProviderConfigRequest
    let a3: ProviderConfigRequest
}

struct ApplyConfigResponse: Decodable {
    let status: String
    let configured: Bool
}

struct ModelsRequest: Encodable {
    let apiKey: String
    let baseURL: String
    let apiProtocol: String

    enum CodingKeys: String, CodingKey {
        case apiKey = "api_key"
        case baseURL = "base_url"
        case apiProtocol = "protocol"
    }
}

struct ModelsResponse: Decodable {
    let models: [String]
}
