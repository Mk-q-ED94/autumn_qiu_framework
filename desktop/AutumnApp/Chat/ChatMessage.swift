import Foundation

struct ChatMessage: Identifiable, Equatable {
    enum Role: String, Codable { case user, assistant }

    let id: UUID
    let role: Role
    var text: String
    var trace: WorkflowTrace?
    let timestamp: Date

    /// Default init used at runtime when composing fresh messages.
    init(role: Role, text: String, trace: WorkflowTrace? = nil) {
        self.id = UUID()
        self.role = role
        self.text = text
        self.trace = trace
        self.timestamp = Date()
    }

    /// Full init used by persistence to rehydrate a stored message.
    init(id: UUID, role: Role, text: String, trace: WorkflowTrace?, timestamp: Date) {
        self.id = id
        self.role = role
        self.text = text
        self.trace = trace
        self.timestamp = timestamp
    }
}
