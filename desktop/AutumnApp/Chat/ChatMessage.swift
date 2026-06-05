import Foundation

struct ChatMessage: Identifiable, Equatable {
    enum Role: String { case user, assistant }

    let id: UUID
    let role: Role
    var text: String
    var trace: WorkflowTrace?
    let timestamp: Date

    init(role: Role, text: String, trace: WorkflowTrace? = nil) {
        self.id = UUID()
        self.role = role
        self.text = text
        self.trace = trace
        self.timestamp = Date()
    }
}
