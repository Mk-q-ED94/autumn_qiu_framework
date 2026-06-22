import Foundation
import SwiftUI

/// Owns the in-memory list of projects and persists them to UserDefaults.
///
/// Coordinates with ``ConversationStore`` for cascading deletes (when a
/// project is deleted, its conversations are returned to the unfiled bucket
/// rather than dropped) — wiring is performed by the caller after both
/// stores are constructed.
@MainActor
final class ProjectStore: ObservableObject {
    @Published private(set) var projects: [Project] = []
    @Published var expandedProjectIDs: Set<UUID> = []
    @Published var unfiledExpanded: Bool = true {
        didSet { persistExpansion() }
    }

    private static let storageKey = "QcoworkDesktop.projects.v1"
    private static let expansionKey = "QcoworkDesktop.projects.expanded"
    private static let unfiledExpansionKey = "QcoworkDesktop.projects.unfiledExpanded"

    init() {
        load()
        loadExpansion()
    }

    // ── lookups ──────────────────────────────────────────────────────────────

    func project(id: UUID) -> Project? {
        projects.first(where: { $0.id == id })
    }

    func project(id: UUID?) -> Project? {
        guard let id else { return nil }
        return project(id: id)
    }

    // ── CRUD ─────────────────────────────────────────────────────────────────

    @discardableResult
    func create(
        name: String = "新项目",
        instructions: String = "",
        colorTag: String? = nil
    ) -> Project {
        let tag = colorTag ?? nextColorTag()
        let project = Project(
            name: trimmedNonEmpty(name) ?? "新项目",
            instructions: instructions,
            colorTag: tag
        )
        projects.insert(project, at: 0)
        expandedProjectIDs.insert(project.id)
        persist()
        persistExpansion()
        return project
    }

    func rename(_ id: UUID, to name: String) {
        guard let idx = projects.firstIndex(where: { $0.id == id }) else { return }
        let cleaned = trimmedNonEmpty(name) ?? "新项目"
        projects[idx].name = cleaned
        projects[idx].updatedAt = Date()
        persist()
    }

    func updateInstructions(_ id: UUID, instructions: String) {
        guard let idx = projects.firstIndex(where: { $0.id == id }) else { return }
        projects[idx].instructions = instructions
        projects[idx].updatedAt = Date()
        persist()
    }

    func updateColor(_ id: UUID, colorTag: String) {
        guard let idx = projects.firstIndex(where: { $0.id == id }) else { return }
        projects[idx].colorTag = colorTag
        projects[idx].updatedAt = Date()
        persist()
    }

    func update(_ project: Project) {
        guard let idx = projects.firstIndex(where: { $0.id == project.id }) else { return }
        var updated = project
        updated.updatedAt = Date()
        projects[idx] = updated
        persist()
    }

    /// Removes the project. Conversations belonging to it are NOT deleted —
    /// the caller is responsible for unassigning them via
    /// ``ConversationStore.unfileConversations(belongingTo:)``.
    func delete(_ id: UUID) {
        projects.removeAll(where: { $0.id == id })
        expandedProjectIDs.remove(id)
        persist()
        persistExpansion()
    }

    // ── expansion state ──────────────────────────────────────────────────────

    func isExpanded(_ id: UUID) -> Bool {
        expandedProjectIDs.contains(id)
    }

    func setExpanded(_ id: UUID, _ value: Bool) {
        if value {
            expandedProjectIDs.insert(id)
        } else {
            expandedProjectIDs.remove(id)
        }
        persistExpansion()
    }

    func toggleExpanded(_ id: UUID) {
        setExpanded(id, !isExpanded(id))
    }

    // ── persistence ──────────────────────────────────────────────────────────

    private func persist() {
        if let data = try? JSONEncoder().encode(projects) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func persistExpansion() {
        let strings = expandedProjectIDs.map { $0.uuidString }
        UserDefaults.standard.set(strings, forKey: Self.expansionKey)
        UserDefaults.standard.set(unfiledExpanded, forKey: Self.unfiledExpansionKey)
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([Project].self, from: data)
        else { return }
        projects = decoded
    }

    private func loadExpansion() {
        if let raw = UserDefaults.standard.array(forKey: Self.expansionKey) as? [String] {
            expandedProjectIDs = Set(raw.compactMap(UUID.init(uuidString:)))
        } else {
            // Default: expand all on first load.
            expandedProjectIDs = Set(projects.map(\.id))
        }
        if UserDefaults.standard.object(forKey: Self.unfiledExpansionKey) != nil {
            unfiledExpanded = UserDefaults.standard.bool(forKey: Self.unfiledExpansionKey)
        }
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    private func trimmedNonEmpty(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// Rotates through ``ProjectPalette.allTags`` so newly created projects
    /// pick up a different colour by default.
    private func nextColorTag() -> String {
        let tags = ProjectPalette.allTags
        guard !tags.isEmpty else { return "leaf" }
        let used = Set(projects.map(\.colorTag))
        for tag in tags where !used.contains(tag) {
            return tag
        }
        return tags[projects.count % tags.count]
    }
}
