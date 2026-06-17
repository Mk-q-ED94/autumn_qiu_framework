import Foundation

@MainActor
final class TerrsViewModel: ObservableObject {
    @Published var terrs: [TerrSummary] = []
    @Published var catalog: [KnownMCP] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    /// Name of the Terr whose toggle is mid-flight, so its row can show a spinner.
    @Published var togglingName: String?

    /// Live connection state per catalog MCP id, from `GET /mcps/status`.
    @Published var mcpStatuses: [String: IntegrationStatus] = [:]
    /// Catalog MCP ids whose connect/disconnect is mid-flight.
    @Published var connectingMCPs: Set<String> = []
    /// Per-MCP connect error (cleared on the next attempt).
    @Published var mcpErrors: [String: String] = [:]

    let settings: AppSettings

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
        await refreshMCPStatus(client: client)
    }

    /// Pull live connection state for the whole catalog (best-effort; an older
    /// server without /mcps/status simply leaves everything "not connected").
    func refreshMCPStatus(client: AutumnClient? = nil) async {
        guard let client = client ?? makeClient() else { return }
        if let statuses = try? await client.mcpStatus() {
            mcpStatuses = Dictionary(statuses.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
        }
    }

    func status(for mcp: KnownMCP) -> IntegrationStatus? { mcpStatuses[mcp.id] }
    func isConnecting(_ mcp: KnownMCP) -> Bool { connectingMCPs.contains(mcp.id) }

    /// Bring an MCP online with the values saved in settings.
    func connectMCP(_ mcp: KnownMCP, writeEnabled: Bool) async {
        guard let client = makeClient() else { return }
        mcpErrors[mcp.id] = nil
        connectingMCPs.insert(mcp.id)
        defer { connectingMCPs.remove(mcp.id) }
        do {
            let status = try await client.connectMcp(
                id: mcp.id,
                args: settings.mcpArgs(for: mcp),
                writeEnabled: writeEnabled
            )
            mcpStatuses[mcp.id] = status
            // A new Terr appeared on the server — refresh the registered list.
            await reloadTerrs(client: client)
        } catch {
            mcpErrors[mcp.id] = error.localizedDescription
            await refreshMCPStatus(client: client)
        }
    }

    func disconnectMCP(_ mcp: KnownMCP) async {
        guard let client = makeClient() else { return }
        mcpErrors[mcp.id] = nil
        connectingMCPs.insert(mcp.id)
        defer { connectingMCPs.remove(mcp.id) }
        do {
            let status = try await client.disconnectMcp(id: mcp.id)
            mcpStatuses[mcp.id] = status
            await reloadTerrs(client: client)
        } catch {
            mcpErrors[mcp.id] = error.localizedDescription
            await refreshMCPStatus(client: client)
        }
    }

    /// Refresh just the registered-Terr list (after a connect/disconnect adds or
    /// removes an `integration:<id>` Terr), leaving catalog/status intact.
    private func reloadTerrs(client: AutumnClient) async {
        if let updated = try? await client.fetchTerrs() {
            terrs = updated
        }
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
