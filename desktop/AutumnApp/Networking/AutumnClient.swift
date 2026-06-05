import Foundation

enum AutumnClientError: LocalizedError {
    case invalidURL
    case badStatus(Int)
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "服务器 URL 无效"
        case .badStatus(let code): return "HTTP 状态码: \(code)"
        case .serverError(let msg): return msg
        }
    }
}

final class AutumnClient {
    let baseURL: URL

    init(baseURL: URL) {
        self.baseURL = baseURL
    }

    func health() async -> HealthResponse? {
        var request = URLRequest(url: baseURL.appendingPathComponent("health"))
        request.timeoutInterval = 3
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse, http.statusCode == 200
        else {
            return nil
        }
        return try? JSONDecoder().decode(HealthResponse.self, from: data)
    }

    func fetchModels(apiKey: String, baseURL: String, apiProtocol: String) async throws -> [String] {
        var request = URLRequest(url: self.baseURL.appendingPathComponent("models"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 45
        request.httpBody = try JSONEncoder().encode(
            ModelsRequest(apiKey: apiKey, baseURL: baseURL, apiProtocol: apiProtocol)
        )

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
        return try JSONDecoder().decode(ModelsResponse.self, from: data).models
    }

    func applyConfiguration(_ config: ApplyConfigRequest) async throws -> ApplyConfigResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("config/apply"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        request.httpBody = try JSONEncoder().encode(config)

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
        return try JSONDecoder().decode(ApplyConfigResponse.self, from: data)
    }

    func process(_ input: String, route: String? = nil) async throws -> String {
        var request = URLRequest(url: baseURL.appendingPathComponent("process"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(ProcessRequest(input: input, route: route))
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
        return try JSONDecoder().decode(ProcessResponse.self, from: data).output
    }

    func trace(_ input: String, route: String? = nil) async throws -> WorkflowTrace {
        var request = URLRequest(url: baseURL.appendingPathComponent("trace"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300
        request.httpBody = try JSONEncoder().encode(ProcessRequest(input: input, route: route))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
        return try JSONDecoder().decode(WorkflowTrace.self, from: data)
    }

    func stream(_ input: String, route: String? = nil) -> AsyncThrowingStream<String, Error> {
        let baseURL = self.baseURL

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var components = URLComponents(
                        url: baseURL.appendingPathComponent("stream"),
                        resolvingAgainstBaseURL: false
                    )!
                    var queryItems = [URLQueryItem(name: "input", value: input)]
                    if let route {
                        queryItems.append(URLQueryItem(name: "route", value: route))
                    }
                    components.queryItems = queryItems
                    guard let url = components.url else {
                        throw AutumnClientError.invalidURL
                    }

                    var request = URLRequest(url: url)
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.timeoutInterval = 300

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    try Self.requireOK(response)

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard line.hasPrefix("data: ") else { continue }
                        let payload = String(line.dropFirst("data: ".count))
                        if payload == "[DONE]" {
                            continuation.finish()
                            return
                        }
                        guard let data = payload.data(using: .utf8),
                              let event = try? JSONDecoder().decode(StreamPayload.self, from: data)
                        else { continue }

                        if let err = event.error {
                            throw AutumnClientError.serverError(err)
                        }
                        if let chunk = event.chunk {
                            continuation.yield(chunk)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func endSession() async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("session/end"))
        request.httpMethod = "POST"
        let (_, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
    }

    func memoryHistory(area: MemoryArea) async throws -> [MemoryEntry] {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/\(area.rawValue)/history"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response)
        let payload = try JSONDecoder().decode([[String: JSONValue]].self, from: data)
        return payload.map { MemoryEntry(area: area, values: $0) }
    }

    private static func requireOK(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw AutumnClientError.badStatus(-1)
        }
        guard (200..<300).contains(http.statusCode) else {
            throw AutumnClientError.badStatus(http.statusCode)
        }
    }
}
