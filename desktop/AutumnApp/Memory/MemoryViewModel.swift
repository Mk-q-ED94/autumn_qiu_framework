import Foundation

@MainActor
final class MemoryViewModel: ObservableObject {
    enum ViewMode: String, CaseIterable, Identifiable {
        case memory
        case pushPreview
        case accessLog

        var id: String { rawValue }

        var title: String {
            switch self {
            case .memory:      return "记忆"
            case .pushPreview: return "推送预览"
            case .accessLog:   return "访问审计"
            }
        }

        var icon: String {
            switch self {
            case .memory:      return "brain"
            case .pushPreview: return "bolt.badge.clock"
            case .accessLog:   return "shield.lefthalf.filled"
            }
        }
    }

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

    // ── 4D status + producer actions ────────────────────────────────────────────
    @Published var fourdStatus: FourDStatus?
    @Published var isAutoAnnotating = false

    // ── push preview ─────────────────────────────────────────────────────────────
    @Published var pushQuery: String = ""
    @Published var pushFired: [PushPreviewEntry] = []
    @Published var pushFragment: String = ""
    @Published var pushEnabled: Bool = false
    @Published var hasRunPush: Bool = false
    @Published var isLoadingPush = false
    @Published var pushError: String?

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
        await loadFourDStatus()
    }

    func loadFourDStatus() async {
        guard let url = URL(string: settings.serverURL) else { return }
        // 4D status is best-effort: an older server without the endpoint simply
        // leaves the memory list usable rather than failing the whole load.
        fourdStatus = try? await AutumnClient(baseURL: url).fetch4DStatus()
    }

    // ── producer actions: annotate + auto-annotate ──────────────────────────────

    func autoAnnotate() async {
        guard let url = URL(string: settings.serverURL) else {
            actionMessage = "服务器 URL 无效"
            return
        }
        isAutoAnnotating = true
        actionMessage = nil
        defer { isAutoAnnotating = false }
        do {
            let result = try await AutumnClient(baseURL: url).autoAnnotate(area: selectedArea)
            actionMessage = "已标注 \(result.annotated)/\(result.scanned) 条"
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func annotate(entry: MemoryEntry, mode: FourDUseMode, cues: String) async {
        guard let url = URL(string: settings.serverURL) else {
            actionMessage = "服务器 URL 无效"
            return
        }
        guard let entryID = entry.entryID else {
            actionMessage = "无法获取条目 ID"
            return
        }
        let cueList = cues
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        do {
            _ = try await AutumnClient(baseURL: url).annotateMemory(
                area: selectedArea, entryID: entryID,
                mode: mode.rawValue, intent: nil,
                cues: cueList.isEmpty ? nil : cueList
            )
            actionMessage = "已标注为 \(mode.label)"
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    // ── push preview ─────────────────────────────────────────────────────────────

    func runPushPreview() async {
        guard let url = URL(string: settings.serverURL) else {
            pushError = "服务器 URL 无效"
            return
        }
        isLoadingPush = true
        pushError = nil
        defer { isLoadingPush = false }
        do {
            let response = try await AutumnClient(baseURL: url)
                .pushPreview(area: selectedArea, query: pushQuery)
            pushFired = response.fired
            pushFragment = response.fragment
            pushEnabled = response.enabled
            hasRunPush = true
            await loadFourDStatus()
        } catch {
            pushFired = []
            pushFragment = ""
            pushError = error.localizedDescription
            hasRunPush = true
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
