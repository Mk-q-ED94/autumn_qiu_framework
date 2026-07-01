import Foundation
import SwiftUI

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

/// The four `use.mode` values of the 4D memory system, with display metadata.
/// Mirrors `UseMode` in `autumn/core/memory/dimensions.py`.
enum FourDUseMode: String, CaseIterable, Identifiable {
    case constrain
    case remind
    case context
    case summarize

    var id: String { rawValue }

    var label: String {
        switch self {
        case .constrain: return "约束"
        case .remind:    return "提醒"
        case .context:   return "上下文"
        case .summarize: return "摘要"
        }
    }

    var icon: String {
        switch self {
        case .constrain: return "lock.fill"
        case .remind:    return "bell.fill"
        case .context:   return "text.alignleft"
        case .summarize: return "doc.text.fill"
        }
    }

    var tone: QcoworkBadge.Tone {
        switch self {
        case .constrain: return .danger
        case .remind:    return .warning
        case .context:   return .neutral
        case .summarize: return .info
        }
    }
}

/// Lightweight memory kinds carried by reserved tags.
/// Mirrors `autumn/core/memory/kinds.py`.
enum MemoryKind: String, CaseIterable, Identifiable {
    case episode
    case atomicFact = "atomic_fact"
    case profile
    case summary
    case caseMemory = "case"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .episode:    return "片段"
        case .atomicFact: return "事实"
        case .profile:    return "画像"
        case .summary:    return "摘要"
        case .caseMemory: return "案例"
        }
    }

    var icon: String {
        switch self {
        case .episode:    return "text.bubble"
        case .atomicFact: return "atom"
        case .profile:    return "person.text.rectangle"
        case .summary:    return "doc.text"
        case .caseMemory: return "rectangle.stack.badge.person.crop"
        }
    }

    var tone: QcoworkBadge.Tone {
        switch self {
        case .episode:    return .neutral
        case .atomicFact: return .info
        case .profile:    return .accent
        case .summary:    return .memory
        case .caseMemory: return .success
        }
    }

    var color: Color {
        tone.foreground
    }
}

struct MemoryEntry: Identifiable, Equatable {
    let id = UUID()
    let area: MemoryArea
    let values: [String: JSONValue]

    var title: String {
        // v1 records keep route/type at the top level; v2 records nest the
        // original payload under `content`. Check both before falling back.
        firstString(for: ["route", "type", "role", "turn"])
            ?? nestedString(for: ["route", "type", "role", "turn"])
            ?? area.title
    }

    var preview: String {
        firstString(for: ["input", "mission", "task", "output", "content"])
            ?? contentString(for: ["input", "mission", "task", "output", "content"])
            ?? "暂无内容"
    }

    var sortedKeys: [String] {
        values.keys.sorted()
    }

    /// The server-side entry id (from the payload), distinct from the local
    /// `id` UUID used for SwiftUI identity. Needed to annotate the entry.
    var entryID: String? {
        if case .string(let s)? = values["id"], !s.isEmpty { return s }
        return nil
    }

    // ── entry metadata accessors ────────────────────────────────────────────

    var importance: Double? {
        guard case .number(let value)? = values["importance"] else { return nil }
        return value
    }

    /// Mirrors `MemoryEntry.PIN_THRESHOLD` (1.5) in `autumn/core/memory/base.py`.
    var isPinned: Bool {
        (importance ?? 1.0) >= 1.5
    }

    var timestamp: Date? {
        guard case .number(let epoch)? = values["timestamp"], epoch > 0 else { return nil }
        return Date(timeIntervalSince1970: epoch)
    }

    var relativeTime: String? {
        guard let timestamp else { return nil }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: timestamp, relativeTo: Date())
    }

    var tags: [String] {
        guard case .array(let raw)? = values["tags"] else { return [] }
        return raw.compactMap {
            if case .string(let s) = $0 { return s } else { return nil }
        }
    }

    var memoryKind: MemoryKind? {
        let tagSet = Set(tags)
        return MemoryKind.allCases.first { tagSet.contains($0.rawValue) }
    }

    // ── 4D dimension accessors ──────────────────────────────────────────────

    var useMode: String? {
        guard case .object(let use)? = values["use"],
              case .string(let mode)? = use["mode"] else { return nil }
        return mode
    }

    var fourdMode: FourDUseMode? {
        useMode.flatMap(FourDUseMode.init(rawValue:))
    }

    var useModeLabel: String {
        fourdMode?.label ?? useMode ?? "—"
    }

    var useCount: Int? {
        guard case .object(let use)? = values["use"],
              case .object(let stats)? = use["stats"],
              case .number(let count)? = stats["count"] else { return nil }
        return Int(count)
    }

    var aimIntent: String? {
        guard case .object(let aim)? = values["aim"],
              case .string(let intent)? = aim["intent"],
              !intent.isEmpty else { return nil }
        return intent
    }

    var aimScope: [String] {
        guard case .object(let aim)? = values["aim"],
              case .array(let scope)? = aim["scope"] else { return [] }
        return scope.compactMap {
            if case .string(let s) = $0 { return s } else { return nil }
        }
    }

    var triggerCues: [String] {
        guard case .object(let trigger)? = values["trigger"],
              case .array(let cues)? = trigger["cues"] else { return [] }
        return cues.compactMap {
            if case .string(let s) = $0 { return s } else { return nil }
        }
    }

    /// True when the entry carries *meaningful* 4D annotation. Every v2 record
    /// serializes `use.mode = "context"` by default, so a bare default mode with
    /// no usage, aim, or cues is just the schema default — not an annotation.
    var has4DData: Bool {
        if let mode = fourdMode, mode != .context { return true }
        return (useCount ?? 0) > 0
            || aimIntent != nil
            || !aimScope.isEmpty
            || !triggerCues.isEmpty
    }

    private func firstString(for keys: [String]) -> String? {
        for key in keys {
            guard let value = values[key]?.summary, !value.isEmpty else { continue }
            return value
        }
        return nil
    }

    /// Strict lookup inside the v2 `content` payload — nil when absent.
    private func nestedString(for keys: [String]) -> String? {
        guard case .object(let content)? = values["content"] else { return nil }
        for key in keys {
            guard let value = content[key]?.summary, !value.isEmpty else { continue }
            return value
        }
        return nil
    }

    private func contentString(for keys: [String]) -> String? {
        guard case .object(let content)? = values["content"] else { return nil }
        if let value = nestedString(for: keys) {
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

struct ExtractFactsResponse: Decodable, Equatable {
    let status: String
    let facts: [[String: JSONValue]]
}

struct EvolveMemoryResponse: Decodable, Equatable {
    let status: String
    let skills: [[String: JSONValue]]
}

struct MemoryProfileResponse: Decodable, Equatable {
    let status: String
    let scope: String
    let profile: String?
}

struct AccessLogEntry: Identifiable, Decodable, Equatable {
    let id: String
    let timestamp: Double
    let action: String
    let requester: String
    let query: String
    let reason: String
    let decisionReason: String
    let redact: Bool
    let entryIds: [String]
    let mediatedBy: String?

    var date: Date { Date(timeIntervalSince1970: timestamp) }
    var isGranted: Bool { action == "mom1_access_granted" }

    var relativeTime: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    enum CodingKeys: String, CodingKey {
        case id, timestamp, action, requester, query, reason, redact
        case decisionReason = "decision_reason"
        case entryIds = "entry_ids"
        case mediatedBy = "mediated_by"
    }
}

struct AccessLogResponse: Decodable {
    let entries: [AccessLogEntry]
    let total: Int
}

// ── 4D memory observability ─────────────────────────────────────────────────────

struct FourDStatus: Decodable, Equatable {
    let fourdMemoryEnabled: Bool
    let fourdPushOnTurn: Bool
    let fourdPullOnTurn: Bool
    let fourdAutoAnnotate: Bool
    let fourdAutoConsolidate: Bool
    let fourdAutoEvolve: Bool
    let fourdAutoExtractFacts: Bool
    let fourdAutoSynthesizeProfile: Bool
    let mom1AccessEnabled: Bool
    // Memory health — lets the client warn instead of silently doing nothing.
    let a4Configured: Bool
    let hasVector: Bool
    let hasLexical: Bool
    let memoryDegraded: Bool

    enum CodingKeys: String, CodingKey {
        case fourdMemoryEnabled = "fourd_memory_enabled"
        case fourdPushOnTurn = "fourd_push_on_turn"
        case fourdPullOnTurn = "fourd_pull_on_turn"
        case fourdAutoAnnotate = "fourd_auto_annotate"
        case fourdAutoConsolidate = "fourd_auto_consolidate"
        case fourdAutoEvolve = "fourd_auto_evolve"
        case fourdAutoExtractFacts = "fourd_auto_extract_facts"
        case fourdAutoSynthesizeProfile = "fourd_auto_synthesize_profile"
        case mom1AccessEnabled = "mom1_access_enabled"
        case a4Configured = "a4_configured"
        case hasVector = "has_vector"
        case hasLexical = "has_lexical"
        case memoryDegraded = "memory_degraded"
    }

    // Tolerate a server that predates the per-turn lifecycle / health fields:
    // each missing field falls back to the framework's own default so an older
    // backend still decodes (mirrors the server's FourDStatusResponse defaults).
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        fourdMemoryEnabled = try c.decodeIfPresent(Bool.self, forKey: .fourdMemoryEnabled) ?? false
        fourdPushOnTurn = try c.decodeIfPresent(Bool.self, forKey: .fourdPushOnTurn) ?? false
        fourdPullOnTurn = try c.decodeIfPresent(Bool.self, forKey: .fourdPullOnTurn) ?? true
        fourdAutoAnnotate = try c.decodeIfPresent(Bool.self, forKey: .fourdAutoAnnotate) ?? true
        fourdAutoConsolidate = try c.decodeIfPresent(Bool.self, forKey: .fourdAutoConsolidate) ?? true
        fourdAutoEvolve = try c.decodeIfPresent(Bool.self, forKey: .fourdAutoEvolve) ?? false
        fourdAutoExtractFacts = try c.decodeIfPresent(Bool.self, forKey: .fourdAutoExtractFacts) ?? false
        fourdAutoSynthesizeProfile =
            try c.decodeIfPresent(Bool.self, forKey: .fourdAutoSynthesizeProfile) ?? false
        mom1AccessEnabled = try c.decodeIfPresent(Bool.self, forKey: .mom1AccessEnabled) ?? true
        a4Configured = try c.decodeIfPresent(Bool.self, forKey: .a4Configured) ?? false
        hasVector = try c.decodeIfPresent(Bool.self, forKey: .hasVector) ?? false
        hasLexical = try c.decodeIfPresent(Bool.self, forKey: .hasLexical) ?? false
        memoryDegraded = try c.decodeIfPresent(Bool.self, forKey: .memoryDegraded) ?? false
    }
}

/// State of the codebase-memory token-saving layer (`GET /config/codebase-memory`).
struct CodebaseMemoryStatus: Decodable, Equatable {
    let enabled: Bool        // behaviour flag (intent; the layer auto-starts when on)
    let connected: Bool      // whether the code-graph MCP is live right now
    let starting: Bool       // bring-up in progress (async MCP spawn) — keep polling
    let indexed: Bool        // whether the repo has been indexed into the graph yet
    let repo: String         // repo scoped for indexing ("" = server working directory)
    let toolCount: Int
    let error: String?

    enum CodingKeys: String, CodingKey {
        case enabled, connected, starting, indexed, repo, error
        case toolCount = "tool_count"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try c.decode(Bool.self, forKey: .enabled)
        connected = try c.decode(Bool.self, forKey: .connected)
        // Tolerate an older server that predates the `starting` / `indexed` fields.
        starting = try c.decodeIfPresent(Bool.self, forKey: .starting) ?? false
        indexed = try c.decodeIfPresent(Bool.self, forKey: .indexed) ?? false
        repo = try c.decodeIfPresent(String.self, forKey: .repo) ?? ""
        toolCount = try c.decodeIfPresent(Int.self, forKey: .toolCount) ?? 0
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

struct PushPreviewEntry: Identifiable, Decodable, Equatable {
    let id: String
    let text: String
    let mode: String
    let intent: String
    let cues: [String]
    let score: Double

    var fourdMode: FourDUseMode? { FourDUseMode(rawValue: mode) }
}

struct PushPreviewResponse: Decodable {
    let fired: [PushPreviewEntry]
    let fragment: String
    let enabled: Bool
}

struct AnnotateResult: Decodable {
    let status: String
    let entryId: String
    let found: Bool

    enum CodingKeys: String, CodingKey {
        case status, found
        case entryId = "entry_id"
    }
}

struct AutoAnnotateResult: Decodable {
    let status: String
    let annotated: Int
    let scanned: Int
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
