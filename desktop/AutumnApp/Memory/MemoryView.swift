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
            switch vm.viewMode {
            case .memory:
                statsStrip
                Divider()
                memoryContent
            case .accessLog:
                accessLogStatsStrip
                Divider()
                accessLogContent
            case .pushPreview:
                pushPreviewStrip
                Divider()
                pushPreviewContent
            }
        }
        .navigationTitle(navTitle)
        .task { await refreshCurrentMode() }
        .onChange(of: vm.viewMode) { _, _ in
            Task { await refreshCurrentMode() }
        }
        .onChange(of: vm.selectedArea) { _, _ in
            vm.selectedMode = nil
            Task { await refreshCurrentMode() }
        }
    }

    private var navTitle: String {
        vm.viewMode == .accessLog ? "Mom1 访问审计" : vm.viewMode.title
    }

    private func refreshCurrentMode(forcePushPreview: Bool = false) async {
        switch vm.viewMode {
        case .memory:
            await vm.load()
        case .accessLog:
            await vm.loadFourDStatus()
            await vm.loadAccessLog()
        case .pushPreview:
            await vm.loadFourDStatus()
            if forcePushPreview || vm.hasRunPush {
                await vm.runPushPreview()
            }
        }
    }

    // ── toolbar ─────────────────────────────────────────────────────────────────

    private var toolbar: some View {
        HStack(spacing: Autumn.spacing.md) {
            Picker("视图", selection: $vm.viewMode) {
                ForEach(MemoryViewModel.ViewMode.allCases) { mode in
                    Label(mode.title, systemImage: mode.icon).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 320)

            if vm.viewMode == .accessLog {
                AutumnBadge("Mom1 受治理访问", icon: "checkmark.shield.fill", tone: .warning)
            } else {
                Picker("记忆区", selection: $vm.selectedArea) {
                    ForEach(MemoryArea.allCases) { area in
                        Text(area.title).tag(area)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 260)
                AutumnBadge(vm.selectedArea.subtitle, tone: .accent)
            }

            Spacer()

            if vm.viewMode == .memory {
                Button {
                    Task { await vm.autoAnnotate() }
                } label: {
                    if vm.isAutoAnnotating {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Autumn.colors.memory)
                    }
                }
                .buttonStyle(.plain)
                .help("用 A4 自动推断当前记忆区的 4D 维度")
                .disabled(vm.isLoading || vm.isAutoAnnotating)

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
            }

            Button {
                Task { await refreshCurrentMode(forcePushPreview: vm.viewMode == .pushPreview) }
            } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .help("刷新")
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.bar)
    }

    // ── 4D status badges (shared) ────────────────────────────────────────────────

    @ViewBuilder
    private func fourdStatusBadges() -> some View {
        if let status = vm.fourdStatus {
            AutumnBadge(status.fourdMemoryEnabled ? "4D 排序 开" : "4D 排序 关",
                        icon: "brain",
                        tone: status.fourdMemoryEnabled ? .memory : .neutral)
            AutumnBadge(status.fourdPushOnTurn ? "推送 开" : "推送 关",
                        icon: "bolt.fill",
                        tone: status.fourdPushOnTurn ? .warning : .neutral)
            AutumnBadge(status.mom1AccessEnabled ? "Mom1 通道 开" : "Mom1 通道 关",
                        icon: status.mom1AccessEnabled ? "checkmark.shield.fill" : "shield.slash",
                        tone: status.mom1AccessEnabled ? .success : .neutral)
        } else {
            AutumnBadge("4D 状态未知", icon: "questionmark.circle", tone: .neutral)
        }
    }

    // ── memory stats strip ───────────────────────────────────────────────────────

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
            fourdStatusBadges()
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

    // ── access log stats strip ───────────────────────────────────────────────────

    private var accessLogStatsStrip: some View {
        HStack(spacing: Autumn.spacing.md) {
            MemoryStat(label: "总计", value: "\(vm.accessLogTotal)", icon: "list.bullet.clipboard")
            MemoryStat(label: "已批准", value: "\(vm.grantedCount)", icon: "checkmark.shield.fill",
                       color: Autumn.colors.success)
            MemoryStat(label: "已拒绝", value: "\(vm.deniedCount)", icon: "xmark.shield.fill",
                       color: Autumn.colors.danger)
            Spacer()
            fourdStatusBadges()
            AutumnBadge("WP4 审计", icon: "shield.lefthalf.filled", tone: .warning)
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.regularMaterial)
    }

    // ── push preview strip ───────────────────────────────────────────────────────

    private var pushPreviewStrip: some View {
        HStack(spacing: Autumn.spacing.md) {
            MemoryStat(label: "命中", value: "\(vm.pushFired.count)", icon: "bolt.fill",
                       color: Autumn.colors.memory)
            AutumnBadge(vm.selectedArea.title, icon: "tray.full", tone: .accent)
            Spacer()
            fourdStatusBadges()
            AutumnBadge(vm.pushEnabled ? "回合推送已启用" : "回合推送未启用",
                        icon: vm.pushEnabled ? "checkmark.circle.fill" : "circle.dashed",
                        tone: vm.pushEnabled ? .success : .neutral)
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.regularMaterial)
    }

    // ── memory content ───────────────────────────────────────────────────────────

    @ViewBuilder
    private var modeFilterBar: some View {
        let counts = vm.modeCounts
        if !counts.isEmpty {
            HStack(spacing: Autumn.spacing.xs) {
                ModeFilterChip(label: "全部", icon: "square.grid.2x2", count: vm.entries.count,
                               color: Autumn.colors.muted, isSelected: vm.selectedMode == nil) {
                    vm.selectedMode = nil
                }
                ForEach(FourDUseMode.allCases) { mode in
                    if let count = counts[mode] {
                        ModeFilterChip(label: mode.label, icon: mode.icon, count: count,
                                       color: mode.tone.foreground,
                                       isSelected: vm.selectedMode == mode) {
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
    private var memoryContent: some View {
        if vm.isLoading {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.errorMessage {
            EmptyStateView(icon: "exclamationmark.triangle", title: "无法读取记忆",
                           message: error, actionTitle: "重试") { Task { await vm.load() } }
        } else if vm.entries.isEmpty {
            EmptyStateView(icon: "tray", title: "暂无记忆", message: vm.selectedArea.subtitle)
        } else {
            VStack(spacing: 0) {
                modeFilterBar
                if vm.filteredEntries.isEmpty {
                    EmptyStateView(icon: "line.3.horizontal.decrease.circle", title: "无匹配记忆",
                                   message: "当前筛选下没有条目", actionTitle: "清除筛选") {
                        vm.selectedMode = nil
                    }
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                            ForEach(vm.filteredEntries) { entry in
                                MemoryEntryRow(entry: entry, onAnnotate: { mode, cues in
                                    Task { await vm.annotate(entry: entry, mode: mode, cues: cues) }
                                })
                            }
                        }
                        .padding(Autumn.spacing.lg)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    // ── access log content ───────────────────────────────────────────────────────

    @ViewBuilder
    private var accessLogContent: some View {
        if vm.isLoadingAccessLog {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.accessLogError {
            EmptyStateView(icon: "exclamationmark.triangle", title: "无法读取审计日志",
                           message: error, actionTitle: "重试") { Task { await vm.loadAccessLog() } }
        } else if vm.accessLogEntries.isEmpty {
            EmptyStateView(icon: "shield", title: "暂无审计记录",
                           message: "Mom2/Mom3 尚未发起 Mom1 访问请求")
        } else {
            VStack(spacing: 0) {
                accessLogVerdictFilter
                if vm.filteredAccessEntries.isEmpty {
                    EmptyStateView(icon: "line.3.horizontal.decrease.circle",
                                   title: "无匹配记录", message: "当前筛选下没有条目",
                                   actionTitle: "清除筛选") { vm.accessLogVerdict = nil }
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                            ForEach(vm.filteredAccessEntries) { entry in
                                AccessLogEntryRow(entry: entry)
                            }
                        }
                        .padding(Autumn.spacing.lg)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private var accessLogVerdictFilter: some View {
        HStack(spacing: Autumn.spacing.xs) {
            VerdictFilterChip(label: "全部", icon: "shield", count: vm.accessLogEntries.count,
                              color: Autumn.colors.muted, isSelected: vm.accessLogVerdict == nil) {
                vm.accessLogVerdict = nil
            }
            VerdictFilterChip(label: "已批准", icon: "checkmark.shield.fill", count: vm.grantedCount,
                              color: Autumn.colors.success, isSelected: vm.accessLogVerdict == "granted") {
                vm.accessLogVerdict = vm.accessLogVerdict == "granted" ? nil : "granted"
            }
            VerdictFilterChip(label: "已拒绝", icon: "xmark.shield.fill", count: vm.deniedCount,
                              color: Autumn.colors.danger, isSelected: vm.accessLogVerdict == "denied") {
                vm.accessLogVerdict = vm.accessLogVerdict == "denied" ? nil : "denied"
            }
            Spacer()
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
    }

    // ── push preview content ───────────────────────────────────────────────────

    @ViewBuilder
    private var pushPreviewContent: some View {
        VStack(spacing: 0) {
            // Query bar
            HStack(spacing: Autumn.spacing.sm) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                TextField("输入一个回合的内容，预览会触发哪些记忆…", text: $vm.pushQuery)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await vm.runPushPreview() } }
                Button {
                    Task { await vm.runPushPreview() }
                } label: {
                    if vm.isLoadingPush {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("预览")
                    }
                }
                .disabled(vm.isLoadingPush)
            }
            .padding(.horizontal, Autumn.spacing.lg)
            .padding(.vertical, Autumn.spacing.sm)

            Divider()

            if let error = vm.pushError {
                EmptyStateView(icon: "exclamationmark.triangle", title: "预览失败",
                               message: error, actionTitle: "重试") { Task { await vm.runPushPreview() } }
            } else if !vm.hasRunPush {
                EmptyStateView(icon: "bolt.badge.clock", title: "推送预览",
                               message: "输入一个回合内容，看看 CONSTRAIN/REMIND 记忆会不会被自动注入到提示词中。")
            } else if vm.pushFired.isEmpty {
                EmptyStateView(icon: "bolt.slash", title: "无命中",
                               message: "当前上下文不会触发任何推送记忆。只有标注为约束/提醒、且触发线索匹配的记忆才会命中。")
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                        ForEach(vm.pushFired) { entry in
                            PushPreviewEntryRow(entry: entry)
                        }
                        if !vm.pushFragment.isEmpty {
                            injectedFragmentCard
                        }
                    }
                    .padding(Autumn.spacing.lg)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private var injectedFragmentCard: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                HStack(spacing: Autumn.spacing.xs) {
                    Image(systemName: "text.insert").font(.system(size: 10, weight: .bold))
                    Text("注入提示词片段").font(Autumn.typography.captionStrong)
                }
                .foregroundStyle(Autumn.colors.memory)
                Text(vm.pushFragment)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

// ── shared sub-views ─────────────────────────────────────────────────────────

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
                Text(label).font(.system(size: 9)).foregroundStyle(.tertiary)
                Text(value).font(.system(size: 11, weight: .semibold, design: .monospaced))
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
                Image(systemName: icon).font(.system(size: 9, weight: .bold))
                Text(label).font(Autumn.typography.captionStrong)
                Text("\(count)")
                    .font(.system(size: 9, weight: .semibold, design: .monospaced))
                    .foregroundStyle(isSelected ? color : .secondary)
                    .padding(.horizontal, 4).padding(.vertical, 1)
                    .background(Capsule().fill(.background.opacity(0.6)))
            }
            .foregroundStyle(isSelected ? color : .secondary)
            .padding(.horizontal, Autumn.spacing.sm).padding(.vertical, 3)
            .background(Capsule(style: .continuous)
                .fill(isSelected ? color.opacity(0.14) : Autumn.colors.surfaceElevated))
            .overlay(Capsule(style: .continuous)
                .strokeBorder(isSelected ? color.opacity(0.4) : Color.secondary.opacity(0.14),
                              lineWidth: Autumn.stroke.thin))
        }
        .buttonStyle(.plain)
        .animation(Autumn.motion.soft, value: isSelected)
    }
}

private typealias VerdictFilterChip = ModeFilterChip

private struct MemoryEntryRow: View {
    let entry: MemoryEntry
    var onAnnotate: ((FourDUseMode, String) -> Void)?
    @State private var isExpanded: Bool = false
    @State private var annotateMode: FourDUseMode = .context
    @State private var annotateCues: String = ""

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
                    Text(entry.title).font(Autumn.typography.headline)
                    if let time = entry.relativeTime {
                        Text(time).font(Autumn.typography.caption).foregroundStyle(.tertiary)
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
                    if entry.has4DData { fourdSection; Divider() }
                    Grid(alignment: .leading, horizontalSpacing: Autumn.spacing.md, verticalSpacing: 4) {
                        ForEach(entry.sortedKeys, id: \.self) { key in
                            GridRow {
                                Text(key).font(Autumn.typography.caption).foregroundStyle(.secondary)
                                Text(entry.values[key]?.formatted ?? "")
                                    .font(Autumn.typography.caption).textSelection(.enabled)
                            }
                        }
                    }
                    .transition(.opacity)
                    if onAnnotate != nil, entry.entryID != nil {
                        Divider()
                        annotateControl
                    }
                }
                HStack {
                    if let importance = entry.importance, importance != 1.0 {
                        AutumnChip(String(format: "重要度 %.1f", importance),
                                   icon: "waveform.path.ecg",
                                   color: entry.isPinned ? Autumn.colors.warning : Autumn.colors.muted,
                                   size: .compact)
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
    private var annotateControl: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            HStack(spacing: Autumn.spacing.xs) {
                Image(systemName: "wand.and.stars").font(.system(size: 9, weight: .bold))
                Text("标注 4D 维度").font(Autumn.typography.captionStrong)
            }
            .foregroundStyle(Autumn.colors.memory)
            HStack(spacing: Autumn.spacing.sm) {
                Picker("模式", selection: $annotateMode) {
                    ForEach(FourDUseMode.allCases) { mode in
                        Text(mode.label).tag(mode)
                    }
                }
                .pickerStyle(.menu)
                .frame(width: 110)
                TextField("触发线索（逗号分隔，可选）", text: $annotateCues)
                    .textFieldStyle(.roundedBorder)
                Button("应用") {
                    onAnnotate?(annotateMode, annotateCues)
                }
                .controlSize(.small)
            }
        }
        .padding(Autumn.spacing.sm)
        .background(Autumn.colors.memory.opacity(0.06), in: RoundedRectangle(cornerRadius: Autumn.radius.sm))
        .transition(.opacity)
    }

    @ViewBuilder
    private var fourdSection: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            HStack(spacing: Autumn.spacing.xs) {
                Image(systemName: "brain").font(.system(size: 9, weight: .bold))
                Text("四维").font(Autumn.typography.captionStrong)
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
                        Text("\(count) 次激活").font(.system(.caption, design: .monospaced))
                    }
                }
                if let intent = entry.aimIntent {
                    GridRow {
                        dimensionLabel("aim.intent")
                        Text(intent).font(Autumn.typography.caption).textSelection(.enabled)
                    }
                }
            }
            if !entry.aimScope.isEmpty { chipRow(label: "aim.scope", items: entry.aimScope, color: Autumn.colors.info) }
            if !entry.triggerCues.isEmpty { chipRow(label: "trigger.cues", items: entry.triggerCues, color: Autumn.colors.memory) }
        }
        .padding(Autumn.spacing.sm)
        .background(Autumn.colors.memory.opacity(0.06), in: RoundedRectangle(cornerRadius: Autumn.radius.sm))
        .transition(.opacity)
    }

    private func dimensionLabel(_ text: String) -> some View {
        Text(text).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
    }

    private func chipRow(label: String, items: [String], color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            dimensionLabel(label)
            FlowLayout(spacing: Autumn.spacing.xs) {
                ForEach(items, id: \.self) { AutumnChip($0, color: color, size: .compact) }
            }
        }
    }
}

// ── PushPreviewEntryRow ──────────────────────────────────────────────────────

private struct PushPreviewEntryRow: View {
    let entry: PushPreviewEntry

    var body: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack(spacing: Autumn.spacing.xs) {
                    if let mode = entry.fourdMode {
                        AutumnBadge(mode.label, icon: mode.icon, tone: mode.tone)
                    }
                    if !entry.intent.isEmpty {
                        Text(entry.intent)
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    AutumnChip(String(format: "分数 %.2f", entry.score),
                               icon: "bolt.fill", color: Autumn.colors.memory, size: .compact)
                }
                Text(entry.text)
                    .font(Autumn.typography.callout)
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                if !entry.cues.isEmpty {
                    FlowLayout(spacing: Autumn.spacing.xs) {
                        ForEach(entry.cues, id: \.self) { cue in
                            AutumnChip(cue, icon: "bolt.fill", color: Autumn.colors.memory, size: .compact)
                        }
                    }
                }
            }
        }
    }
}

// ── AccessLogEntryRow ────────────────────────────────────────────────────────

private struct AccessLogEntryRow: View {
    let entry: AccessLogEntry
    @State private var isExpanded = false

    var body: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.xs) {
                    AutumnBadge(
                        entry.isGranted ? "已批准" : "已拒绝",
                        icon: entry.isGranted ? "checkmark.shield.fill" : "xmark.shield.fill",
                        tone: entry.isGranted ? .success : .danger
                    )
                    AutumnBadge(entry.requester.uppercased(), tone: .memory)
                    Spacer()
                    Text(entry.relativeTime)
                        .font(Autumn.typography.caption)
                        .foregroundStyle(.tertiary)
                }
                Text(entry.query)
                    .font(Autumn.typography.callout)
                    .foregroundStyle(.primary)
                    .lineLimit(isExpanded ? nil : 2)
                    .textSelection(.enabled)
                if isExpanded {
                    Divider()
                    Grid(alignment: .leading, horizontalSpacing: Autumn.spacing.md, verticalSpacing: 5) {
                        detailRow(label: "原因", value: entry.reason)
                        if !entry.decisionReason.isEmpty {
                            detailRow(label: "A1 判断", value: entry.decisionReason)
                        }
                        if let mediatedBy = entry.mediatedBy, !mediatedBy.isEmpty {
                            detailRow(label: "调解方", value: mediatedBy)
                        }
                        GridRow {
                            Text("条目数").font(Autumn.typography.caption).foregroundStyle(.secondary)
                            Text("\(entry.entryIds.count) 条")
                                .font(.system(.caption, design: .monospaced))
                        }
                        if entry.redact {
                            GridRow {
                                Text("脱敏").font(Autumn.typography.caption).foregroundStyle(.secondary)
                                AutumnBadge("已脱敏", icon: "eye.slash", tone: .warning)
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

    private func detailRow(label: String, value: String) -> some View {
        GridRow {
            Text(label)
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(Autumn.typography.caption)
                .textSelection(.enabled)
        }
    }
}
