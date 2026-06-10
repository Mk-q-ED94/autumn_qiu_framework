import Foundation

enum WorkflowInputKind: String, CaseIterable, Identifiable, Codable {
    case task
    case mission

    var id: String { rawValue }

    var title: String {
        switch self {
        case .task: return NSLocalizedString("input.task.title", comment: "")
        case .mission: return NSLocalizedString("input.mission.title", comment: "")
        }
    }

    var badgeTitle: String {
        switch self {
        case .task: return NSLocalizedString("input.task.badge", comment: "")
        case .mission: return NSLocalizedString("input.mission.badge", comment: "")
        }
    }

    var icon: String {
        switch self {
        case .task: return "checklist"
        case .mission: return "arrow.triangle.branch"
        }
    }
}

enum WorkflowTaskKind: String, CaseIterable, Identifiable, Codable {
    case code
    case search
    case write
    case data
    case general

    var id: String { rawValue }

    var title: String {
        switch self {
        case .code: return NSLocalizedString("task.code.title", comment: "")
        case .search: return NSLocalizedString("task.search.title", comment: "")
        case .write: return NSLocalizedString("task.write.title", comment: "")
        case .data: return NSLocalizedString("task.data.title", comment: "")
        case .general: return NSLocalizedString("task.general.title", comment: "")
        }
    }

    var badgeTitle: String {
        switch self {
        case .code: return NSLocalizedString("task.code.badge", comment: "")
        case .search: return NSLocalizedString("task.search.badge", comment: "")
        case .write: return NSLocalizedString("task.write.badge", comment: "")
        case .data: return NSLocalizedString("task.data.badge", comment: "")
        case .general: return NSLocalizedString("task.general.badge", comment: "")
        }
    }
}

enum MissionRouteMode: String, CaseIterable, Identifiable, Codable {
    case auto
    case direct
    case convert

    var id: String { rawValue }

    var title: String {
        switch self {
        case .auto: return NSLocalizedString("route.auto.title", comment: "")
        case .direct: return NSLocalizedString("route.direct.title", comment: "")
        case .convert: return NSLocalizedString("route.convert.title", comment: "")
        }
    }

    var icon: String {
        switch self {
        case .auto: return "wand.and.stars"
        case .direct: return "arrow.down.message"
        case .convert: return "checklist"
        }
    }

    var detail: String {
        switch self {
        case .auto: return NSLocalizedString("route.auto.detail", comment: "")
        case .direct: return NSLocalizedString("route.direct.detail", comment: "")
        case .convert: return NSLocalizedString("route.convert.detail", comment: "")
        }
    }
}
