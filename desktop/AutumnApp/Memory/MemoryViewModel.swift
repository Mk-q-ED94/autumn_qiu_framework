import Foundation

@MainActor
final class MemoryViewModel: ObservableObject {
    enum ViewMode { case memory, accessLog }

    @Published var viewMode: ViewMode = .memory
    @Published var selectedArea: MemoryArea = .mom1
    @Published var selectedMode: FourDUseMode?
    @Published var entries: [MemoryEntry] = []
    @Published var stats: MemoryStats?
    @Published var overview: MemoryStatsOverview?
    @Published var isLoading = false
    @Published var isConsolidating = false
    @Published var errorMessage: String?
    @Published var actionMessage: String?

    // ── access log ─────────────────────────────────────────────────────────────
    @Published var accessLogEntries: [AccessLogEntry] = []
    @Published var accessLogTotal: Int = 0
    @Published var accessLogVerdict: String? = nil   // nil=all, "granted", "denied"
    @Published var isLoadingAccessLog = false
    @Published var accessLogError: String?

    private let settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
    }

    // ── memory ──────────────────────────────────────────────────────────────────

    var filteredEntries: [MemoryEntry] {
        let ordered = entries.reversed()
        guard let mode = selectedMode else { return Array(ordered) }
        return ordered.filter { $0.fourdMode == mode }
    }

    var modeCounts: [FourDUseMode: Int] {
        entries.reduce(into: [:]) { counts, entry in
            if let mode = entry.fourdMode { counts[mode, default: 0] += 1 }
        }
    }

    var annotatedCount: Int { entries.filter(\.has4DData).count }

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
            let response = try await AutumnClient(baseURL: url).consolidateMemory(area: selectedArea)
            actionMessage = response.status == "noop" ? "无需归并" : "已归并"
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    // ── access log ──────────────────────────────────────────────────────────────

    var filteredAccessEntries: [AccessLogEntry] {
        switch accessLogVerdict {
        case "granted": return accessLogEntries.filter(\.isGranted)
        case "denied":  return accessLogEntries.filter { !$0.isGranted }
        default:        return accessLogEntries
        }
    }

    var grantedCount: Int { accessLogEntries.filter(\.isGranted).count }
    var deniedCount: Int  { accessLogEntries.filter { !$0.isGranted }.count }

    func loadAccessLog() async {
        guard let url = URL(string: settings.serverURL) else {
            accessLogError = "服务器 URL 无效"
            return
        }
        isLoadingAccessLog = true
        accessLogError = nil
        defer { isLoadingAccessLog = false }
        do {
            let response = try await AutumnClient(baseURL: url).fetchAccessLog()
            accessLogEntries = response.entries
            accessLogTotal = response.total
        } catch {
            accessLogEntries = []
            accessLogError = error.localizedDescription
        }
    }
}
