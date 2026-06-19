import Foundation

enum AppSection: String, CaseIterable, Identifiable {
    case workspace
    case memory
    case terrs

    var id: String { rawValue }

    var title: String {
        switch self {
        case .workspace: return NSLocalizedString("section.workspace.title", comment: "")
        case .memory: return NSLocalizedString("section.memory.title", comment: "")
        case .terrs: return NSLocalizedString("section.terrs.title", comment: "")
        }
    }

    var subtitle: String {
        switch self {
        case .workspace: return NSLocalizedString("section.workspace.subtitle", comment: "")
        case .memory: return NSLocalizedString("section.memory.subtitle", comment: "")
        case .terrs: return NSLocalizedString("section.terrs.subtitle", comment: "")
        }
    }

    var systemImage: String {
        switch self {
        case .workspace: return "sparkles"
        case .memory: return "brain"
        case .terrs: return "puzzlepiece.extension"
        }
    }
}
