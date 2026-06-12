import Foundation

struct ProcessRequest: Encodable {
    let input: String
    let route: String?
    let inputType: String?
    let taskType: String?
    let projectInstructions: String?
    let projectID: String?

    init(
        input: String,
        route: String? = nil,
        inputType: String? = nil,
        taskType: String? = nil,
        projectInstructions: String? = nil,
        projectID: String? = nil
    ) {
        self.input = input
        self.route = route
        self.inputType = inputType
        self.taskType = taskType
        self.projectInstructions = projectInstructions
        self.projectID = projectID
    }

    enum CodingKeys: String, CodingKey {
        case input
        case route
        case inputType = "input_type"
        case taskType = "task_type"
        case projectInstructions = "project_instructions"
        case projectID = "project_id"
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
    let totalCostUsd: Double?

    init(
        output: String,
        inputType: String,
        route: String?,
        taskType: String?,
        stages: [WorkflowStage],
        totalPromptTokens: Int? = nil,
        totalCompletionTokens: Int? = nil,
        totalCostUsd: Double? = nil
    ) {
        self.output = output
        self.inputType = inputType
        self.route = route
        self.taskType = taskType
        self.stages = stages
        self.totalPromptTokens = totalPromptTokens
        self.totalCompletionTokens = totalCompletionTokens
        self.totalCostUsd = totalCostUsd
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
        totalCostUsd = try c.decodeIfPresent(Double.self, forKey: .totalCostUsd)
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

    var hasFailedStage: Bool {
        stages.contains { $0.status == "failed" }
    }

    var completedStageCount: Int {
        stages.filter { $0.status == "completed" }.count
    }

    var toolStageCount: Int {
        stages.filter { $0.kind == "tool" }.count
    }

    var agentStageCount: Int {
        stages.filter { $0.kind == "agent" }.count
    }

    var hasAgentActivity: Bool {
        agentStageCount > 0 || toolStageCount > 0
    }

    /// The wp4.push stage when the 4D push engine fired this turn.
    var pushStage: WorkflowStage? {
        stages.first { $0.kind == "push" }
    }

    var sourceTerrNames: [String] {
        Array(Set(stages.compactMap(\.sourceTerr))).sorted()
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
        case totalCostUsd = "total_cost_usd"
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
    let sourceTerr: String?
    let costUsd: Double?

    init(
        id: String,
        title: String,
        detail: String,
        workspace: String,
        status: String,
        kind: String = "stage",
        durationMS: Double? = nil,
        promptTokens: Int? = nil,
        completionTokens: Int? = nil,
        sourceTerr: String? = nil,
        costUsd: Double? = nil
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
        self.sourceTerr = sourceTerr
        self.costUsd = costUsd
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
        sourceTerr = try c.decodeIfPresent(String.self, forKey: .sourceTerr)
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd)
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, detail, workspace, status, kind
        case durationMS = "duration_ms"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case sourceTerr = "source_terr"
        case costUsd = "cost_usd"
    }
}

struct IntentPreview: Decodable, Equatable {
    let inputType: String
    let taskType: String?
    let route: String?
    let confidence: Double
    let reasoning: String?

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
        case reasoning
    }
}

struct TerrSummary: Decodable, Identifiable, Equatable {
    var name: String
    var description: String
    var enabled: Bool
    var tools: [TerrCallable]
    var skills: [TerrCallable]
    var mcps: [TerrMCP]

    var id: String { name }

    init(
        name: String,
        description: String,
        enabled: Bool = true,
        tools: [TerrCallable],
        skills: [TerrCallable],
        mcps: [TerrMCP]
    ) {
        self.name = name
        self.description = description
        self.enabled = enabled
        self.tools = tools
        self.skills = skills
        self.mcps = mcps
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        description = try c.decode(String.self, forKey: .description)
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
        tools = try c.decode([TerrCallable].self, forKey: .tools)
        skills = try c.decode([TerrCallable].self, forKey: .skills)
        mcps = try c.decode([TerrMCP].self, forKey: .mcps)
    }

    private enum CodingKeys: String, CodingKey {
        case name, description, enabled, tools, skills, mcps
    }
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
    let trace: WorkflowTrace?
    let error: String?
}

enum StreamEvent {
    case chunk(String)
    case trace(WorkflowTrace)
}

struct HealthResponse: Decodable {
    let status: String
    let configured: Bool
    let lastError: String?

    enum CodingKeys: String, CodingKey {
        case status, configured
        case lastError = "last_error"
    }
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
    let a4: ProviderConfigRequest?
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

struct TerrToggleRequest: Encodable {
    let enabled: Bool
}
