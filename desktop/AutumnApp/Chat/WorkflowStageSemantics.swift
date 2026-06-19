import Foundation

enum WorkflowStageRole: String, CaseIterable, Identifiable {
    case memory
    case orientation
    case routing
    case execution
    case quality

    var id: String { rawValue }

    var title: String {
        switch self {
        case .memory: return "记忆上下文"
        case .orientation: return "识别与计划"
        case .routing: return "路由与交接"
        case .execution: return "执行与工具"
        case .quality: return "监督与检查"
        }
    }

    var icon: String {
        switch self {
        case .memory: return "brain"
        case .orientation: return "scope"
        case .routing: return "arrow.triangle.branch"
        case .execution: return "cpu"
        case .quality: return "checkmark.seal"
        }
    }
}

struct WorkflowStageGroup: Identifiable, Equatable {
    let role: WorkflowStageRole
    let stages: [WorkflowStage]

    var id: WorkflowStageRole { role }
}

extension WorkflowTrace {
    var stageGroups: [WorkflowStageGroup] {
        let grouped = Dictionary(grouping: stages, by: \.role)
        return WorkflowStageRole.allCases.compactMap { role in
            guard let stages = grouped[role], !stages.isEmpty else { return nil }
            return WorkflowStageGroup(role: role, stages: stages)
        }
    }
}

extension WorkflowStage {
    var role: WorkflowStageRole {
        if kind == "push" || kind == "archive" || workspace == "WP4" {
            return .memory
        }
        if kind == "tool" || kind == "agent" || id == "wp2.task" || id == "wp3.direct" {
            return .execution
        }
        if id == "wp1.final_check" || id.contains("supervise") || id == "error" {
            return .quality
        }
        if id.hasPrefix("wp3.") || id.contains("handoff") {
            return .routing
        }
        if id == "wp1.select" || id == "wp1.plan" {
            return .orientation
        }

        switch workspace {
        case "WP2": return .execution
        case "WP3": return .routing
        case "WP4": return .memory
        default: return .orientation
        }
    }

    var semanticIcon: String {
        if status == "failed" { return "exclamationmark.triangle.fill" }
        if kind == "tool" { return "wrench.and.screwdriver.fill" }
        if kind == "agent" { return "cpu" }
        if kind == "push" { return "brain" }
        if kind == "archive" { return "archivebox.fill" }
        if id == "wp1.select" { return "scope" }
        if id == "wp1.plan" { return "checklist" }
        if id.contains("supervise") { return "eye.fill" }
        if id.contains("handoff") { return "arrow.right.circle" }
        if id.hasSuffix(".route") { return "arrow.triangle.branch" }
        if id.hasSuffix(".convert") { return "arrow.triangle.2.circlepath" }
        if id.contains("check") { return "checkmark.seal" }
        return role.icon
    }

    var statusTitle: String {
        switch status {
        case "completed": return "完成"
        case "active": return "运行中"
        case "failed": return "失败"
        default: return "等待"
        }
    }

    var isPrimaryPipelineStage: Bool {
        kind == "stage"
    }

    var isPipelineAnchor: Bool {
        id == "wp1.select" || id == "wp1.final_check"
    }
}
