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
    let kind: String   // "stage" = workflow step, "tool" = an agent tool call

    init(
        id: String,
        title: String,
        detail: String,
        workspace: String,
        status: String,
        kind: String = "stage"
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.workspace = workspace
        self.status = status
        self.kind = kind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        detail = try c.decode(String.self, forKey: .detail)
        workspace = try c.decode(String.self, forKey: .workspace)
        status = try c.decode(String.self, forKey: .status)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "stage"
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, detail, workspace, status, kind
    }
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
