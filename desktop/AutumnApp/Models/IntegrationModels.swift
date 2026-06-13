import Foundation

// ── Platform integrations ────────────────────────────────────────────────────────
//
// A platform (GitHub, GitLab, Slack, …) the agent can be granted access to by
// saving a credential. The server starts the matching MCP server and registers
// its tools, so once connected the agent reads/edits that platform on its own.

/// One input field in a platform's credential form (e.g. GitHub → token).
struct IntegrationField: Decodable, Identifiable, Equatable {
    let key: String
    let label: String
    let secret: Bool
    let optional: Bool

    var id: String { key }

    init(key: String, label: String, secret: Bool = false, optional: Bool = false) {
        self.key = key
        self.label = label
        self.secret = secret
        self.optional = optional
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = try c.decode(String.self, forKey: .label)
        secret = try c.decodeIfPresent(Bool.self, forKey: .secret) ?? false
        optional = try c.decodeIfPresent(Bool.self, forKey: .optional) ?? false
    }

    private enum CodingKeys: String, CodingKey {
        case key, label, secret, optional
    }
}

/// A connectable platform from `GET /integrations/catalog` — secret-free; drives
/// the Settings input form.
struct IntegrationCatalogEntry: Decodable, Identifiable, Equatable {
    let id: String
    let name: String
    let description: String
    let fields: [IntegrationField]
}

/// Per-platform connection state from `GET /integrations/status`.
struct IntegrationStatus: Decodable, Identifiable, Equatable {
    let id: String
    let name: String
    let connected: Bool
    let toolCount: Int
    let error: String?

    init(id: String, name: String, connected: Bool, toolCount: Int = 0, error: String? = nil) {
        self.id = id
        self.name = name
        self.connected = connected
        self.toolCount = toolCount
        self.error = error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        connected = try c.decode(Bool.self, forKey: .connected)
        toolCount = try c.decodeIfPresent(Int.self, forKey: .toolCount) ?? 0
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }

    enum CodingKeys: String, CodingKey {
        case id, name, connected, error
        case toolCount = "tool_count"
    }
}

/// Request body for `POST /integrations/connect`.
struct IntegrationConnectBody: Encodable {
    let id: String
    let args: [String: String]
}
