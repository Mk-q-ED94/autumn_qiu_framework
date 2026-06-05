import Foundation

@MainActor
final class MemoryViewModel: ObservableObject {
    @Published var selectedArea: MemoryArea = .mom1
    @Published var entries: [MemoryEntry] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
    }

    func load() async {
        guard let url = URL(string: settings.serverURL) else {
            errorMessage = "服务器 URL 无效"
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let client = AutumnClient(baseURL: url)
            entries = try await client.memoryHistory(area: selectedArea)
        } catch {
            entries = []
            errorMessage = error.localizedDescription
        }
    }
}
