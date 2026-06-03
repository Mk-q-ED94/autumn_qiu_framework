import Foundation
import SwiftUI

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input: String = ""
    @Published var isStreaming: Bool = false
    @Published var errorMessage: String? = nil

    private let settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
    }

    private var client: AutumnClient? {
        guard let url = URL(string: settings.serverURL) else { return nil }
        return AutumnClient(baseURL: url)
    }

    func send() async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }
        guard let client = client else {
            errorMessage = "服务器 URL 无效"
            return
        }

        input = ""
        errorMessage = nil

        messages.append(ChatMessage(role: .user, text: text))
        let assistantIndex = messages.count
        messages.append(ChatMessage(role: .assistant, text: ""))

        isStreaming = true
        defer { isStreaming = false }

        do {
            for try await chunk in client.stream(text, route: settings.routeMode) {
                messages[assistantIndex].text += chunk
            }
            if messages[assistantIndex].text.isEmpty {
                messages[assistantIndex].text = "(empty response)"
            }
        } catch {
            errorMessage = error.localizedDescription
            messages[assistantIndex].text +=
                (messages[assistantIndex].text.isEmpty ? "" : "\n\n") +
                "[错误] \(error.localizedDescription)"
        }
    }

    func clear() {
        messages.removeAll()
        errorMessage = nil
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
}
