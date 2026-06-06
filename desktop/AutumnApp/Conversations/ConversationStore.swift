import Foundation
import SwiftUI

/// Owns the conversation list and persists it to UserDefaults as JSON.
@MainActor
final class ConversationStore: ObservableObject {
    @Published private(set) var conversations: [Conversation] = []
    @Published var selectedID: UUID?
    @Published private(set) var isLoading: Bool = true

    private static let storageKey = "AutumnDesktop.conversations.v1"
    private static let selectionKey = "AutumnDesktop.conversations.selected"
    private static let maxKeptConversations = 60

    init() {
        load()
        if conversations.isEmpty {
            let fresh = Conversation()
            conversations.append(fresh)
            selectedID = fresh.id
        } else if let raw = UserDefaults.standard.string(forKey: Self.selectionKey),
                  let uuid = UUID(uuidString: raw),
                  conversations.contains(where: { $0.id == uuid }) {
            selectedID = uuid
        } else {
            selectedID = conversations.first?.id
        }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 220_000_000)
            await MainActor.run {
                self?.isLoading = false
            }
        }
    }

    var selected: Conversation? {
        guard let id = selectedID else { return nil }
        return conversations.first(where: { $0.id == id })
    }

    func newConversation() {
        let new = Conversation()
        conversations.insert(new, at: 0)
        selectedID = new.id
        persist()
    }

    func select(_ id: UUID) {
        selectedID = id
        UserDefaults.standard.set(id.uuidString, forKey: Self.selectionKey)
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
        if selectedID == id {
            selectedID = conversations.first?.id
        }
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
