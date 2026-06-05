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
        .task {
            await vm.load()
        }
        .onChange(of: vm.selectedArea) { _, _ in
            Task { await vm.load() }
        }
    }

    private var toolbar: some View {
        HStack(spacing: 12) {
            Picker("记忆区", selection: $vm.selectedArea) {
                ForEach(MemoryArea.allCases) { area in
                    Text(area.title).tag(area)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 260)

            Text(vm.selectedArea.subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)

            Spacer()

            Button {
                Task { await vm.load() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("刷新")
            .disabled(vm.isLoading)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.errorMessage {
            ContentUnavailableView("无法读取记忆", systemImage: "exclamationmark.triangle", description: Text(error))
        } else if vm.entries.isEmpty {
            ContentUnavailableView("暂无记忆", systemImage: "tray", description: Text(vm.selectedArea.subtitle))
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(vm.entries) { entry in
                        MemoryEntryRow(entry: entry)
                    }
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

private struct MemoryEntryRow: View {
    let entry: MemoryEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(entry.title)
                    .font(.headline)
                Spacer()
                Text(entry.area.title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Text(entry.preview)
                .font(.callout)
                .foregroundStyle(.primary)
                .lineLimit(3)
                .textSelection(.enabled)

            Divider()

            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                ForEach(entry.sortedKeys, id: \.self) { key in
                    GridRow {
                        Text(key)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(entry.values[key]?.formatted ?? "")
                            .font(.caption)
                            .textSelection(.enabled)
                    }
                }
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}
