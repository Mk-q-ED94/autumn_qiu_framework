import SwiftUI

struct OllamaPanel: View {
    let status: OllamaStatus?
    let installedModels: [OllamaModel]
    let recommendedModels: [OllamaRecommendedModel]
    let selectedModel: String
    let isLoading: Bool
    let pullingModel: String?
    let pullProgress: String?
    let errorMessage: String?
    let refresh: () -> Void
    let useModel: (String) -> Void
    let pullModel: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Qcowork.spacing.md) {
            HStack {
                Label("本地模型 · Ollama", systemImage: "externaldrive.connected.to.line.below")
                    .font(Qcowork.typography.captionStrong)
                Spacer()
                statusBadge
                Button(action: refresh) {
                    if isLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .buttonStyle(.borderless)
                .help("刷新 Ollama 状态")
            }

            if let status {
                HStack(alignment: .firstTextBaseline, spacing: Qcowork.spacing.xs) {
                    Image(systemName: status.running ? "network" : "exclamationmark.triangle")
                        .foregroundStyle(status.running ? Qcowork.colors.success : Qcowork.colors.warning)
                    Text(status.running
                         ? "管理端点：\(status.baseURL)"
                         : "未连接到 \(status.baseURL)")
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.middle)
                }
            }

            if !installedModels.isEmpty {
                VStack(alignment: .leading, spacing: Qcowork.spacing.xs) {
                    Text("已安装")
                        .font(Qcowork.typography.captionStrong)
                    ForEach(installedModels) { model in
                        HStack(spacing: Qcowork.spacing.sm) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(model.name)
                                    .font(.system(.caption, design: .monospaced).weight(.semibold))
                                Text(modelDetail(model))
                                    .font(Qcowork.typography.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if model.name == selectedModel {
                                QcoworkBadge("A4", icon: "checkmark.circle.fill", tone: .success)
                            } else {
                                Button("用于 A4") { useModel(model.name) }
                                    .controlSize(.small)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }

            if !recommendedModels.isEmpty {
                VStack(alignment: .leading, spacing: Qcowork.spacing.xs) {
                    Text("推荐")
                        .font(Qcowork.typography.captionStrong)
                    ForEach(recommendedModels) { model in
                        HStack(spacing: Qcowork.spacing.sm) {
                            VStack(alignment: .leading, spacing: 1) {
                                HStack(spacing: Qcowork.spacing.xs) {
                                    Text(model.label)
                                        .font(Qcowork.typography.captionMedium)
                                    if model.recommended {
                                        QcoworkBadge("推荐", tone: .accent)
                                    }
                                }
                                Text("\(model.name) · \(model.size) · \(model.note)")
                                    .font(Qcowork.typography.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if pullingModel == model.name {
                                Text(pullProgress ?? "拉取中")
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            } else if installedModels.contains(where: { $0.name == model.name }) {
                                Button("用于 A4") { useModel(model.name) }
                                    .controlSize(.small)
                            } else {
                                Button("拉取") { pullModel(model.name) }
                                    .controlSize(.small)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }

            if let errorMessage, !errorMessage.isEmpty {
                HStack(alignment: .top, spacing: Qcowork.spacing.sm) {
                    Image(systemName: "lightbulb.max")
                        .foregroundStyle(Qcowork.colors.gold)
                    Text(errorMessage)
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(Qcowork.colors.danger)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(Qcowork.spacing.sm)
                .background(
                    RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                        .fill(Qcowork.colors.warning.opacity(0.10))
                )
            }
        }
        .padding(.vertical, Qcowork.spacing.xs)
    }

    @ViewBuilder
    private var statusBadge: some View {
        if let status {
            if status.running {
                QcoworkBadge(status.version.map { "运行中 · \($0)" } ?? "运行中",
                            icon: "checkmark.circle.fill",
                            tone: .success)
            } else {
                QcoworkBadge("未运行", icon: "xmark.circle", tone: .warning)
            }
        } else {
            QcoworkBadge("未检测", tone: .neutral)
        }
    }

    private func modelDetail(_ model: OllamaModel) -> String {
        var parts: [String] = []
        if let parameterSize = model.parameterSize { parts.append(parameterSize) }
        if let family = model.family { parts.append(family) }
        if let size = model.size { parts.append(formatBytes(size)) }
        return parts.isEmpty ? "本地模型" : parts.joined(separator: " · ")
    }

    private func formatBytes(_ bytes: Int) -> String {
        let gb = Double(bytes) / 1_073_741_824
        if gb >= 1 { return String(format: "%.1f GB", gb) }
        return String(format: "%.0f MB", Double(bytes) / 1_048_576)
    }
}
