import Foundation

/// Model context-window limits and token estimation.
enum ContextLimit {

    // ── per-model context sizes (tokens) ─────────────────────────────────────

    static func limit(for model: String) -> Int {
        let m = model.lowercased()

        // Gemini
        if m.contains("gemini-2")                          { return 2_097_152 }
        if m.contains("gemini-1.5")                        { return 1_048_576 }
        if m.contains("gemini")                            { return 32_768 }

        // Claude (Anthropic)
        if m.contains("claude")                            { return 200_000 }

        // GPT-4o / GPT-4 Turbo
        if m.contains("gpt-4o")                            { return 128_000 }
        if m.contains("gpt-4-turbo") || m.contains("gpt-4-1106") || m.contains("gpt-4-0125") {
            return 128_000
        }
        if m.contains("gpt-4")                             { return 8_192 }

        // GPT-3.5
        if m.contains("gpt-3.5-turbo-16k")                { return 16_385 }
        if m.contains("gpt-3.5")                          { return 16_385 }

        // DeepSeek
        if m.contains("deepseek-r1")                       { return 65_536 }
        if m.contains("deepseek")                          { return 128_000 }

        // Qwen
        if m.contains("qwen2.5") || m.contains("qwen-max") { return 131_072 }
        if m.contains("qwen")                              { return 32_768 }

        // Mistral / Mixtral
        if m.contains("mistral-large") || m.contains("mistral-medium") { return 128_000 }
        if m.contains("mixtral")                           { return 32_768 }
        if m.contains("mistral")                           { return 32_768 }

        // Llama
        if m.contains("llama-3") || m.contains("llama3")  { return 128_000 }
        if m.contains("llama")                             { return 8_192 }

        // Moonshot
        if m.contains("moonshot-v1-128k")                  { return 131_072 }
        if m.contains("moonshot")                          { return 32_768 }

        // GLM (智谱)
        if m.contains("glm-4")                             { return 128_000 }
        if m.contains("glm")                               { return 32_768 }

        // Qwen (通义)
        if m.contains("qwq") || m.contains("qwen-long")   { return 131_072 }

        return 8_192  // conservative default
    }

    // ── fast token estimation ─────────────────────────────────────────────────

    /// Rough estimate: 4 characters per token on average.
    static func estimateTokens(_ text: String) -> Int {
        max(1, text.count / 4)
    }

    // ── formatting ────────────────────────────────────────────────────────────

    static func format(_ count: Int) -> String {
        if count >= 1_000 {
            let k = Double(count) / 1000.0
            if k >= 100 { return "\(Int(k.rounded()))k" }
            return String(format: "%.1fk", k)
        }
        return "\(count)"
    }
}
