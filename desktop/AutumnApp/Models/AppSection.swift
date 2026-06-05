import Foundation

enum AppSection: String, CaseIterable, Identifiable {
    case workspace
    case memory
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .workspace: return "协作"
        case .memory: return "记忆"
        case .settings: return "设置"
        }
    }

    var subtitle: String {
        switch self {
        case .workspace: return "A1/A2/A3 工作流"
        case .memory: return "Mom1-3 历史"
        case .settings: return "模型与服务器"
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
