import Foundation

/// Persistable single conversation.
struct Conversation: Identifiable, Codable, Equatable {
    let id: UUID
    var title: String
    var messages: [PersistableMessage]
    var createdAt: Date
    var updatedAt: Date

    init(
        id: UUID = UUID(),
        title: String = "新对话",
        messages: [PersistableMessage] = [],
        createdAt: Date = Date(),
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.messages = messages
        self.createdAt = createdAt
        self.updatedAt = updatedAt
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
    let stages: [PersistableStage]

    init(from trace: WorkflowTrace) {
        self.output = trace.output
        self.inputType = trace.inputType
        self.route = trace.route
        self.stages = trace.stages.map(PersistableStage.init)
    }

    func toWorkflowTrace() -> WorkflowTrace {
        WorkflowTrace(
            output: output,
            inputType: inputType,
            route: route,
            stages: stages.map { $0.toWorkflowStage() }
        )
    }
}

struct PersistableStage: Codable, Equatable {
    let id: String
    let title: String
    let detail: String
    let workspace: String
    let status: String

    init(from stage: WorkflowStage) {
        self.id = stage.id
        self.title = stage.title
        self.detail = stage.detail
        self.workspace = stage.workspace
        self.status = stage.status
    }

    func toWorkflowStage() -> WorkflowStage {
        WorkflowStage(id: id, title: title, detail: detail, workspace: workspace, status: status)
    }
}
