import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings
    @SceneStorage("AutumnDesktop.selectedSection") private var selectedSectionRaw = AppSection.workspace.rawValue

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: $selectedSectionRaw)
        } detail: {
            NavigationStack {
                detailView
            }
        }
        #if os(macOS)
        .frame(minWidth: 980, minHeight: 680)
        #endif
    }

    @ViewBuilder
    private var detailView: some View {
        switch AppSection(rawValue: selectedSectionRaw) ?? .workspace {
        case .workspace:
            WorkspaceView()
        case .memory:
            MemoryView(settings: settings)
        case .settings:
            SettingsView()
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppSettings())
        .environmentObject(LocalServerManager())
}
