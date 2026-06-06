import Foundation

/// Persistable single conversation.
///
/// ``projectID`` is optional so legacy persisted blobs without the field
/// continue to decode (custom ``init(from:)`` defaults it to nil).
struct Conversation: Identifiable, Codable, Equatable {
    let id: UUID
    var title: String
    var messages: [PersistableMessage]
    var createdAt: Date
    var updatedAt: Date
    var projectID: UUID?

    init(
        id: UUID = UUID(),
        title: String = "新对话",
        messages: [PersistableMessage] = [],
        createdAt: Date = Date(),
        updatedAt: Date = Date(),
        projectID: UUID? = nil
    ) {
        self.id = id
        self.title = title
        self.messages = messages
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.projectID = projectID
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        messages = try c.decode([PersistableMessage].self, forKey: .messages)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
        projectID = try c.decodeIfPresent(UUID.self, forKey: .projectID)
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, messages, createdAt, updatedAt, projectID
    }
}

/// Codable mirror of ChatMessage; trace is stored as raw JSON-decoded blob.
struct PersistableMessage: Codable, Equatable, Identifiable {
    let id: UUID
    let role: String
    var text: String
    var trace: PersistableTrace?
    let timestamp: Date

    init(from chat: ChatMessage) {
        self.id = chat.id
        self.role = chat.role.rawValue
        self.text = chat.text
        self.trace = chat.trace.map(PersistableTrace.init)
        self.timestamp = chat.timestamp
    }

    func toChatMessage() -> ChatMessage {
        ChatMessage(
            id: id,
            role: ChatMessage.Role(rawValue: role) ?? .assistant,
            text: text,
            trace: trace?.toWorkflowTrace(),
            timestamp: timestamp
        )
    }
}

struct PersistableTrace: Codable, Equatable {
    let output: String
    let inputType: String
    let route: String?
    let taskType: String?
    let stages: [PersistableStage]
    let totalPromptTokens: Int?
    let totalCompletionTokens: Int?

    init(from trace: WorkflowTrace) {
        self.output = trace.output
        self.inputType = trace.inputType
        self.route = trace.route
        self.taskType = trace.taskType
        self.stages = trace.stages.map { PersistableStage(from: $0) }
        self.totalPromptTokens = trace.totalPromptTokens
        self.totalCompletionTokens = trace.totalCompletionTokens
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        output = try c.decode(String.self, forKey: .output)
        inputType = try c.decode(String.self, forKey: .inputType)
        route = try c.decodeIfPresent(String.self, forKey: .route)
        taskType = try c.decodeIfPresent(String.self, forKey: .taskType)
        stages = try c.decode([PersistableStage].self, forKey: .stages)
        totalPromptTokens = try c.decodeIfPresent(Int.self, forKey: .totalPromptTokens)
        totalCompletionTokens = try c.decodeIfPresent(Int.self, forKey: .totalCompletionTokens)
    }

    private enum CodingKeys: String, CodingKey {
        case output, inputType, route, taskType, stages
        case totalPromptTokens, totalCompletionTokens
    }

    func toWorkflowTrace() -> WorkflowTrace {
        WorkflowTrace(
            output: output,
            inputType: inputType,
            route: route,
            taskType: taskType,
            stages: stages.map { $0.toWorkflowStage() },
            totalPromptTokens: totalPromptTokens,
            totalCompletionTokens: totalCompletionTokens
        )
    }
}

struct PersistableStage: Codable, Equatable {
    let id: String
    let title: String
    let detail: String
    let workspace: String
    let status: String
    let kind: String
    let durationMS: Double?
    let promptTokens: Int?
    let completionTokens: Int?

    init(from stage: WorkflowStage) {
        self.id = stage.id
        self.title = stage.title
        self.detail = stage.detail
        self.workspace = stage.workspace
        self.status = stage.status
        self.kind = stage.kind
        self.durationMS = stage.durationMS
        self.promptTokens = stage.promptTokens
        self.completionTokens = stage.completionTokens
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
        case durationMS
        case promptTokens, completionTokens
    }

    func toWorkflowStage() -> WorkflowStage {
        WorkflowStage(
            id: id,
            title: title,
            detail: detail,
            workspace: workspace,
            status: status,
            kind: kind,
            durationMS: durationMS,
            promptTokens: promptTokens,
            completionTokens: completionTokens
        )
    }
}
