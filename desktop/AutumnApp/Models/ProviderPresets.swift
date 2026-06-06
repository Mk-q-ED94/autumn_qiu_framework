import Foundation

/// A preset for a known model provider — base URL + protocol + URL patterns for auto-detection.
struct ProviderPreset: Identifiable, Hashable {
    let id: String
    let name: String
    let baseURL: String
    let apiProtocol: String
    let urlPatterns: [String]
    let note: String?
}

enum ProviderPresets {
    static let all: [ProviderPreset] = [
        ProviderPreset(
            id: "openai", name: "OpenAI",
            baseURL: "https://api.openai.com",
            apiProtocol: "openai",
            urlPatterns: ["api.openai.com"],
            note: nil
        ),
        ProviderPreset(
            id: "anthropic", name: "Anthropic",
            baseURL: "https://api.anthropic.com",
            apiProtocol: "anthropic",
            urlPatterns: ["api.anthropic.com"],
            note: nil
        ),
        ProviderPreset(
            id: "deepseek", name: "DeepSeek",
            baseURL: "https://api.deepseek.com",
            apiProtocol: "openai",
            urlPatterns: ["deepseek.com"],
            note: nil
        ),
        ProviderPreset(
            id: "openrouter", name: "OpenRouter",
            baseURL: "https://openrouter.ai/api",
            apiProtocol: "openai",
            urlPatterns: ["openrouter.ai"],
            note: "聚合多家模型"
        ),
        ProviderPreset(
            id: "siliconflow", name: "硅基流动",
            baseURL: "https://api.siliconflow.cn",
            apiProtocol: "openai",
            urlPatterns: ["siliconflow"],
            note: nil
        ),
        ProviderPreset(
            id: "moonshot", name: "Moonshot 月之暗面",
            baseURL: "https://api.moonshot.cn",
            apiProtocol: "openai",
            urlPatterns: ["moonshot.cn"],
            note: nil
        ),
        ProviderPreset(
            id: "zhipu", name: "智谱 BigModel",
            baseURL: "https://open.bigmodel.cn/api/paas",
            apiProtocol: "openai",
            urlPatterns: ["bigmodel.cn"],
            note: nil
        ),
        ProviderPreset(
            id: "dashscope", name: "通义千问 DashScope",
            baseURL: "https://dashscope.aliyuncs.com/compatible-mode",
            apiProtocol: "openai",
            urlPatterns: ["dashscope"],
            note: "阿里云"
        ),
        ProviderPreset(
            id: "ollama", name: "Ollama 本地",
            baseURL: "http://localhost:11434",
            apiProtocol: "openai",
            urlPatterns: ["localhost:11434", "127.0.0.1:11434"],
            note: "OpenAI 兼容接口"
        ),
        ProviderPreset(
            id: "hermes", name: "Hermes 本地",
            baseURL: "http://localhost:11434",
            apiProtocol: "hermes",
            urlPatterns: [],
            note: "Nous Hermes XML tool-use"
        ),
    ]

    /// Detect a preset by base URL substring. Returns nil if no pattern matches.
    /// Hermes is intentionally not in the auto-detect list — its URL is identical
    /// to Ollama, so it must be selected manually.
    static func detect(baseURL: String) -> ProviderPreset? {
        let url = baseURL.lowercased()
        return all.first { preset in
            preset.urlPatterns.contains { pattern in url.contains(pattern) }
        }
    }

    /// Detect just the protocol from a URL. Falls back to "openai".
    static func detectProtocol(baseURL: String) -> String {
        detect(baseURL: baseURL)?.apiProtocol ?? "openai"
    }
}
