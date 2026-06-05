import SwiftUI

struct SidebarView: View {
    @Binding var selection: String

    var body: some View {
        List(selection: $selection) {
            Section("Autumn") {
                ForEach(AppSection.allCases) { section in
                    SidebarRow(section: section)
                        .tag(section.rawValue)
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("秋")
    }
}

private struct SidebarRow: View {
    let section: AppSection

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 1) {
                Text(section.title)
                Text(section.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: section.systemImage)
        }
    }
}
