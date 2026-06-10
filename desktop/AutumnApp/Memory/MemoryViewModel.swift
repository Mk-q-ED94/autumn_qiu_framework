import Foundation

@MainActor
final class MemoryViewModel: ObservableObject {
    @Published var selectedArea: MemoryArea = .mom1
    @Published var entries: [MemoryEntry] = []
    @Published var stats: MemoryStats?
    @Published var overview: MemoryStatsOverview?
    @Published var isLoading = false
    @Published var isConsolidating = false
    @Published var errorMessage: String?
    @Published var actionMessage: String?

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
            async let history = client.memoryHistory(area: selectedArea)
            async let areaStats = client.memoryStats(area: selectedArea)
            async let allStats = client.memoryStatsOverview()
            entries = try await history
            stats = try await areaStats
            overview = try await allStats
        } catch {
            entries = []
            stats = nil
            overview = nil
            errorMessage = error.localizedDescription
        }
    }

    func consolidateSelectedArea() async {
        guard let url = URL(string: settings.serverURL) else {
            actionMessage = "服务器 URL 无效"
            return
        }

        isConsolidating = true
        actionMessage = nil
        defer { isConsolidating = false }

        do {
            let response = try await AutumnClient(baseURL: url)
                .consolidateMemory(area: selectedArea)
            actionMessage = response.status == "noop" ? "无需归并" : "已归并"
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }
}
