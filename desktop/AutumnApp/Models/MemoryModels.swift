import Foundation

enum MemoryArea: String, CaseIterable, Identifiable, Codable {
    case mom1
    case mom2
    case mom3
    case shared

    var id: String { rawValue }

    var title: String {
        switch self {
        case .mom1: return "Mom1"
        case .mom2: return "Mom2"
        case .mom3: return "Mom3"
        case .shared: return "Shared"
        }
    }

    var subtitle: String {
        switch self {
        case .mom1: return NSLocalizedString("memory.mom1.subtitle", comment: "")
        case .mom2: return NSLocalizedString("memory.mom2.subtitle", comment: "")
        case .mom3: return NSLocalizedString("memory.mom3.subtitle", comment: "")
        case .shared: return NSLocalizedString("memory.shared.subtitle", comment: "")
        }
    }
}

struct MemoryEntry: Identifiable, Equatable {
    let id = UUID()
    let area: MemoryArea
    let values: [String: JSONValue]

    var title: String {
        firstString(for: ["route", "type", "role", "turn"]) ?? area.title
    }

    var preview: String {
        firstString(for: ["input", "mission", "task", "output", "content"])
            ?? contentString(for: ["input", "mission", "task", "output", "content"])
            ?? "暂无内容"
    }

    var sortedKeys: [String] {
        values.keys.sorted()
    }

    private func firstString(for keys: [String]) -> String? {
        for key in keys {
            guard let value = values[key]?.summary, !value.isEmpty else { continue }
            return value
        }
        return nil
    }

    private func contentString(for keys: [String]) -> String? {
        guard case .object(let content)? = values["content"] else { return nil }
        for key in keys {
            guard let value = content[key]?.summary, !value.isEmpty else { continue }
            return value
        }
        return content.isEmpty ? nil : content.keys.sorted().joined(separator: ", ")
    }
}

struct MemoryStats: Decodable, Equatable {
    let area: String
    let total: Int
    let expired: Int
    let pinned: Int
    let tags: [String: Int]
    let oldest: Double?
    let newest: Double?
    let avgImportance: Double
    let historyLimit: Int
    let decayHalfLife: Double?
    let hasVector: Bool

    enum CodingKeys: String, CodingKey {
        case area, total, expired, pinned, tags, oldest, newest
        case avgImportance = "avg_importance"
        case historyLimit = "history_limit"
        case decayHalfLife = "decay_half_life"
        case hasVector = "has_vector"
    }
}

struct MemoryStatsOverview: Decodable, Equatable {
    let zones: [String: MemoryStats]
    let total: Int
    let areas: [String]
}

struct ConsolidateResponse: Decodable, Equatable {
    let status: String
    let summary: [String: JSONValue]?
}

enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var summary: String {
        switch self {
        case .string(let value):
            return value
        case .number(let value):
            if value.rounded() == value {
                return String(Int(value))
            }
            return String(value)
        case .bool(let value):
            return value ? "true" : "false"
        case .object(let value):
            return value.keys.sorted().joined(separator: ", ")
        case .array(let value):
            return "\(value.count) 项"
        case .null:
            return ""
        }
    }

    var formatted: String {
        switch self {
        case .string(let value):
            return value
        case .number, .bool, .null:
            return summary
        case .object(let value):
            return value.keys.sorted().map { "\($0): \(value[$0]?.summary ?? "")" }.joined(separator: "\n")
        case .array(let value):
            return value.map(\.summary).joined(separator: "\n")
        }
    }
}
