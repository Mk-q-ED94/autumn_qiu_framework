import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @EnvironmentObject private var store: ConversationStore

    @SceneStorage("AutumnDesktop.inspectorVisible") private var inspectorVisible: Bool = true

    var body: some View {
        HStack(spacing: 0) {
            ChatView(settings: settings, store: store)
                .id(store.selectedID)   // rebuild the chat VM when the conversation switches

            if inspectorVisible {
                Divider()
                WorkflowInspectorView(settings: settings, localServer: localServer)
                    .frame(width: Autumn.sizing.inspectorWidth)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .navigationTitle(store.selected?.title ?? "协作")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    withAnimation(Autumn.motion.snappy) {
                        inspectorVisible.toggle()
                    }
                } label: {
                    Image(systemName: inspectorVisible ? "sidebar.right" : "sidebar.right")
                        .foregroundStyle(inspectorVisible ? .tint : .secondary)
                }
                .help("切换检视面板 (⌘⇧I)")
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnToggleInspector)) { _ in
            withAnimation(Autumn.motion.snappy) { inspectorVisible.toggle() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnNewConversation)) { _ in
            store.newConversation()
        }
    }
}

// ── Inspector ─────────────────────────────────────────────────────────────────

private struct WorkflowInspectorView: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Autumn.spacing.md) {
                StatusPanel(settings: settings, localServer: localServer)
                RoutePanel(routeMode: settings.routeMode)
                ModelStack(settings: settings)
            }
            .padding(Autumn.spacing.md)
        }
        .background(.regularMaterial)
    }
}

private struct StatusPanel: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        AutumnCard {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                Text("状态")
                    .font(Autumn.typography.headline)
                Divider()
                LabeledRow(label: "本地服务", value: localServer.statusText, tone: statusTone)
                LabeledRow(label: "服务器", value: settings.serverURL)
            }
        }
    }

    private var statusTone: AutumnBadge.Tone {
        let s = localServer.statusText
        if s.contains("已") { return .success }
        if s.contains("失败") { return .danger }
        if s.contains("启动中") || s.contains("检测中") { return .warning }
        return .neutral
    }
}

private struct RoutePanel: View {
    let routeMode: String

    var body: some View {
        AutumnCard {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack {
                    Text("默认路由")
                        .font(Autumn.typography.headline)
                    Spacer()
                    AutumnBadge(routeTitle, icon: routeIcon, tone: .accent)
                }
                Divider()
                Text(routeDetail)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
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
        AutumnCard {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                Text("模型 A1 / A2 / A3")
                    .font(Autumn.typography.headline)
                Divider()
                VStack(spacing: Autumn.spacing.sm) {
                    ForEach(ModelSlot.allCases) { slot in
                        ModelStatusRow(slot: slot, config: settings.providerConfig(for: slot))
                    }
                }
            }
        }
    }
}

private struct ModelStatusRow: View {
    let slot: ModelSlot
    let config: ProviderConfigRequest

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: Autumn.spacing.xs) {
                    Text(slot.title)
                        .font(Autumn.typography.captionStrong)
                    AutumnBadge(
                        isConfigured ? "就绪" : "未就绪",
                        tone: isConfigured ? .success : .neutral
                    )
                }
                Text(config.model?.isEmpty == false ? config.model ?? "" : "未选择模型")
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            Spacer()
        }
        .padding(Autumn.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                .fill(Autumn.colors.surfaceElevated)
        )
    }

    private var isConfigured: Bool {
        !config.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !(config.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

private struct LabeledRow: View {
    let label: String
    let value: String
    var tone: AutumnBadge.Tone? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if let tone {
                AutumnBadge(value, tone: tone)
            } else {
                Text(value)
                    .font(Autumn.typography.caption)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }
}
