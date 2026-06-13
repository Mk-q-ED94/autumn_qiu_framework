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
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ModelsResponse.self, from: data).models
    }

    func applyConfiguration(_ config: ApplyConfigRequest) async throws -> ApplyConfigResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("config/apply"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        request.httpBody = try JSONEncoder().encode(config)

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ApplyConfigResponse.self, from: data)
    }

    func process(
        _ input: String,
        route: String? = nil,
        inputType: String? = nil,
        taskType: String? = nil,
        projectInstructions: String? = nil,
        projectID: String? = nil
    ) async throws -> String {
        var request = URLRequest(url: baseURL.appendingPathComponent("process"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            ProcessRequest(
                input: input, route: route, inputType: inputType, taskType: taskType,
                projectInstructions: projectInstructions, projectID: projectID
            )
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProcessResponse.self, from: data).output
    }

    func trace(
        _ input: String,
        route: String? = nil,
        inputType: String? = nil,
        taskType: String? = nil,
        projectInstructions: String? = nil,
        projectID: String? = nil
    ) async throws -> WorkflowTrace {
        var request = URLRequest(url: baseURL.appendingPathComponent("trace"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 300
        request.httpBody = try JSONEncoder().encode(
            ProcessRequest(
                input: input, route: route, inputType: inputType, taskType: taskType,
                projectInstructions: projectInstructions, projectID: projectID
            )
        )

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(WorkflowTrace.self, from: data)
    }

    func previewIntent(
        _ input: String,
        route: String? = nil,
        inputType: String? = nil,
        taskType: String? = nil,
        projectInstructions: String? = nil,
        projectID: String? = nil
    ) async throws -> IntentPreview {
        var request = URLRequest(url: baseURL.appendingPathComponent("intent"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 45
        request.httpBody = try JSONEncoder().encode(
            ProcessRequest(
                input: input, route: route, inputType: inputType, taskType: taskType,
                projectInstructions: projectInstructions, projectID: projectID
            )
        )

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(IntentPreview.self, from: data)
    }

    func stream(
        _ input: String,
        route: String? = nil,
        inputType: String? = nil,
        taskType: String? = nil,
        projectInstructions: String? = nil,
        projectID: String? = nil
    ) -> AsyncThrowingStream<StreamEvent, Error> {
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
                    if let inputType {
                        queryItems.append(URLQueryItem(name: "input_type", value: inputType))
                    }
                    if let taskType {
                        queryItems.append(URLQueryItem(name: "task_type", value: taskType))
                    }
                    if let projectInstructions, !projectInstructions.isEmpty {
                        queryItems.append(URLQueryItem(
                            name: "project_instructions",
                            value: projectInstructions
                        ))
                    }
                    if let projectID, !projectID.isEmpty {
                        queryItems.append(URLQueryItem(name: "project_id", value: projectID))
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
                            continuation.yield(.chunk(chunk))
                        }
                        if let trace = event.trace {
                            continuation.yield(.trace(trace))
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

    func fetchTerrs() async throws -> [TerrSummary] {
        var request = URLRequest(url: baseURL.appendingPathComponent("terrs"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode([TerrSummary].self, from: data)
    }

    func setTerrEnabled(name: String, enabled: Bool) async throws -> TerrSummary {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("terrs")
                .appendingPathComponent(name)
        )
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        request.httpBody = try JSONEncoder().encode(TerrToggleRequest(enabled: enabled))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(TerrSummary.self, from: data)
    }

    func mcpCatalog() async throws -> [KnownMCP] {
        var request = URLRequest(url: baseURL.appendingPathComponent("mcps/catalog"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode([KnownMCP].self, from: data)
    }

    func endSession() async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("session/end"))
        request.httpMethod = "POST"
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
    }

    func memoryHistory(area: MemoryArea) async throws -> [MemoryEntry] {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/\(area.rawValue)/history"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        let payload = try JSONDecoder().decode([[String: JSONValue]].self, from: data)
        return payload.map { MemoryEntry(area: area, values: $0) }
    }

    func memoryStats(area: MemoryArea) async throws -> MemoryStats {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/\(area.rawValue)/stats"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(MemoryStats.self, from: data)
    }

    func memoryStatsOverview() async throws -> MemoryStatsOverview {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/stats"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(MemoryStatsOverview.self, from: data)
    }

    func fetch4DStatus() async throws -> FourDStatus {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/4d/status"))
        request.timeoutInterval = 15
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(FourDStatus.self, from: data)
    }

    func pushPreview(area: MemoryArea, query: String) async throws -> PushPreviewResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/push/preview"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        request.httpBody = try JSONEncoder().encode(
            PushPreviewRequestBody(area: area.rawValue, query: query, k: 5)
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(PushPreviewResponse.self, from: data)
    }

    @discardableResult
    func annotateMemory(
        area: MemoryArea, entryID: String,
        mode: String?, intent: String?, cues: [String]?
    ) async throws -> AnnotateResult {
        var request = URLRequest(
            url: baseURL.appendingPathComponent("memory/\(area.rawValue)/annotate")
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        request.httpBody = try JSONEncoder().encode(
            AnnotateRequestBody(entryId: entryID, mode: mode, intent: intent, cues: cues)
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(AnnotateResult.self, from: data)
    }

    func autoAnnotate(area: MemoryArea, n: Int = 10) async throws -> AutoAnnotateResult {
        var request = URLRequest(
            url: baseURL.appendingPathComponent("memory/\(area.rawValue)/auto-annotate")
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        request.httpBody = try JSONEncoder().encode(AutoAnnotateRequestBody(n: n, onlyUnannotated: true))
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(AutoAnnotateResult.self, from: data)
    }

    func fetchAccessLog(limit: Int = 200, offset: Int = 0) async throws -> AccessLogResponse {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("memory/audit/access_log"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)"),
        ]
        guard let url = components.url else { throw AutumnClientError.invalidURL }
        var request = URLRequest(url: url)
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(AccessLogResponse.self, from: data)
    }

    func consolidateMemory(area: MemoryArea) async throws -> ConsolidateResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("memory/\(area.rawValue)/consolidate"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        request.httpBody = try JSONEncoder().encode(["keep_recent": 10, "min_candidates": 3])

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ConsolidateResponse.self, from: data)
    }

    func projectMetadata(projectID: String) async throws -> ProjectMetadata {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("projects")
                .appendingPathComponent(projectID)
                .appendingPathComponent("metadata")
        )
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProjectMetadata.self, from: data)
    }

    func updateProjectMetadata(
        projectID: String,
        update: ProjectMetadataUpdate
    ) async throws -> ProjectMetadata {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("projects")
                .appendingPathComponent(projectID)
                .appendingPathComponent("metadata")
        )
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        request.httpBody = try JSONEncoder().encode(update)

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProjectMetadata.self, from: data)
    }

    func draftProjectDescription(projectID: String, input: String) async throws -> String {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("projects")
                .appendingPathComponent(projectID)
                .appendingPathComponent("describe")
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        request.httpBody = try JSONEncoder().encode(ProjectDraftInput(input: input))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProjectDescriptionDraft.self, from: data).description
    }

    func draftProjectGoals(projectID: String, input: String) async throws -> ProjectGoalsConfig {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("projects")
                .appendingPathComponent(projectID)
                .appendingPathComponent("goals")
        )
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120
        request.httpBody = try JSONEncoder().encode(ProjectDraftInput(input: input))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProjectGoalsConfig.self, from: data)
    }

    func inferProjectEnvironment(projectID: String) async throws -> ProjectMetadata {
        var request = URLRequest(
            url: baseURL
                .appendingPathComponent("projects")
                .appendingPathComponent(projectID)
                .appendingPathComponent("infer-environment")
        )
        request.httpMethod = "POST"
        request.timeoutInterval = 120

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(ProjectMetadata.self, from: data)
    }

    func ollamaStatus(baseURL targetBaseURL: String) async throws -> OllamaStatus {
        var request = URLRequest(url: baseURL.appendingPathComponent("ollama/status"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 10
        request.httpBody = try JSONEncoder().encode(OllamaTargetRequest(baseURL: targetBaseURL))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(OllamaStatus.self, from: data)
    }

    func ollamaModels(baseURL targetBaseURL: String) async throws -> [OllamaModel] {
        var request = URLRequest(url: baseURL.appendingPathComponent("ollama/models"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        request.httpBody = try JSONEncoder().encode(OllamaTargetRequest(baseURL: targetBaseURL))

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(OllamaModelsResponse.self, from: data).models
    }

    func ollamaRecommendedModels() async throws -> [OllamaRecommendedModel] {
        var request = URLRequest(url: baseURL.appendingPathComponent("ollama/recommended"))
        request.timeoutInterval = 20

        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
        return try JSONDecoder().decode(OllamaRecommendedResponse.self, from: data).models
    }

    func deleteOllamaModel(name: String, baseURL targetBaseURL: String) async throws {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("ollama/models"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [
            URLQueryItem(name: "name", value: name),
            URLQueryItem(name: "base_url", value: targetBaseURL),
        ]
        guard let url = components.url else { throw AutumnClientError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 60
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.requireOK(response, data: data)
    }

    func pullOllamaModel(
        name: String,
        baseURL targetBaseURL: String
    ) -> AsyncThrowingStream<OllamaPullEvent, Error> {
        let serverBaseURL = self.baseURL
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var components = URLComponents(
                        url: serverBaseURL.appendingPathComponent("ollama/pull"),
                        resolvingAgainstBaseURL: false
                    )!
                    components.queryItems = [
                        URLQueryItem(name: "name", value: name),
                        URLQueryItem(name: "base_url", value: targetBaseURL),
                    ]
                    guard let url = components.url else {
                        throw AutumnClientError.invalidURL
                    }
                    var request = URLRequest(url: url)
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.timeoutInterval = 600

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
                        guard let data = payload.data(using: .utf8) else { continue }
                        let event = try JSONDecoder().decode(OllamaPullEvent.self, from: data)
                        if let error = event.error {
                            throw AutumnClientError.serverError(error)
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

    private static func requireOK(_ response: URLResponse, data: Data = Data()) throws {
        guard let http = response as? HTTPURLResponse else {
            throw AutumnClientError.badStatus(-1)
        }
        guard (200..<300).contains(http.statusCode) else {
            if let body = try? JSONDecoder().decode([String: String].self, from: data),
               let detail = body["detail"], !detail.isEmpty {
                throw AutumnClientError.serverError(detail)
            }
            throw AutumnClientError.badStatus(http.statusCode)
        }
    }
}
