import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager

    var body: some View {
        HStack(spacing: 0) {
            ChatView(settings: settings)

            Divider()

            WorkflowInspectorView(settings: settings, localServer: localServer)
                .frame(width: 280)
        }
        .navigationTitle("协作工作台")
    }
}

private struct WorkflowInspectorView: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                StatusPanel(settings: settings, localServer: localServer)
                RoutePanel(routeMode: settings.routeMode)
                ModelStack(settings: settings)
            }
            .padding(16)
        }
        .background(.regularMaterial)
    }
}

private struct StatusPanel: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("状态")
                .font(.headline)
            LabeledContent("本地服务", value: localServer.statusText)
            LabeledContent("服务器", value: settings.serverURL)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .font(.caption)
    }
}

private struct RoutePanel: View {
    let routeMode: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("路由")
                .font(.headline)
            HStack {
                Image(systemName: routeIcon)
                    .foregroundStyle(.tint)
                Text(routeTitle)
                    .font(.callout)
            }
            Text(routeDetail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var routeIcon: String {
        switch routeMode {
        case "direct": return "arrow.down.message"
        case "convert": return "checklist"
        default: return "wand.and.stars"
        }
    }

    private var routeTitle: String {
        switch routeMode {
        case "direct": return "直接回答"
        case "convert": return "转为任务"
        default: return "自动"
        }
    }

    private var routeDetail: String {
        switch routeMode {
        case "direct": return "A3 生成回答，A1 做最终检查。"
        case "convert": return "A3 转换任务，A2 执行，A1 检查。"
        default: return "每条 mission 由 A3 决定路径。"
        }
    }
}

private struct ModelStack: View {
    let settings: AppSettings

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("模型")
                .font(.headline)

            ForEach(ModelSlot.allCases) { slot in
                ModelStatusRow(slot: slot, config: settings.providerConfig(for: slot))
            }
        }
    }
}

private struct ModelStatusRow: View {
    let slot: ModelSlot
    let config: ProviderConfigRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(slot.title)
                    .font(.caption)
                    .fontWeight(.semibold)
                Spacer()
                Image(systemName: isConfigured ? "checkmark.circle.fill" : "circle.dashed")
                    .foregroundStyle(isConfigured ? .green : .secondary)
            }

            Text(config.model?.isEmpty == false ? config.model ?? "" : "未选择模型")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .padding(10)
        .background(.quaternary.opacity(0.65), in: RoundedRectangle(cornerRadius: 8))
    }

    private var isConfigured: Bool {
        !config.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !(config.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}
