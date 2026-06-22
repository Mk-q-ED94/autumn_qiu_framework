import SwiftUI

enum WorkspaceInspectorMode: String, CaseIterable, Identifiable {
    case run
    case environment

    var id: String { rawValue }

    var title: String {
        switch self {
        case .run: return "运行"
        case .environment: return "环境"
        }
    }

    var icon: String {
        switch self {
        case .run: return "point.3.connected.trianglepath.dotted"
        case .environment: return "gauge.with.dots.needle.50percent"
        }
    }
}

struct WorkspaceInspectorView: View {
    @Binding var mode: WorkspaceInspectorMode
    let trace: WorkflowTrace?
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        VStack(spacing: 0) {
            Picker("检视内容", selection: $mode) {
                ForEach(WorkspaceInspectorMode.allCases) { mode in
                    Label(mode.title, systemImage: mode.icon).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(Qcowork.spacing.md)

            Divider()

            switch mode {
            case .run:
                MessageInspectorView(trace: trace)
            case .environment:
                EnvironmentInspectorView(settings: settings, localServer: localServer)
            }
        }
        .background(.regularMaterial)
    }
}

private struct EnvironmentInspectorView: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Qcowork.spacing.md) {
                StatusPanel(settings: settings, localServer: localServer)
                RoutePanel(
                    routeMode: settings.routeMode,
                    routeOverride: settings.activeRouteOverride
                )
                ModelStack(settings: settings)
                CapabilityLocationPanel()
            }
            .padding(Qcowork.spacing.md)
        }
        .background(.regularMaterial)
    }
}

private struct StatusPanel: View {
    let settings: AppSettings
    let localServer: LocalServerManager

    var body: some View {
        QcoworkCard {
            VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
                Text("状态")
                    .font(Qcowork.typography.headline)
                Divider()
                LabeledRow(label: "本地服务", value: localServer.statusText, tone: statusTone)
                LabeledRow(label: "服务器", value: settings.serverURL)
            }
        }
    }

    private var statusTone: QcoworkBadge.Tone {
        let status = localServer.statusText
        if status.contains("已") { return .success }
        if status.contains("失败") { return .danger }
        if status.contains("启动中") || status.contains("检测中") || status.contains("更新") {
            return .warning
        }
        return .neutral
    }
}

private struct RoutePanel: View {
    let routeMode: String
    let routeOverride: String?

    var body: some View {
        QcoworkCard {
            VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
                HStack {
                    Text("默认路由")
                        .font(Qcowork.typography.headline)
                    Spacer()
                    QcoworkBadge(route.title, icon: route.icon, tone: .accent)
                }

                if let routeOverride,
                   let override = MissionRouteMode(rawValue: routeOverride) {
                    HStack {
                        Text("本次覆盖")
                            .font(Qcowork.typography.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        QcoworkBadge(override.title, icon: override.icon, tone: .warning)
                    }
                }

                Divider()
                Text(route.detail)
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var route: MissionRouteMode {
        MissionRouteMode(rawValue: routeMode) ?? .auto
    }
}

private struct ModelStack: View {
    let settings: AppSettings

    var body: some View {
        QcoworkCard {
            VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
                Text("模型 A1 / A2 / A3")
                    .font(Qcowork.typography.headline)
                Divider()
                VStack(spacing: Qcowork.spacing.sm) {
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
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: Qcowork.spacing.xs) {
                Text(slot.title)
                    .font(Qcowork.typography.captionStrong)
                QcoworkBadge(state.title, tone: state.tone)
            }
            Text(modelName)
                .font(Qcowork.typography.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Qcowork.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                .fill(Qcowork.colors.surfaceElevated)
        )
    }

    private var modelName: String {
        guard let model = config.model, !model.isEmpty else { return "未选择模型" }
        return model
    }
}

private struct CapabilityLocationPanel: View {
    var body: some View {
        QcoworkCard {
            HStack(alignment: .top, spacing: Qcowork.spacing.sm) {
                Image(systemName: "puzzlepiece.extension")
                    .foregroundStyle(Qcowork.colors.sage)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: Qcowork.spacing.xs) {
                    Text("能力域")
                        .font(Qcowork.typography.captionStrong)
                    Text("Terr 启停、工具清单与 MCP 连接统一在侧栏的“能力域”页面管理。")
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private struct LabeledRow: View {
    let label: String
    let value: String
    var tone: QcoworkBadge.Tone?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(Qcowork.typography.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if let tone {
                QcoworkBadge(value, tone: tone)
            } else {
                Text(value)
                    .font(Qcowork.typography.caption)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }
}
