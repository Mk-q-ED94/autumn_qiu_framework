import Foundation
import SwiftUI

/// Owns the conversation list and persists it to UserDefaults as JSON.
@MainActor
final class ConversationStore: ObservableObject {
    @Published private(set) var conversations: [Conversation] = []
    @Published private(set) var isLoading: Bool = true

    private static let storageKey = "AutumnDesktop.conversations.v1"
    private static let maxKeptConversations = 60

    init() {
        load()
        if conversations.isEmpty {
            let fresh = Conversation()
            conversations.append(fresh)
        }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 220_000_000)
            await MainActor.run {
                self?.isLoading = false
            }
        }
    }

    @discardableResult
    func newConversation(projectID: UUID? = nil) -> UUID {
        let new = Conversation(projectID: projectID)
        conversations.insert(new, at: 0)
        persist()
        return new.id
    }

    func rename(_ id: UUID, to title: String) {
        guard let idx = conversations.firstIndex(where: { $0.id == id }) else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        conversations[idx].title = trimmed.isEmpty ? "新对话" : trimmed
        conversations[idx].updatedAt = Date()
        persist()
    }

    func delete(_ id: UUID) {
        conversations.removeAll(where: { $0.id == id })
        if conversations.isEmpty {
            newConversation()
        }
        persist()
    }

    func updateMessages(_ id: UUID, messages: [ChatMessage]) {
        guard let idx = conversations.firstIndex(where: { $0.id == id }) else { return }
        conversations[idx].messages = messages.map(PersistableMessage.init)
        conversations[idx].updatedAt = Date()

        // Auto-name from the first user message if still untitled.
        if conversations[idx].title == "新对话",
           let firstUser = messages.first(where: { $0.role == .user })?.text {
            let preview = String(firstUser.prefix(28)).trimmingCharacters(in: .whitespacesAndNewlines)
            if !preview.isEmpty {
                conversations[idx].title = preview
            }
        }
        persist()
    }

    func clearMessages(_ id: UUID) {
        guard let idx = conversations.firstIndex(where: { $0.id == id }) else { return }
        conversations[idx].messages = []
        conversations[idx].updatedAt = Date()
        persist()
    }

    // ── project assignment ───────────────────────────────────────────────────

    /// Assigns ``conversationID`` to ``projectID`` (nil = unfiled).
    func moveConversation(_ conversationID: UUID, toProject projectID: UUID?) {
        guard let idx = conversations.firstIndex(where: { $0.id == conversationID }) else { return }
        guard conversations[idx].projectID != projectID else { return }
        conversations[idx].projectID = projectID
        conversations[idx].updatedAt = Date()
        persist()
    }

    /// Clears project membership for every conversation in the given project —
    /// called when the project itself is deleted so conversations survive as
    /// unfiled rather than vanishing.
    func unfileConversations(belongingTo projectID: UUID) {
        var changed = false
        for idx in conversations.indices where conversations[idx].projectID == projectID {
            conversations[idx].projectID = nil
            conversations[idx].updatedAt = Date()
            changed = true
        }
        if changed { persist() }
    }

    func conversations(in projectID: UUID?) -> [Conversation] {
        conversations.filter { $0.projectID == projectID }
    }

    var unfiledConversations: [Conversation] {
        conversations.filter { $0.projectID == nil }
    }

    // ── persistence ──────────────────────────────────────────────────────────

    private func persist() {
        let kept = Array(conversations.prefix(Self.maxKeptConversations))
        if let data = try? JSONEncoder().encode(kept) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([Conversation].self, from: data)
        else { return }
        conversations = decoded
    }
}
