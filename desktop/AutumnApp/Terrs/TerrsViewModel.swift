import Foundation

@MainActor
final class TerrsViewModel: ObservableObject {
    @Published var terrs: [TerrSummary] = []
    @Published var catalog: [KnownMCP] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    /// Name of the Terr whose toggle is mid-flight, so its row can show a spinner.
    @Published var togglingName: String?

    private let settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
    }

    private func makeClient() -> AutumnClient? {
        guard let url = URL(string: settings.serverURL) else {
            errorMessage = "服务器 URL 无效"
            return nil
        }
        return AutumnClient(baseURL: url)
    }

    func load() async {
        guard let client = makeClient() else { return }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            terrs = try await client.fetchTerrs()
        } catch {
            terrs = []
            errorMessage = error.localizedDescription
            return
        }

        // The MCP catalog is best-effort: an older server without /mcps/catalog
        // shouldn't blank out the registered-Terr list.
        catalog = (try? await client.mcpCatalog()) ?? []
    }

    func setEnabled(_ terr: TerrSummary, enabled: Bool) async {
        guard let client = makeClient() else { return }

        togglingName = terr.name
        defer { togglingName = nil }

        do {
            let updated = try await client.setTerrEnabled(name: terr.name, enabled: enabled)
            if let index = terrs.firstIndex(where: { $0.name == updated.name }) {
                terrs[index] = updated
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var enabledCount: Int { terrs.filter(\.enabled).count }
    var toolCount: Int { terrs.reduce(0) { $0 + $1.tools.count } }
    var skillCount: Int { terrs.reduce(0) { $0 + $1.skills.count } }
    var mcpCount: Int { terrs.reduce(0) { $0 + $1.mcps.count } }
}
