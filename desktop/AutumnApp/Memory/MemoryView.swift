import SwiftUI

struct MemoryView: View {
    @StateObject private var vm: MemoryViewModel

    init(settings: AppSettings) {
        _vm = StateObject(wrappedValue: MemoryViewModel(settings: settings))
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar

            Divider()

            statsStrip

            Divider()

            content
        }
        .navigationTitle("记忆")
        .task { await vm.load() }
        .onChange(of: vm.selectedArea) { _, _ in
            Task { await vm.load() }
        }
    }

    private var toolbar: some View {
        HStack(spacing: Autumn.spacing.md) {
            Picker("记忆区", selection: $vm.selectedArea) {
                ForEach(MemoryArea.allCases) { area in
                    Text(area.title).tag(area)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 260)

            AutumnBadge(vm.selectedArea.subtitle, tone: .accent)

            Spacer()

            Button {
                Task { await vm.consolidateSelectedArea() }
            } label: {
                if vm.isConsolidating {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "rectangle.compress.vertical")
                        .font(.system(size: 13, weight: .medium))
                }
            }
            .buttonStyle(.plain)
            .help("用 WP4/A4 归并当前记忆区")
            .disabled(vm.isLoading || vm.isConsolidating)

            Button {
                Task { await vm.load() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .help("刷新")
            .disabled(vm.isLoading)
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.bar)
    }

    private var statsStrip: some View {
        HStack(spacing: Autumn.spacing.md) {
            if let stats = vm.stats {
                MemoryStat(label: "总数", value: "\(stats.total)", icon: "tray.full")
                MemoryStat(label: "置顶", value: "\(stats.pinned)", icon: "pin.fill")
                MemoryStat(label: "过期", value: "\(stats.expired)", icon: "timer")
                MemoryStat(label: "均值", value: String(format: "%.2f", stats.avgImportance), icon: "waveform.path.ecg")
                AutumnBadge(stats.hasVector ? "Vector" : "No Vector",
                            icon: stats.hasVector ? "point.3.connected.trianglepath.dotted" : "circle.dashed",
                            tone: stats.hasVector ? .info : .neutral)
            } else {
                Text("等待 WP4 统计")
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if let overview = vm.overview {
                AutumnBadge("WP4 · \(overview.total)", icon: "brain", tone: .accent)
            }
            if let message = vm.actionMessage {
                Text(message)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.regularMaterial)
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.errorMessage {
            EmptyStateView(
                icon: "exclamationmark.triangle",
                title: "无法读取记忆",
                message: error,
                actionTitle: "重试",
                action: { Task { await vm.load() } }
            )
        } else if vm.entries.isEmpty {
            EmptyStateView(
                icon: "tray",
                title: "暂无记忆",
                message: vm.selectedArea.subtitle
            )
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                    ForEach(vm.entries) { entry in
                        MemoryEntryRow(entry: entry)
                    }
                }
                .padding(Autumn.spacing.lg)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

private struct MemoryStat: View {
    let label: String
    let value: String
    let icon: String

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 0) {
                Text(label)
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                Text(value)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
            }
        }
    }
}

private struct MemoryEntryRow: View {
    let entry: MemoryEntry
    @State private var isExpanded: Bool = false

    var body: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack(alignment: .firstTextBaseline) {
                    Text(entry.title)
                        .font(Autumn.typography.headline)
                    Spacer()
                    if let mode = entry.useMode {
                        AutumnBadge(entry.useModeLabel, icon: useModeIcon(mode), tone: useModeTone(mode))
                    }
                    AutumnBadge(entry.area.title, tone: .neutral)
                }

                Text(entry.preview)
                    .font(Autumn.typography.callout)
                    .foregroundStyle(.primary)
                    .lineLimit(isExpanded ? nil : 3)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)

                if isExpanded {
                    Divider()
                    if entry.has4DData {
                        fourdSection
                        Divider()
                    }
                    Grid(alignment: .leading, horizontalSpacing: Autumn.spacing.md, verticalSpacing: 4) {
                        ForEach(entry.sortedKeys, id: \.self) { key in
                            GridRow {
                                Text(key)
                                    .font(Autumn.typography.caption)
                                    .foregroundStyle(.secondary)
                                Text(entry.values[key]?.formatted ?? "")
                                    .font(Autumn.typography.caption)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                    .transition(.opacity)
                }

                HStack {
                    Spacer()
                    AutumnGhostButton(action: {
                        withAnimation(Autumn.motion.snappy) { isExpanded.toggle() }
                    }) {
                        HStack(spacing: Autumn.spacing.xs) {
                            Text(isExpanded ? "收起" : "展开详情")
                            Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var fourdSection: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            Text("四维")
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(Color.purple)

            Grid(alignment: .leading, horizontalSpacing: Autumn.spacing.md, verticalSpacing: 3) {
                if let mode = entry.useMode {
                    GridRow {
                        Text("use.mode")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        AutumnBadge(entry.useModeLabel, tone: useModeTone(mode))
                    }
                }
                if let count = entry.useCount {
                    GridRow {
                        Text("use.count")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        Text("\(count)")
                            .font(.system(.caption, design: .monospaced))
                    }
                }
                if let intent = entry.aimIntent {
                    GridRow {
                        Text("aim.intent")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        Text(intent)
                            .font(Autumn.typography.caption)
                            .textSelection(.enabled)
                    }
                }
                if !entry.triggerCues.isEmpty {
                    GridRow {
                        Text("trigger.cues")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        Text(entry.triggerCues.joined(separator: ", "))
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
            }
        }
        .padding(Autumn.spacing.sm)
        .background(Color.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: Autumn.radius.sm))
        .transition(.opacity)
    }

    private func useModeIcon(_ mode: String) -> String {
        switch mode {
        case "constrain": return "lock.fill"
        case "remind":    return "bell.fill"
        case "summarize": return "doc.text.fill"
        default:          return "circle.fill"
        }
    }

    private func useModeTone(_ mode: String) -> AutumnBadge.Tone {
        switch mode {
        case "constrain": return .danger
        case "remind":    return .warning
        case "summarize": return .info
        default:          return .neutral
        }
    }
}
