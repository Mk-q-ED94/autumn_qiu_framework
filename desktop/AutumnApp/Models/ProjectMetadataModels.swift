import Foundation

struct ProjectGoalsConfig: Codable, Equatable {
    var master: String = ""
    var longTerm: [String] = []
    var shortTerm: [String] = []

    enum CodingKeys: String, CodingKey {
        case master
        case longTerm = "long_term"
        case shortTerm = "short_term"
    }
}

struct ProjectEnvironmentConfig: Codable, Equatable {
    var terrs: [String] = []
    var skills: [String] = []
    var tools: [String] = []
    var mcp: [String] = []
    var agentChannel: String?

    enum CodingKeys: String, CodingKey {
        case terrs, skills, tools, mcp
        case agentChannel = "agent_channel"
    }
}

struct ProjectMetadata: Codable, Equatable {
    var projectType: String?
    var description: String
    var goals: ProjectGoalsConfig
    var files: [String]
    var environment: ProjectEnvironmentConfig

    static let empty = ProjectMetadata(
        projectType: nil,
        description: "",
        goals: ProjectGoalsConfig(),
        files: [],
        environment: ProjectEnvironmentConfig()
    )

    enum CodingKeys: String, CodingKey {
        case projectType = "project_type"
        case description, goals, files, environment
    }
}

struct ProjectMetadataUpdate: Encodable {
    var projectType: String?
    var description: String?
    var goals: ProjectGoalsConfig?
    var files: [String]?
    var environment: ProjectEnvironmentConfig?

    enum CodingKeys: String, CodingKey {
        case projectType = "project_type"
        case description, goals, files, environment
    }
}

struct ProjectDraftInput: Encodable {
    let input: String
}

struct ProjectDescriptionDraft: Decodable {
    let description: String
}

struct ProjectFileResponse: Decodable {
    let status: String
    let files: [String]
}

struct ProjectListResponse: Decodable {
    let projects: [String]
}

struct OllamaTargetRequest: Encodable {
    let baseURL: String

    enum CodingKeys: String, CodingKey {
        case baseURL = "base_url"
    }
}

struct OllamaDeleteRequest: Encodable {
    let baseURL: String
    let name: String

    enum CodingKeys: String, CodingKey {
        case baseURL = "base_url"
        case name
    }
}

struct OllamaStatus: Decodable, Equatable {
    let running: Bool
    let baseURL: String
    let version: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case running
        case baseURL = "base_url"
        case version, error
    }
}

struct OllamaModel: Decodable, Identifiable, Equatable {
    let name: String
    let size: Int?
    let parameterSize: String?
    let family: String?
    let modifiedAt: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, size, family
        case parameterSize = "parameter_size"
        case modifiedAt = "modified_at"
    }
}

struct OllamaModelsResponse: Decodable {
    let models: [OllamaModel]
}

struct OllamaRecommendedModel: Decodable, Identifiable, Equatable {
    let name: String
    let label: String
    let size: String
    let note: String
    let recommended: Bool

    var id: String { name }
}

struct OllamaRecommendedResponse: Decodable {
    let models: [OllamaRecommendedModel]
}

struct OllamaPullEvent: Decodable, Equatable {
    let status: String?
    let digest: String?
    let total: Int?
    let completed: Int?
    let error: String?

    var progressFraction: Double? {
        guard let total, total > 0, let completed else { return nil }
        return min(1, max(0, Double(completed) / Double(total)))
    }
}
