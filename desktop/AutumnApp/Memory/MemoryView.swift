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
}
