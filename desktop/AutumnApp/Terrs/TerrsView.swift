import SwiftUI
#if os(macOS)
import AppKit
#endif

struct TerrsView: View {
    @StateObject private var vm: TerrsViewModel

    init(settings: AppSettings) {
        _vm = StateObject(wrappedValue: TerrsViewModel(settings: settings))
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider()
            content
        }
        .navigationTitle(NSLocalizedString("section.terrs.title", comment: ""))
        .task { await vm.load() }
    }

    // MARK: Toolbar

    private var toolbar: some View {
        HStack(spacing: Autumn.spacing.sm) {
            AutumnLogoMark(size: 24)
            VStack(alignment: .leading, spacing: 1) {
                Text("能力域")
                    .font(Autumn.typography.captionStrong)
                Text("Terr · Tool · Skill · MCP")
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
            }
            Divider()
                .frame(height: 22)
            AutumnChip("\(vm.enabledCount)/\(vm.terrs.count)",
                       icon: "puzzlepiece.extension", color: Autumn.colors.leaf)
            if vm.toolCount > 0 {
                AutumnChip("\(vm.toolCount)", icon: "wrench.and.screwdriver.fill", color: Autumn.colors.info)
            }
            if vm.skillCount > 0 {
                AutumnChip("\(vm.skillCount)", icon: "bolt.fill", color: Autumn.colors.warning)
            }
            if vm.mcpCount > 0 {
                AutumnChip("\(vm.mcpCount)", icon: "server.rack", color: Autumn.colors.success)
            }

            Spacer()

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

    // MARK: Content

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.terrs.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.errorMessage, vm.terrs.isEmpty {
            EmptyStateView(
                icon: "exclamationmark.triangle",
                title: "无法读取能力域",
                message: error,
                actionTitle: "重试",
                action: { Task { await vm.load() } }
            )
        } else if vm.terrs.isEmpty && vm.catalog.isEmpty {
            EmptyStateView(
                icon: "puzzlepiece.extension",
                title: "暂无已注册能力域",
                message: "服务端可设 AUTUMN_BUILTIN_TERRS=safe 注册内置域（time/math/text/data/encoding/collection）。"
            )
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Autumn.spacing.md) {
                    if !vm.terrs.isEmpty {
                        InvocationGuideCard(terrs: vm.terrs)
                        sectionHeader("已注册能力域", systemImage: "checkmark.seal")
                        ForEach(vm.terrs) { terr in
                            TerrCard(terr: terr, vm: vm)
                        }
                    }

                    if !vm.catalog.isEmpty {
                        sectionHeader("可用 MCP 目录", systemImage: "square.grid.2x2")
                            .padding(.top, Autumn.spacing.sm)
                        Text("框架已知的官方 MCP 服务器。在服务端用对应工厂函数注册后即可在上方启用。")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                        ForEach(vm.catalog) { mcp in
                            KnownMCPRow(mcp: mcp)
                        }
                    }
                }
                .padding(Autumn.spacing.lg)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func sectionHeader(_ title: String, systemImage: String) -> some View {
        HStack(spacing: Autumn.spacing.xs) {
            Image(systemName: systemImage)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
            Text(title)
                .font(Autumn.typography.headline)
        }
    }
}

// MARK: - Registered Terr card

private struct TerrCard: View {
    let terr: TerrSummary
    @ObservedObject var vm: TerrsViewModel
    @State private var isExpanded = false

    private var isToggling: Bool { vm.togglingName == terr.name }

    var body: some View {
        AutumnCard(padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                header

                if !terr.description.isEmpty {
                    Text(terr.description)
                        .font(Autumn.typography.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                countChips

                if isExpanded {
                    Divider()
                    detail
                        .transition(.opacity)
                }

                if hasDetail {
                    HStack {
                        Spacer()
                        AutumnGhostButton(action: {
                            withAnimation(Autumn.motion.snappy) { isExpanded.toggle() }
                        }) {
                            HStack(spacing: Autumn.spacing.xs) {
                                Text(isExpanded ? "收起" : "展开")
                                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            }
                        }
                    }
                }
            }
            .opacity(terr.enabled ? 1 : 0.55)
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.sm) {
            Text(terr.name)
                .font(Autumn.typography.headline)
            AutumnBadge(terr.enabled ? "已启用" : "已停用",
                        tone: terr.enabled ? .success : .neutral)
            Spacer()
            if isToggling {
                ProgressView().controlSize(.small)
            }
            Toggle("", isOn: Binding(
                get: { terr.enabled },
                set: { newValue in Task { await vm.setEnabled(terr, enabled: newValue) } }
            ))
            .labelsHidden()
            .toggleStyle(.switch)
            .controlSize(.mini)
            .disabled(isToggling)
        }
    }

    private var countChips: some View {
        HStack(spacing: Autumn.spacing.xs) {
            if !terr.tools.isEmpty {
                AutumnChip("\(terr.tools.count) tools", icon: "wrench.and.screwdriver.fill",
                           color: Autumn.colors.info, size: .compact)
            }
            if !terr.skills.isEmpty {
                AutumnChip("\(terr.skills.count) skills", icon: "bolt.fill",
                           color: Autumn.colors.warning, size: .compact)
            }
            if !terr.mcps.isEmpty {
                AutumnChip("\(terr.mcps.count) mcp", icon: "server.rack",
                           color: Autumn.colors.success, size: .compact)
            }
        }
    }

    private var hasDetail: Bool {
        !terr.tools.isEmpty || !terr.skills.isEmpty || !terr.mcps.isEmpty
    }

    @ViewBuilder
    private var detail: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            if !terr.tools.isEmpty {
                callableGroup(title: "Tools", icon: "wrench.and.screwdriver.fill",
                              color: Autumn.colors.info, items: terr.tools)
            }
            if !terr.skills.isEmpty {
                callableGroup(title: "Skills", icon: "bolt.fill",
                              color: Autumn.colors.warning, items: terr.skills)
            }
            if !terr.mcps.isEmpty {
                VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                    groupLabel("MCP", icon: "server.rack", color: Autumn.colors.success)
                    ForEach(terr.mcps) { mcp in
                        calloutRow(name: mcp.name, description: mcp.description)
                    }
                }
            }
        }
    }

    private func callableGroup(title: String, icon: String, color: Color, items: [TerrCallable]) -> some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            groupLabel(title, icon: icon, color: color)
            ForEach(items) { item in
                calloutRow(name: item.name, description: item.description)
            }
        }
    }

    private func groupLabel(_ title: String, icon: String, color: Color) -> some View {
        HStack(spacing: Autumn.spacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(color)
            Text(title)
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(color)
        }
    }

    private func calloutRow(name: String, description: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.sm) {
            Text(name)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
            Text(description)
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button {
                copyInvocationHint(name)
            } label: {
                Image(systemName: "doc.on.doc")
                    .font(.caption)
            }
            .buttonStyle(.plain)
            .help("复制调用提示")
        }
    }

    private func copyInvocationHint(_ name: String) {
        let text = "请在需要时调用能力域工具 \(name)，并根据当前任务补全参数。"
        #if os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}

// MARK: - Invocation guide

private struct InvocationGuideCard: View {
    let terrs: [TerrSummary]

    private var enabledTerrs: [TerrSummary] {
        terrs.filter(\.enabled)
    }

    private var sampleNames: [String] {
        enabledTerrs
            .flatMap { $0.tools.map(\.name) + $0.skills.map(\.name) }
            .prefix(4)
            .map { $0 }
    }

    var body: some View {
        AutumnCard(emphasis: .subtle, padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                HStack(spacing: Autumn.spacing.sm) {
                    AutumnLogoMark(size: 24)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("能力域调用")
                            .font(Autumn.typography.headline)
                        Text("启用的 Terr 会注入 A2 Agent；在输入中明确目标，A2 会按工具名和参数 schema 自动选择调用。")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if sampleNames.isEmpty {
                    AutumnBadge("当前没有启用的 Tool / Skill", icon: "pause.circle", tone: .neutral)
                } else {
                    InvocationChips(values: sampleNames.map { "调用名 · \($0)" })
                    Text("例：请使用 \(sampleNames[0]) 处理这个输入，并把结果解释给我。")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .padding(Autumn.spacing.sm)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                                .fill(Autumn.colors.surfaceElevated)
                        )
                }
            }
        }
    }
}

private struct InvocationChips: View {
    let values: [String]

    var body: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 120), spacing: Autumn.spacing.xs)],
            alignment: .leading,
            spacing: Autumn.spacing.xs
        ) {
            ForEach(values, id: \.self) { value in
                AutumnBadge(value, tone: .info)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

// MARK: - MCP catalog row

private struct KnownMCPRow: View {
    let mcp: KnownMCP

    var body: some View {
        AutumnCard(emphasis: .subtle, padding: Autumn.spacing.md) {
            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.sm) {
                    Text(mcp.name)
                        .font(Autumn.typography.bodyMedium)
                    AutumnChip(mcp.factory, color: Autumn.colors.muted, size: .compact)
                    credentialChip
                }
                Text(mcp.description)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if mcp.needsCredentials {
                    Text("参数：\(mcp.requiredArgs.joined(separator: ", "))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                }
            }
        }
    }

    @ViewBuilder
    private var credentialChip: some View {
        if mcp.needsCredentials {
            AutumnChip("需凭据", icon: "key.fill",
                       color: Autumn.colors.warning, size: .compact)
        } else {
            AutumnChip("无需凭据", icon: "checkmark.seal.fill",
                       color: Autumn.colors.success, size: .compact)
        }
    }
}
