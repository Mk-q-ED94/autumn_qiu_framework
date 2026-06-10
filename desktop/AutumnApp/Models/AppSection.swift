import Foundation

enum AppSection: String, CaseIterable, Identifiable {
    case workspace
    case memory
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .workspace: return NSLocalizedString("section.workspace.title", comment: "")
        case .memory: return NSLocalizedString("section.memory.title", comment: "")
        case .settings: return NSLocalizedString("section.settings.title", comment: "")
        }
    }

    var subtitle: String {
        switch self {
        case .workspace: return NSLocalizedString("section.workspace.subtitle", comment: "")
        case .memory: return NSLocalizedString("section.memory.subtitle", comment: "")
        case .settings: return NSLocalizedString("section.settings.subtitle", comment: "")
        }
    }

    var systemImage: String {
        switch self {
        case .workspace: return "sparkles"
        case .memory: return "tray.full"
        case .settings: return "gearshape"
        }
    }
}
