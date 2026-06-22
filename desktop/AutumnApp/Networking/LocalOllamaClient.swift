import Foundation

final class LocalOllamaClient {
    let baseURL: URL

    init(baseURL rawValue: String) throws {
        guard let baseURL = Self.normalizedBaseURL(from: rawValue) else {
            throw QcoworkClientError.invalidURL
        }
        self.baseURL = baseURL
    }

    func status() async -> OllamaStatus {
        let url = baseURL.appendingPathComponent("api/version")
        var request = URLRequest(url: url)
        request.timeoutInterval = 3

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return unavailable("Ollama 返回了无效响应")
            }
            guard (200..<300).contains(http.statusCode) else {
                let detail = Self.responseText(data)
                return unavailable("Ollama HTTP \(http.statusCode)\(detail)")
            }
            let version = try? JSONDecoder().decode(OllamaVersionResponse.self, from: data).version
            return OllamaStatus(
                running: true,
                baseURL: displayBaseURL,
                version: version,
                error: nil
            )
        } catch {
            return unavailable(error.localizedDescription)
        }
    }

    func models() async throws -> [OllamaModel] {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/tags"))
        request.timeoutInterval = 10

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        let payload = try JSONDecoder().decode(LocalOllamaTagsResponse.self, from: data)
        return payload.models.compactMap { item in
            guard let name = item.name ?? item.model else { return nil }
            return OllamaModel(
                name: name,
                size: item.size,
                parameterSize: item.details?.parameterSize,
                family: item.details?.family,
                modifiedAt: item.modifiedAt
            )
        }
    }

    func pullModel(name: String) -> AsyncThrowingStream<OllamaPullEvent, Error> {
        let baseURL = self.baseURL
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: baseURL.appendingPathComponent("api/pull"))
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.timeoutInterval = 600
                    request.httpBody = try JSONEncoder().encode(
                        LocalOllamaPullRequest(name: name, model: name, stream: true)
                    )

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    try Self.requireOK(response)

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        let payload = line.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !payload.isEmpty, let data = payload.data(using: .utf8) else {
                            continue
                        }
                        let event = try JSONDecoder().decode(OllamaPullEvent.self, from: data)
                        if let error = event.error {
                            throw QcoworkClientError.serverError(error)
                        }
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static func normalizedBaseURL(from rawValue: String) -> URL? {
        var value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            value = "http://127.0.0.1:11434"
        }
        if !value.contains("://") {
            value = "http://\(value)"
        }

        guard var components = URLComponents(string: value) else { return nil }
        if components.path == "/v1" || components.path == "/api" {
            components.path = ""
        }
        if components.host?.lowercased() == "localhost" || components.host == "::1" {
            components.host = "127.0.0.1"
        }
        return components.url
    }

    private var displayBaseURL: String {
        var value = baseURL.absoluteString
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }

    private func unavailable(_ message: String) -> OllamaStatus {
        OllamaStatus(
            running: false,
            baseURL: displayBaseURL,
            version: nil,
            error: message
        )
    }

    private static func requireOK(_ response: URLResponse, data: Data? = nil) throws {
        guard let http = response as? HTTPURLResponse else {
            throw QcoworkClientError.serverError("无效响应")
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = data.map(Self.responseText) ?? ""
            throw QcoworkClientError.serverError("Ollama HTTP \(http.statusCode)\(detail)")
        }
    }

    private static func responseText(_ data: Data) -> String {
        let raw = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return raw.isEmpty ? "" : ": \(raw.prefix(240))"
    }
}

private struct OllamaVersionResponse: Decodable {
    let version: String?
}

private struct LocalOllamaTagsResponse: Decodable {
    let models: [LocalOllamaModel]
}

private struct LocalOllamaModel: Decodable {
    let name: String?
    let model: String?
    let size: Int?
    let modifiedAt: String?
    let details: Details?

    enum CodingKeys: String, CodingKey {
        case name, model, size, details
        case modifiedAt = "modified_at"
    }

    struct Details: Decodable {
        let parameterSize: String?
        let family: String?

        enum CodingKeys: String, CodingKey {
            case parameterSize = "parameter_size"
            case family
        }
    }
}

private struct LocalOllamaPullRequest: Encodable {
    let name: String
    let model: String
    let stream: Bool
}
