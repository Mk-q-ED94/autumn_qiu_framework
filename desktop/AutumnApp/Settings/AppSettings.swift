import Foundation
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: Self.serverURLKey) }
    }

    @Published var routeMode: String {
        didSet { UserDefaults.standard.set(routeMode, forKey: Self.routeModeKey) }
    }

    @Published var a1APIKey: String {
        didSet { UserDefaults.standard.set(a1APIKey, forKey: Self.a1APIKeyKey) }
    }

    @Published var a1BaseURL: String {
        didSet { UserDefaults.standard.set(a1BaseURL, forKey: Self.a1BaseURLKey) }
    }

    @Published var a1Protocol: String {
        didSet { UserDefaults.standard.set(a1Protocol, forKey: Self.a1ProtocolKey) }
    }

    @Published var a1Model: String {
        didSet { UserDefaults.standard.set(a1Model, forKey: Self.a1ModelKey) }
    }

    @Published var a2APIKey: String {
        didSet { UserDefaults.standard.set(a2APIKey, forKey: Self.a2APIKeyKey) }
    }

    @Published var a2BaseURL: String {
        didSet { UserDefaults.standard.set(a2BaseURL, forKey: Self.a2BaseURLKey) }
    }

    @Published var a2Protocol: String {
        didSet { UserDefaults.standard.set(a2Protocol, forKey: Self.a2ProtocolKey) }
    }

    @Published var a2Model: String {
        didSet { UserDefaults.standard.set(a2Model, forKey: Self.a2ModelKey) }
    }

    @Published var a3APIKey: String {
        didSet { UserDefaults.standard.set(a3APIKey, forKey: Self.a3APIKeyKey) }
    }

    @Published var a3BaseURL: String {
        didSet { UserDefaults.standard.set(a3BaseURL, forKey: Self.a3BaseURLKey) }
    }

    @Published var a3Protocol: String {
        didSet { UserDefaults.standard.set(a3Protocol, forKey: Self.a3ProtocolKey) }
    }

    @Published var a3Model: String {
        didSet { UserDefaults.standard.set(a3Model, forKey: Self.a3ModelKey) }
    }

    private static let serverURLKey = "AutumnDesktop.serverURL"
    private static let routeModeKey = "AutumnDesktop.routeMode"
    private static let a1APIKeyKey = "AutumnDesktop.a1APIKey"
    private static let a1BaseURLKey = "AutumnDesktop.a1BaseURL"
    private static let a1ProtocolKey = "AutumnDesktop.a1Protocol"
    private static let a1ModelKey = "AutumnDesktop.a1Model"
    private static let a2APIKeyKey = "AutumnDesktop.a2APIKey"
    private static let a2BaseURLKey = "AutumnDesktop.a2BaseURL"
    private static let a2ProtocolKey = "AutumnDesktop.a2Protocol"
    private static let a2ModelKey = "AutumnDesktop.a2Model"
    private static let a3APIKeyKey = "AutumnDesktop.a3APIKey"
    private static let a3BaseURLKey = "AutumnDesktop.a3BaseURL"
    private static let a3ProtocolKey = "AutumnDesktop.a3Protocol"
    private static let a3ModelKey = "AutumnDesktop.a3Model"
    private static let defaultServerURL = "http://127.0.0.1:8765"
    private static let openAIBaseURL = "https://api.openai.com"
    private static let anthropicBaseURL = "https://api.anthropic.com"

    init() {
        self.serverURL =
            UserDefaults.standard.string(forKey: Self.serverURLKey) ?? Self.defaultServerURL
        self.routeMode = UserDefaults.standard.string(forKey: Self.routeModeKey) ?? "auto"
        self.a1APIKey = UserDefaults.standard.string(forKey: Self.a1APIKeyKey) ?? ""
        self.a1BaseURL = UserDefaults.standard.string(forKey: Self.a1BaseURLKey) ?? Self.openAIBaseURL
        self.a1Protocol = UserDefaults.standard.string(forKey: Self.a1ProtocolKey) ?? "openai"
        self.a1Model = UserDefaults.standard.string(forKey: Self.a1ModelKey) ?? "gpt-4o-mini"
        self.a2APIKey = UserDefaults.standard.string(forKey: Self.a2APIKeyKey) ?? ""
        self.a2BaseURL = UserDefaults.standard.string(forKey: Self.a2BaseURLKey) ?? Self.anthropicBaseURL
        self.a2Protocol = UserDefaults.standard.string(forKey: Self.a2ProtocolKey) ?? "anthropic"
        self.a2Model = UserDefaults.standard.string(forKey: Self.a2ModelKey) ?? "claude-sonnet-4-5"
        self.a3APIKey = UserDefaults.standard.string(forKey: Self.a3APIKeyKey) ?? ""
        self.a3BaseURL = UserDefaults.standard.string(forKey: Self.a3BaseURLKey) ?? Self.openAIBaseURL
        self.a3Protocol = UserDefaults.standard.string(forKey: Self.a3ProtocolKey) ?? "openai"
        self.a3Model = UserDefaults.standard.string(forKey: Self.a3ModelKey) ?? "gpt-4o"
    }

    func providerConfig(for slot: ModelSlot) -> ProviderConfigRequest {
        switch slot {
        case .a1:
            return ProviderConfigRequest(
                apiKey: a1APIKey,
                baseURL: a1BaseURL,
                model: a1Model,
                apiProtocol: a1Protocol
            )
        case .a2:
            return ProviderConfigRequest(
                apiKey: a2APIKey,
                baseURL: a2BaseURL,
                model: a2Model,
                apiProtocol: a2Protocol
            )
        case .a3:
            return ProviderConfigRequest(
                apiKey: a3APIKey,
                baseURL: a3BaseURL,
                model: a3Model,
                apiProtocol: a3Protocol
            )
        }
    }

    func applyConfigRequest() -> ApplyConfigRequest {
        ApplyConfigRequest(
            a1: providerConfig(for: .a1),
            a2: providerConfig(for: .a2),
            a3: providerConfig(for: .a3)
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
