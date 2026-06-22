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
    @Published var selectedKind: MemoryKind?
    @Published var entries: [MemoryEntry] = []
    @Published var stats: MemoryStats?
    @Published var overview: MemoryStatsOverview?
    @Published var isLoading = false
    @Published var isConsolidating = false
    @Published var isExtractingFacts = false
    @Published var isEvolving = false
    @Published var errorMessage: String?
    @Published var actionMessage: String?

    // ── 4D status + producer actions ────────────────────────────────────────────
    @Published var fourdStatus: FourDStatus?
    @Published var isAutoAnnotating = false

    // ── derived memory profile ─────────────────────────────────────────────────
    @Published var showProfilePanel = false
    @Published var profileScope = "default"
    @Published var profileText: String?
    @Published var profileError: String?
    @Published var isLoadingProfile = false

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
        return ordered.filter { entry in
            let modeMatches = selectedMode.map { entry.fourdMode == $0 } ?? true
            let kindMatches = selectedKind.map { entry.memoryKind == $0 } ?? true
            return modeMatches && kindMatches
        }
    }

    var modeCounts: [FourDUseMode: Int] {
        entries.reduce(into: [:]) { counts, entry in
            if let mode = entry.fourdMode { counts[mode, default: 0] += 1 }
        }
    }

    var kindCounts: [MemoryKind: Int] {
        entries.reduce(into: [:]) { counts, entry in
            if let kind = entry.memoryKind { counts[kind, default: 0] += 1 }
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
            let client = QcoworkClient(baseURL: url)
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
        fourdStatus = try? await QcoworkClient(baseURL: url).fetch4DStatus()
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
            let result = try await QcoworkClient(baseURL: url).autoAnnotate(area: selectedArea)
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
            _ = try await QcoworkClient(baseURL: url).annotateMemory(
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
            let response = try await QcoworkClient(baseURL: url)
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
            let response = try await QcoworkClient(baseURL: url).consolidateMemory(area: selectedArea)
            actionMessage = response.status == "noop" ? "无需归并" : "已归并"
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func extractFacts() async {
        guard let url = URL(string: settings.serverURL) else {
            actionMessage = "服务器 URL 无效"
            return
        }
        isExtractingFacts = true
        actionMessage = nil
        defer { isExtractingFacts = false }
        do {
            let response = try await QcoworkClient(baseURL: url).extractFacts(area: selectedArea)
            actionMessage = response.facts.isEmpty ? "未抽取到新事实" : "已抽取 \(response.facts.count) 条事实"
            selectedKind = .atomicFact
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func evolveMemory() async {
        guard let url = URL(string: settings.serverURL) else {
            actionMessage = "服务器 URL 无效"
            return
        }
        isEvolving = true
        actionMessage = nil
        defer { isEvolving = false }
        do {
            let response = try await QcoworkClient(baseURL: url).evolveMemory(area: selectedArea)
            actionMessage = response.skills.isEmpty ? "未生成新案例" : "已演化 \(response.skills.count) 条案例"
            selectedKind = .caseMemory
            await load()
        } catch {
            actionMessage = error.localizedDescription
        }
    }

    func loadProfile() async {
        guard let url = URL(string: settings.serverURL) else {
            profileError = "服务器 URL 无效"
            return
        }
        isLoadingProfile = true
        profileError = nil
        defer { isLoadingProfile = false }
        do {
            let response = try await QcoworkClient(baseURL: url).fetchMemoryProfile(
                area: selectedArea,
                scope: normalizedProfileScope
            )
            profileText = response.profile
            profileScope = response.scope
        } catch {
            profileText = nil
            profileError = error.localizedDescription
        }
    }

    func synthesizeProfile() async {
        guard let url = URL(string: settings.serverURL) else {
            profileError = "服务器 URL 无效"
            return
        }
        isLoadingProfile = true
        profileError = nil
        actionMessage = nil
        defer { isLoadingProfile = false }
        do {
            let response = try await QcoworkClient(baseURL: url).synthesizeMemoryProfile(
                area: selectedArea,
                scope: normalizedProfileScope
            )
            profileText = response.profile
            profileScope = response.scope
            actionMessage = response.profile == nil ? "画像暂无可更新内容" : "画像已更新"
            selectedKind = .profile
            await load()
        } catch {
            profileError = error.localizedDescription
            actionMessage = error.localizedDescription
        }
    }

    private var normalizedProfileScope: String {
        let scope = profileScope.trimmingCharacters(in: .whitespacesAndNewlines)
        return scope.isEmpty ? "default" : scope
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
            let response = try await QcoworkClient(baseURL: url).fetchAccessLog()
            accessLogEntries = response.entries
            accessLogTotal = response.total
        } catch {
            accessLogEntries = []
            accessLogError = error.localizedDescription
        }
    }
}
