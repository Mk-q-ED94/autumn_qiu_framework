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
            vm.selectedMode = nil
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
                if vm.annotatedCount > 0 {
                    MemoryStat(label: "四维", value: "\(vm.annotatedCount)", icon: "brain",
                               color: Autumn.colors.memory)
                }
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
                AutumnBadge("WP4 · \(overview.total)", icon: "brain", tone: .memory)
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

    /// Use-mode filter chips — shown only when the area has 4D-mode entries,
    /// so plain conversation areas keep the original uncluttered layout.
    @ViewBuilder
    private var modeFilterBar: some View {
        let counts = vm.modeCounts
        if !counts.isEmpty {
            HStack(spacing: Autumn.spacing.xs) {
                ModeFilterChip(
                    label: "全部",
                    icon: "square.grid.2x2",
                    count: vm.entries.count,
                    color: Autumn.colors.muted,
                    isSelected: vm.selectedMode == nil
                ) {
                    vm.selectedMode = nil
                }
                ForEach(FourDUseMode.allCases) { mode in
                    if let count = counts[mode] {
                        ModeFilterChip(
                            label: mode.label,
                            icon: mode.icon,
                            count: count,
                            color: mode.tone.foreground,
                            isSelected: vm.selectedMode == mode
                        ) {
                            vm.selectedMode = vm.selectedMode == mode ? nil : mode
                        }
                    }
                }
                Spacer()
            }
            .padding(.horizontal, Autumn.spacing.lg)
            .padding(.vertical, Autumn.spacing.sm)
        }
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
            VStack(spacing: 0) {
                modeFilterBar

                if vm.filteredEntries.isEmpty {
                    EmptyStateView(
                        icon: "line.3.horizontal.decrease.circle",
                        title: "无匹配记忆",
                        message: "当前筛选下没有条目",
                        actionTitle: "清除筛选",
                        action: { vm.selectedMode = nil }
                    )
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                            ForEach(vm.filteredEntries) { entry in
                                MemoryEntryRow(entry: entry)
                            }
                        }
                        .padding(Autumn.spacing.lg)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }
}

private struct MemoryStat: View {
    let label: String
    let value: String
    let icon: String
    var color: Color = .secondary

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(color)
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

private struct ModeFilterChip: View {
    let label: String
    let icon: String
    let count: Int
    let color: Color
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Autumn.spacing.xs) {
                Image(systemName: icon)
                    .font(.system(size: 9, weight: .bold))
                Text(label)
                    .font(Autumn.typography.captionStrong)
                Text("\(count)")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    .foregroundStyle(isSelected ? color : .secondary)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(.background.opacity(0.6)))
            }
            .foregroundStyle(isSelected ? color : .secondary)
            .padding(.horizontal, Autumn.spacing.sm)
            .padding(.vertical, 3)
            .background(
                Capsule(style: .continuous)
                    .fill(isSelected ? color.opacity(0.14) : Autumn.colors.surfaceElevated)
            )
            .overlay(
                Capsule(style: .continuous)
                    .strokeBorder(
                        isSelected ? color.opacity(0.4) : Color.secondary.opacity(0.14),
                        lineWidth: Autumn.stroke.thin
                    )
            )
        }
        .buttonStyle(.plain)
        .animation(Autumn.motion.soft, value: isSelected)
    }
}

private struct MemoryEntryRow: View {
    let entry: MemoryEntry
    @State private var isExpanded: Bool = false

    var body: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.xs) {
                    if entry.isPinned {
                        Image(systemName: "pin.fill")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Autumn.colors.warning)
                            .help("置顶 — 不会被淘汰")
                    }
                    Text(entry.title)
                        .font(Autumn.typography.headline)
                    if let time = entry.relativeTime {
                        Text(time)
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.tertiary)
                    }
                    Spacer()
                    if entry.has4DData, let mode = entry.fourdMode {
                        AutumnBadge(mode.label, icon: mode.icon, tone: mode.tone)
                    }
                    AutumnBadge(entry.area.title, tone: .neutral)
                }

                Text(entry.preview)
                    .font(Autumn.typography.callout)
                    .foregroundStyle(.primary)
                    .lineLimit(isExpanded ? nil : 3)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)

                if !entry.tags.isEmpty {
                    FlowLayout(spacing: Autumn.spacing.xs) {
                        ForEach(entry.tags, id: \.self) { tag in
                            AutumnChip(tag, icon: "tag.fill", color: Autumn.colors.muted, size: .compact)
                        }
                    }
                }

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
                    if let importance = entry.importance, importance != 1.0 {
                        AutumnChip(
                            String(format: "重要度 %.1f", importance),
                            icon: "waveform.path.ecg",
                            color: entry.isPinned ? Autumn.colors.warning : Autumn.colors.muted,
                            size: .compact
                        )
                    }
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
            HStack(spacing: Autumn.spacing.xs) {
                Image(systemName: "brain")
                    .font(.system(size: 9, weight: .bold))
                Text("四维")
                    .font(Autumn.typography.captionStrong)
            }
            .foregroundStyle(Autumn.colors.memory)

            Grid(alignment: .leading, horizontalSpacing: Autumn.spacing.md, verticalSpacing: 3) {
                if let mode = entry.fourdMode {
                    GridRow {
                        dimensionLabel("use.mode")
                        AutumnBadge(mode.label, icon: mode.icon, tone: mode.tone)
                    }
                }
                if let count = entry.useCount, count > 0 {
                    GridRow {
                        dimensionLabel("use.count")
                        Text("\(count) 次激活")
                            .font(.system(.caption, design: .monospaced))
                    }
                }
                if let intent = entry.aimIntent {
                    GridRow {
                        dimensionLabel("aim.intent")
                        Text(intent)
                            .font(Autumn.typography.caption)
                            .textSelection(.enabled)
                    }
                }
            }

            // Chip collections live outside the Grid: a wrapping layout inside
            // a grid cell is measured at unlimited width and can overflow.
            if !entry.aimScope.isEmpty {
                chipRow(label: "aim.scope", items: entry.aimScope, color: Autumn.colors.info)
            }
            if !entry.triggerCues.isEmpty {
                chipRow(label: "trigger.cues", items: entry.triggerCues, color: Autumn.colors.memory)
            }
        }
        .padding(Autumn.spacing.sm)
        .background(
            Autumn.colors.memory.opacity(0.06),
            in: RoundedRectangle(cornerRadius: Autumn.radius.sm)
        )
        .transition(.opacity)
    }

    private func dimensionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(.caption, design: .monospaced))
            .foregroundStyle(.secondary)
    }

    private func chipRow(label: String, items: [String], color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            dimensionLabel(label)
            FlowLayout(spacing: Autumn.spacing.xs) {
                ForEach(items, id: \.self) { item in
                    AutumnChip(item, color: color, size: .compact)
                }
            }
        }
    }
}
