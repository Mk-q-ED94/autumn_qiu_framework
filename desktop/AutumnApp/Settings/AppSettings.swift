import Foundation
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    @Published var serverURL: String { didSet { _schedulePersist() } }
    @Published var routeMode: String { didSet { _schedulePersist() } }

    @Published var a1APIKey: String   { didSet { _schedulePersist() } }
    @Published var a1BaseURL: String  { didSet { _schedulePersist() } }
    @Published var a1Protocol: String { didSet { _schedulePersist() } }
    @Published var a1Model: String    { didSet { _schedulePersist() } }

    @Published var a2APIKey: String   { didSet { _schedulePersist() } }
    @Published var a2BaseURL: String  { didSet { _schedulePersist() } }
    @Published var a2Protocol: String { didSet { _schedulePersist() } }
    @Published var a2Model: String    { didSet { _schedulePersist() } }

    @Published var a3APIKey: String   { didSet { _schedulePersist() } }
    @Published var a3BaseURL: String  { didSet { _schedulePersist() } }
    @Published var a3Protocol: String { didSet { _schedulePersist() } }
    @Published var a3Model: String    { didSet { _schedulePersist() } }

    @Published var a4Enabled: Bool    { didSet { _schedulePersist() } }
    @Published var a4APIKey: String   { didSet { _schedulePersist() } }
    @Published var a4BaseURL: String  { didSet { _schedulePersist() } }
    @Published var a4Protocol: String { didSet { _schedulePersist() } }
    @Published var a4Model: String    { didSet { _schedulePersist() } }

    @Published private(set) var a1ModelState: ModelConnectionState = .unconfigured
    @Published private(set) var a2ModelState: ModelConnectionState = .unconfigured
    @Published private(set) var a3ModelState: ModelConnectionState = .unconfigured
    @Published private(set) var a4ModelState: ModelConnectionState = .unconfigured
    @Published var activeRouteOverride: String? = nil

    /// Platform-integration credentials, keyed `"<integration_id>.<field_key>"`
    /// (e.g. `"github.token"`). Stored locally; pushed to the server only when
    /// the user connects a platform.
    @Published var integrationCredentials: [String: String] { didSet { _schedulePersist() } }

    private static let serverURLKey  = "AutumnDesktop.serverURL"
    private static let routeModeKey  = "AutumnDesktop.routeMode"
    private static let a1APIKeyKey   = "AutumnDesktop.a1APIKey"
    private static let a1BaseURLKey  = "AutumnDesktop.a1BaseURL"
    private static let a1ProtocolKey = "AutumnDesktop.a1Protocol"
    private static let a1ModelKey    = "AutumnDesktop.a1Model"
    private static let a2APIKeyKey   = "AutumnDesktop.a2APIKey"
    private static let a2BaseURLKey  = "AutumnDesktop.a2BaseURL"
    private static let a2ProtocolKey = "AutumnDesktop.a2Protocol"
    private static let a2ModelKey    = "AutumnDesktop.a2Model"
    private static let a3APIKeyKey   = "AutumnDesktop.a3APIKey"
    private static let a3BaseURLKey  = "AutumnDesktop.a3BaseURL"
    private static let a3ProtocolKey = "AutumnDesktop.a3Protocol"
    private static let a3ModelKey    = "AutumnDesktop.a3Model"
    private static let a4EnabledKey  = "AutumnDesktop.a4Enabled"
    private static let a4APIKeyKey   = "AutumnDesktop.a4APIKey"
    private static let a4BaseURLKey  = "AutumnDesktop.a4BaseURL"
    private static let a4ProtocolKey = "AutumnDesktop.a4Protocol"
    private static let a4ModelKey    = "AutumnDesktop.a4Model"
    private static let integrationCredentialsKey = "AutumnDesktop.integrationCredentials"
    private static let defaultServerURL  = "http://127.0.0.1:8765"
    private static let openAIBaseURL     = "https://api.openai.com"
    private static let anthropicBaseURL  = "https://api.anthropic.com"
    private static let ollamaBaseURL     = "http://127.0.0.1:11434"

    private var _persistTask: Task<Void, Never>?

    init() {
        self.serverURL  = UserDefaults.standard.string(forKey: Self.serverURLKey) ?? Self.defaultServerURL
        self.routeMode  = UserDefaults.standard.string(forKey: Self.routeModeKey) ?? "auto"
        self.a1APIKey   = UserDefaults.standard.string(forKey: Self.a1APIKeyKey)  ?? ""
        self.a1BaseURL  = UserDefaults.standard.string(forKey: Self.a1BaseURLKey) ?? Self.openAIBaseURL
        self.a1Protocol = UserDefaults.standard.string(forKey: Self.a1ProtocolKey) ?? "openai"
        self.a1Model    = UserDefaults.standard.string(forKey: Self.a1ModelKey)   ?? "gpt-4o-mini"
        self.a2APIKey   = UserDefaults.standard.string(forKey: Self.a2APIKeyKey)  ?? ""
        self.a2BaseURL  = UserDefaults.standard.string(forKey: Self.a2BaseURLKey) ?? Self.anthropicBaseURL
        self.a2Protocol = UserDefaults.standard.string(forKey: Self.a2ProtocolKey) ?? "anthropic"
        self.a2Model    = UserDefaults.standard.string(forKey: Self.a2ModelKey)   ?? "claude-sonnet-4-5"
        self.a3APIKey   = UserDefaults.standard.string(forKey: Self.a3APIKeyKey)  ?? ""
        self.a3BaseURL  = UserDefaults.standard.string(forKey: Self.a3BaseURLKey) ?? Self.openAIBaseURL
        self.a3Protocol = UserDefaults.standard.string(forKey: Self.a3ProtocolKey) ?? "openai"
        self.a3Model    = UserDefaults.standard.string(forKey: Self.a3ModelKey)   ?? "gpt-4o"
        self.a4Enabled  = UserDefaults.standard.bool(forKey: Self.a4EnabledKey)
        self.a4APIKey   = UserDefaults.standard.string(forKey: Self.a4APIKeyKey)  ?? ""
        self.a4BaseURL  = Self.normalizedLocalOllamaBaseURL(
            UserDefaults.standard.string(forKey: Self.a4BaseURLKey) ?? Self.ollamaBaseURL
        )
        self.a4Protocol = UserDefaults.standard.string(forKey: Self.a4ProtocolKey) ?? "openai"
        self.a4Model    = UserDefaults.standard.string(forKey: Self.a4ModelKey)   ?? ""
        self.integrationCredentials = Self.loadIntegrationCredentials()
        refreshInitialModelStates()
    }

    // ── platform-integration credentials ───────────────────────────────────────

    func integrationValue(_ integrationID: String, _ fieldKey: String) -> String {
        integrationCredentials["\(integrationID).\(fieldKey)"] ?? ""
    }

    func setIntegrationValue(_ integrationID: String, _ fieldKey: String, _ value: String) {
        integrationCredentials["\(integrationID).\(fieldKey)"] = value
    }

    /// Collect the saved `{field_key: value}` map for a platform, dropping empties.
    func integrationArgs(for entry: IntegrationCatalogEntry) -> [String: String] {
        var args: [String: String] = [:]
        for field in entry.fields {
            let value = integrationValue(entry.id, field.key).trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty { args[field.key] = value }
        }
        return args
    }

    private static func loadIntegrationCredentials() -> [String: String] {
        guard let data = UserDefaults.standard.data(forKey: integrationCredentialsKey),
              let decoded = try? JSONDecoder().decode([String: String].self, from: data)
        else { return [:] }
        return decoded
    }

    func providerConfig(for slot: ModelSlot) -> ProviderConfigRequest {
        switch slot {
        case .a1:
            return ProviderConfigRequest(apiKey: a1APIKey, baseURL: a1BaseURL,
                                         model: a1Model, apiProtocol: a1Protocol)
        case .a2:
            return ProviderConfigRequest(apiKey: a2APIKey, baseURL: a2BaseURL,
                                         model: a2Model, apiProtocol: a2Protocol)
        case .a3:
            return ProviderConfigRequest(apiKey: a3APIKey, baseURL: a3BaseURL,
                                         model: a3Model, apiProtocol: a3Protocol)
        }
    }

    func applyConfigRequest() -> ApplyConfigRequest {
        let a4Key = a4APIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let a4ModelName = a4Model.trimmingCharacters(in: .whitespacesAndNewlines)
        let a4Config: ProviderConfigRequest? = (a4Enabled && !a4ModelName.isEmpty)
            ? ProviderConfigRequest(
                apiKey: a4Key.isEmpty ? "ollama" : a4Key,
                baseURL: a4BaseURL,
                model: a4ModelName,
                apiProtocol: a4Protocol
            )
            : nil
        return ApplyConfigRequest(
            a1: providerConfig(for: .a1),
            a2: providerConfig(for: .a2),
            a3: providerConfig(for: .a3),
            a4: a4Config
        )
    }

    /// True when at least one slot has API key + base URL + model populated.
    var anyModelConfigured: Bool {
        ModelSlot.allCases.contains { slot in
            let cfg = providerConfig(for: slot)
            return !cfg.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !cfg.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !(cfg.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    /// True when ALL three slots are populated (A1 + A2 + A3).
    var allModelsConfigured: Bool {
        ModelSlot.allCases.allSatisfy { slot in
            let cfg = providerConfig(for: slot)
            return !cfg.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !cfg.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !(cfg.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    func modelState(for slot: ModelSlot) -> ModelConnectionState {
        switch slot {
        case .a1: return a1ModelState
        case .a2: return a2ModelState
        case .a3: return a3ModelState
        }
    }

    func setModelState(_ state: ModelConnectionState, for slot: ModelSlot) {
        switch slot {
        case .a1: a1ModelState = state
        case .a2: a2ModelState = state
        case .a3: a3ModelState = state
        }
    }

    private func refreshInitialModelStates() {
        for slot in ModelSlot.allCases {
            let cfg = providerConfig(for: slot)
            let configured = !cfg.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !cfg.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !(cfg.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            setModelState(configured ? .ready : .unconfigured, for: slot)
        }
        let a4Configured = a4Enabled
            && !a4APIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !a4BaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !a4Model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        a4ModelState = a4Configured ? .ready : .unconfigured
    }

    // ── debounced persistence ─────────────────────────────────────────────────

    private func _schedulePersist() {
        _persistTask?.cancel()
        _persistTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled, let self else { return }
            self._flush()
        }
    }

    private func _flush() {
        let ud = UserDefaults.standard
        ud.set(serverURL,  forKey: Self.serverURLKey)
        ud.set(routeMode,  forKey: Self.routeModeKey)
        ud.set(a1APIKey,   forKey: Self.a1APIKeyKey)
        ud.set(a1BaseURL,  forKey: Self.a1BaseURLKey)
        ud.set(a1Protocol, forKey: Self.a1ProtocolKey)
        ud.set(a1Model,    forKey: Self.a1ModelKey)
        ud.set(a2APIKey,   forKey: Self.a2APIKeyKey)
        ud.set(a2BaseURL,  forKey: Self.a2BaseURLKey)
        ud.set(a2Protocol, forKey: Self.a2ProtocolKey)
        ud.set(a2Model,    forKey: Self.a2ModelKey)
        ud.set(a3APIKey,   forKey: Self.a3APIKeyKey)
        ud.set(a3BaseURL,  forKey: Self.a3BaseURLKey)
        ud.set(a3Protocol, forKey: Self.a3ProtocolKey)
        ud.set(a3Model,    forKey: Self.a3ModelKey)
        ud.set(a4Enabled,  forKey: Self.a4EnabledKey)
        ud.set(a4APIKey,   forKey: Self.a4APIKeyKey)
        ud.set(a4BaseURL,  forKey: Self.a4BaseURLKey)
        ud.set(a4Protocol, forKey: Self.a4ProtocolKey)
        ud.set(a4Model,    forKey: Self.a4ModelKey)
        if let data = try? JSONEncoder().encode(integrationCredentials) {
            ud.set(data, forKey: Self.integrationCredentialsKey)
        }
    }

    private static func normalizedLocalOllamaBaseURL(_ rawValue: String) -> String {
        let original = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        var value = original
        if value.isEmpty {
            value = Self.ollamaBaseURL
        }
        if !value.contains("://") {
            value = "http://\(value)"
        }
        guard var components = URLComponents(string: value) else {
            return rawValue
        }
        let host = components.host?.lowercased()
        guard host == "localhost" || host == "127.0.0.1" || host == "::1" else {
            return original.isEmpty ? Self.ollamaBaseURL : original
        }
        if components.path == "/v1" || components.path == "/api" {
            components.path = ""
        }
        if host == "localhost" || host == "::1" {
            components.host = "127.0.0.1"
        }
        return components.url?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            ?? rawValue
    }
}

enum ModelConnectionState: String, Equatable {
    case unconfigured
    case connecting
    case ready
    case failed

    var title: String {
        switch self {
        case .unconfigured: return "未配置"
        case .connecting:   return "连接中"
        case .ready:        return "就绪"
        case .failed:       return "失败"
        }
    }

    var tone: AutumnBadge.Tone {
        switch self {
        case .unconfigured: return .neutral
        case .connecting:   return .warning
        case .ready:        return .success
        case .failed:       return .danger
        }
    }
}

enum ModelSlot: String, CaseIterable, Identifiable {
    case a1
    case a2
    case a3

    var id: String { rawValue }

    var title: String {
        switch self {
        case .a1: return "A1 / WP1"
        case .a2: return "A2 / WP2"
        case .a3: return "A3 / WP3"
        }
    }

    var subtitle: String {
        switch self {
        case .a1: return "路由与总检"
        case .a2: return "任务执行"
        case .a3: return "Mission 与转换"
        }
    }
}
