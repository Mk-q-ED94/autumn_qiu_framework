import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @EnvironmentObject private var store: ConversationStore
    @EnvironmentObject private var projects: ProjectStore

    @SceneStorage("AutumnDesktop.inspectorVisible") private var inspectorVisible: Bool = true

    var body: some View {
        HStack(spacing: 0) {
            ChatView(settings: settings, store: store, projects: projects)
                .id(store.selectedID)   // rebuild the chat VM when the conversation switches

            if inspectorVisible {
                Divider()
                WorkflowInspectorView(settings: settings, localServer: localServer)
                    .frame(width: Autumn.sizing.inspectorWidth)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .navigationTitle(navigationTitleText)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    withAnimation(Autumn.motion.snappy) {
                        inspectorVisible.toggle()
                    }
                } label: {
                    Image(systemName: "sidebar.right")
                        .foregroundStyle(inspectorVisible ? Color.accentColor : Color.secondary)
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

    private var navigationTitleText: String {
        let title = store.selected?.title ?? "协作"
        if let projectID = store.selected?.projectID,
           let project = projects.project(id: projectID) {
            return "\(project.name) › \(title)"
        }
        return title
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
                RoutePanel(
                    routeMode: settings.routeMode,
                    routeOverride: settings.activeRouteOverride
                )
                ModelStack(settings: settings)
                TerrPanel(settings: settings)
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
    let routeOverride: String?

    var body: some View {
        AutumnCard {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack {
                    Text("默认路由")
                        .font(Autumn.typography.headline)
                    Spacer()
                    AutumnBadge(routeTitle, icon: routeIcon, tone: .accent)
                }
                if let routeOverride,
                   let override = MissionRouteMode(rawValue: routeOverride) {
                    HStack {
                        Text("本次覆盖")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        AutumnBadge(override.title, icon: override.icon, tone: .warning)
                    }
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
        (MissionRouteMode(rawValue: routeMode) ?? .auto).icon
    }

    private var routeTitle: String {
        (MissionRouteMode(rawValue: routeMode) ?? .auto).title
    }

    private var routeDetail: String {
        (MissionRouteMode(rawValue: routeMode) ?? .auto).detail
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
                        ModelStatusRow(
                            slot: slot,
                            config: settings.providerConfig(for: slot),
                            state: settings.modelState(for: slot)
                        )
                    }
                }
            }
        }
    }
}

private struct ModelStatusRow: View {
    let slot: ModelSlot
    let config: ProviderConfigRequest
    let state: ModelConnectionState

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: Autumn.spacing.xs) {
                    Text(slot.title)
                        .font(Autumn.typography.captionStrong)
                    AutumnBadge(state.title, tone: state.tone)
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

}

private struct TerrPanel: View {
    let settings: AppSettings
    @State private var terrs: [TerrSummary] = []
    @State private var isLoading = false
    @State private var togglingTerrs: Set<String> = []
    @State private var errorMessage: String?

    var body: some View {
        AutumnCard {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack {
                    Text("能力域")
                        .font(Autumn.typography.headline)
                    Spacer()
                    if isLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Button(action: { Task { await loadTerrs() } }) {
                            Image(systemName: "arrow.clockwise")
                        }
                        .buttonStyle(.plain)
                        .help("刷新能力域")
                    }
                }
                Divider()

                if let errorMessage {
                    Text(errorMessage)
                        .font(Autumn.typography.caption)
                        .foregroundStyle(Autumn.colors.danger)
                } else if terrs.isEmpty {
                    VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                        Text("尚未加载 Terr")
                            .font(Autumn.typography.captionStrong)
                        Text("在 Python 侧调用 register_terr、add_terr，或把 Terr 插件放入 plugin_dirs。")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else {
                    VStack(spacing: Autumn.spacing.sm) {
                        ForEach(terrs) { terr in
                            TerrCard(
                                terr: terr,
                                isToggling: togglingTerrs.contains(terr.name),
                                onToggle: { enabled in
                                    Task { await setTerr(terr, enabled: enabled) }
                                }
                            )
                        }
                    }
                }
            }
        }
        .task { await loadTerrs() }
    }

    private func loadTerrs() async {
        guard let url = URL(string: settings.serverURL) else {
            errorMessage = "服务器 URL 无效"
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            terrs = try await AutumnClient(baseURL: url).fetchTerrs()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func setTerr(_ terr: TerrSummary, enabled: Bool) async {
        guard let url = URL(string: settings.serverURL) else {
            errorMessage = "服务器 URL 无效"
            return
        }
        let previous = terr.enabled
        if let index = terrs.firstIndex(where: { $0.name == terr.name }) {
            terrs[index].enabled = enabled
        }
        togglingTerrs.insert(terr.name)
        errorMessage = nil
        defer { togglingTerrs.remove(terr.name) }

        do {
            let updated = try await AutumnClient(baseURL: url)
                .setTerrEnabled(name: terr.name, enabled: enabled)
            if let index = terrs.firstIndex(where: { $0.name == terr.name }) {
                terrs[index] = updated
            }
        } catch {
            if let index = terrs.firstIndex(where: { $0.name == terr.name }) {
                terrs[index].enabled = previous
            }
            errorMessage = error.localizedDescription
        }
    }
}

private struct TerrCard: View {
    let terr: TerrSummary
    let isToggling: Bool
    let onToggle: (Bool) -> Void
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                capabilityGroup("Tools", items: terr.tools)
                capabilityGroup("Skills", items: terr.skills)
                if !terr.mcps.isEmpty {
                    VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                        Text("MCP")
                            .font(Autumn.typography.captionStrong)
                        ForEach(terr.mcps) { mcp in
                            Text("\(mcp.name) · \(mcp.description)")
                                .font(Autumn.typography.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .padding(.top, Autumn.spacing.sm)
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(terr.name)
                        .font(Autumn.typography.captionStrong)
                    AutumnBadge(
                        terr.enabled ? "启用" : "停用",
                        icon: terr.enabled ? "checkmark.circle.fill" : "pause.circle",
                        tone: terr.enabled ? .success : .neutral
                    )
                    Spacer()
                    if isToggling {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Toggle(isOn: toggleBinding) {
                            Text("启用")
                        }
                        .labelsHidden()
                        .toggleStyle(.switch)
                        .controlSize(.mini)
                        .help(terr.enabled ? "停用能力域" : "启用能力域")
                    }
                    AutumnBadge("\(terr.tools.count)T", tone: .info)
                    AutumnBadge("\(terr.skills.count)S", tone: .accent)
                }
                Text(terr.description.isEmpty ? "未提供描述" : terr.description)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(Autumn.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                .fill(Autumn.colors.surfaceElevated)
        )
        .opacity(terr.enabled ? 1.0 : 0.62)
    }

    private var toggleBinding: Binding<Bool> {
        Binding(
            get: { terr.enabled },
            set: { onToggle($0) }
        )
    }

    @ViewBuilder
    private func capabilityGroup(_ title: String, items: [TerrCallable]) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text(title)
                    .font(Autumn.typography.captionStrong)
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.name)
                            .font(.system(.caption, design: .monospaced).weight(.medium))
                        Text(schemaSummary(for: item))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }
        }
    }

    private func schemaSummary(for item: TerrCallable) -> String {
        guard !item.parameters.isEmpty else {
            return item.description.isEmpty ? "无参数" : item.description
        }
        let params = item.parameters.map { parameter in
            "\(parameter.name):\(parameter.type)\(parameter.required ? "" : "?")"
        }
        return params.joined(separator: ", ")
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
