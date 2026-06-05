import Foundation
import SwiftUI
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input: String = ""
    @Published var isRunning: Bool = false
    @Published var errorMessage: String? = nil

    private let settings: AppSettings
    private let store: ConversationStore
    private var cancellables: Set<AnyCancellable> = []
    private var loadedConversationID: UUID?

    init(settings: AppSettings, store: ConversationStore) {
        self.settings = settings
        self.store = store
        bindToStore()
    }

    private func bindToStore() {
        // Reload messages whenever the user picks a different conversation.
        store.$selectedID
            .removeDuplicates()
            .sink { [weak self] id in
                guard let self else { return }
                self.loadFromStore(id: id)
            }
            .store(in: &cancellables)
    }

    private func loadFromStore(id: UUID?) {
        loadedConversationID = id
        if let id, let conv = store.conversations.first(where: { $0.id == id }) {
            messages = conv.messages.map { $0.toChatMessage() }
        } else {
            messages = []
        }
        errorMessage = nil
        input = ""
    }

    private var client: AutumnClient? {
        guard let url = URL(string: settings.serverURL) else { return nil }
        return AutumnClient(baseURL: url)
    }

    func send() async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isRunning else { return }
        guard let client = client else {
            errorMessage = "服务器 URL 无效"
            return
        }

        input = ""
        errorMessage = nil

        withAnimation(Autumn.motion.snappy) {
            messages.append(ChatMessage(role: .user, text: text))
            messages.append(ChatMessage(role: .assistant, text: ""))
        }
        persistMessages()

        let assistantIndex = messages.count - 1
        isRunning = true
        defer {
            isRunning = false
            persistMessages()
        }

        do {
            let trace = try await client.trace(text, route: settings.routeMode)
            withAnimation(Autumn.motion.smooth) {
                messages[assistantIndex].text = trace.output.isEmpty ? "(empty response)" : trace.output
                messages[assistantIndex].trace = trace
            }
        } catch {
            errorMessage = error.localizedDescription
            messages[assistantIndex].text +=
                (messages[assistantIndex].text.isEmpty ? "" : "\n\n") +
                "[错误] \(error.localizedDescription)"
        }
    }

    func clear() {
        withAnimation(Autumn.motion.smooth) {
            messages.removeAll()
            errorMessage = nil
        }
        if let id = loadedConversationID {
            store.clearMessages(id)
        }
    }

    func endSession() async {
        guard let client = client else { return }
        do {
            try await client.endSession()
            clear()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // ── private ───────────────────────────────────────────────────────────────

    private func persistMessages() {
        guard let id = loadedConversationID else { return }
        store.updateMessages(id, messages: messages)
    }
}
