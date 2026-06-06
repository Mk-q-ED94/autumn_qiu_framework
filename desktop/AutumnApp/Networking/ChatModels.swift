import Foundation

struct ProcessRequest: Encodable {
    let input: String
    let route: String?
    let inputType: String?
    let taskType: String?

    init(input: String, route: String? = nil, inputType: String? = nil, taskType: String? = nil) {
        self.input = input
        self.route = route
        self.inputType = inputType
        self.taskType = taskType
    }

    enum CodingKeys: String, CodingKey {
        case input
        case route
        case inputType = "input_type"
        case taskType = "task_type"
    }
}

struct ProcessResponse: Decodable {
    let output: String
}

struct WorkflowTrace: Decodable, Equatable {
    let output: String
    let inputType: String
    let route: String?
    let taskType: String?
    let stages: [WorkflowStage]
    let totalPromptTokens: Int?
    let totalCompletionTokens: Int?

    init(
        output: String,
        inputType: String,
        route: String?,
        taskType: String?,
        stages: [WorkflowStage],
        totalPromptTokens: Int? = nil,
        totalCompletionTokens: Int? = nil
    ) {
        self.output = output
        self.inputType = inputType
        self.route = route
        self.taskType = taskType
        self.stages = stages
        self.totalPromptTokens = totalPromptTokens
        self.totalCompletionTokens = totalCompletionTokens
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        output = try c.decode(String.self, forKey: .output)
        inputType = try c.decode(String.self, forKey: .inputType)
        route = try c.decodeIfPresent(String.self, forKey: .route)
        taskType = try c.decodeIfPresent(String.self, forKey: .taskType)
        stages = try c.decode([WorkflowStage].self, forKey: .stages)
        totalPromptTokens = try c.decodeIfPresent(Int.self, forKey: .totalPromptTokens)
        totalCompletionTokens = try c.decodeIfPresent(Int.self, forKey: .totalCompletionTokens)
    }

    var inputKind: WorkflowInputKind {
        WorkflowInputKind(rawValue: inputType) ?? .mission
    }

    var taskKind: WorkflowTaskKind? {
        guard let taskType else { return nil }
        return WorkflowTaskKind(rawValue: taskType)
    }

    var routeMode: MissionRouteMode? {
        guard let route else { return nil }
        return MissionRouteMode(rawValue: route)
    }

    var isLive: Bool {
        stages.contains { $0.status == "active" || $0.status == "pending" }
    }

    var totalDurationMS: Double? {
        let values = stages.compactMap(\.durationMS)
        guard !values.isEmpty else { return nil }
        return values.reduce(0, +)
    }

    enum CodingKeys: String, CodingKey {
        case output
        case inputType = "input_type"
        case route
        case taskType = "task_type"
        case stages
        case totalPromptTokens = "total_prompt_tokens"
        case totalCompletionTokens = "total_completion_tokens"
    }
}

struct WorkflowStage: Decodable, Identifiable, Equatable {
    let id: String
    let title: String
    let detail: String
    let workspace: String
    let status: String
    let kind: String   // "stage" = workflow step, "tool" = an agent tool call
    let durationMS: Double?
    let promptTokens: Int?
    let completionTokens: Int?

    init(
        id: String,
        title: String,
        detail: String,
        workspace: String,
        status: String,
        kind: String = "stage",
        durationMS: Double? = nil,
        promptTokens: Int? = nil,
        completionTokens: Int? = nil
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.workspace = workspace
        self.status = status
        self.kind = kind
        self.durationMS = durationMS
        self.promptTokens = promptTokens
        self.completionTokens = completionTokens
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        detail = try c.decode(String.self, forKey: .detail)
        workspace = try c.decode(String.self, forKey: .workspace)
        status = try c.decode(String.self, forKey: .status)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "stage"
        durationMS = try c.decodeIfPresent(Double.self, forKey: .durationMS)
        promptTokens = try c.decodeIfPresent(Int.self, forKey: .promptTokens)
        completionTokens = try c.decodeIfPresent(Int.self, forKey: .completionTokens)
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, detail, workspace, status, kind
        case durationMS = "duration_ms"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
    }
}

struct IntentPreview: Decodable, Equatable {
    let inputType: String
    let taskType: String?
    let route: String?
    let confidence: Double

    var inputKind: WorkflowInputKind {
        WorkflowInputKind(rawValue: inputType) ?? .mission
    }

    var taskKind: WorkflowTaskKind? {
        guard let taskType else { return nil }
        return WorkflowTaskKind(rawValue: taskType)
    }

    var routeMode: MissionRouteMode? {
        guard let route else { return nil }
        return MissionRouteMode(rawValue: route)
    }

    var badgeTitle: String {
        if inputKind == .task {
            return taskKind?.badgeTitle ?? WorkflowTaskKind.general.badgeTitle
        }
        return inputKind.badgeTitle
    }

    enum CodingKeys: String, CodingKey {
        case inputType = "input_type"
        case taskType = "task_type"
        case route
        case confidence
    }
}

struct TerrSummary: Decodable, Identifiable, Equatable {
    let name: String
    let description: String
    let tools: [TerrCallable]
    let skills: [TerrCallable]
    let mcps: [TerrMCP]

    var id: String { name }
}

struct TerrCallable: Decodable, Identifiable, Equatable {
    let name: String
    let description: String
    let parameters: [TerrParameter]

    var id: String { name }
}

struct TerrParameter: Decodable, Identifiable, Equatable {
    let name: String
    let type: String
    let description: String
    let required: Bool

    var id: String { name }
}

struct TerrMCP: Decodable, Identifiable, Equatable {
    let name: String
    let description: String

    var id: String { name }
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
