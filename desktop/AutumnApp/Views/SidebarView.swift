import SwiftUI

struct SidebarView: View {
    @Binding var selection: String

    var body: some View {
        VStack(spacing: 0) {
            // ── primary navigation ──
            List(selection: $selection) {
                Section {
                    ForEach(AppSection.allCases) { section in
                        SidebarRow(section: section)
                            .tag(section.rawValue)
                    }
                } header: {
                    HStack(spacing: Autumn.spacing.xs) {
                        Image(systemName: "leaf.fill")
                            .foregroundStyle(.tint)
                        Text("秋 · Autumn")
                            .font(Autumn.typography.headline)
                    }
                    .padding(.vertical, 2)
                }
            }
            .listStyle(.sidebar)
            .frame(maxHeight: 220)

            Divider()

            // ── conversation list (visible while in workspace) ──
            if selection == AppSection.workspace.rawValue {
                ConversationListView()
            } else {
                Spacer()
            }
        }
        .navigationTitle("秋")
    }
}

private struct SidebarRow: View {
    let section: AppSection

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 1) {
                Text(section.title)
                    .font(Autumn.typography.bodyMedium)
                Text(section.subtitle)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: section.systemImage)
                .foregroundStyle(.tint)
        }
        .padding(.vertical, 2)
    }
}
