import Foundation

enum WorkflowInputKind: String, CaseIterable, Identifiable, Codable {
    case task
    case mission

    var id: String { rawValue }

    var title: String {
        switch self {
        case .task: return "任务"
        case .mission: return "使命"
        }
    }

    var badgeTitle: String {
        switch self {
        case .task: return "结构任务"
        case .mission: return "宏观使命"
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
        case .code: return "代码"
        case .search: return "检索"
        case .write: return "写作"
        case .data: return "数据"
        case .general: return "通用"
        }
    }

    var badgeTitle: String {
        switch self {
        case .code: return "代码任务"
        case .search: return "检索任务"
        case .write: return "写作任务"
        case .data: return "数据任务"
        case .general: return "通用任务"
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
        case .auto: return "自动"
        case .direct: return "直接回答"
        case .convert: return "转为任务"
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
        case .auto: return "每条 mission 由 A3 决定路径。"
        case .direct: return "A3 生成回答，A1 做最终检查。"
        case .convert: return "A3 转换任务，A2 执行，A1 检查。"
        }
    }
}
