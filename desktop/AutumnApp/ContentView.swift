import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var store: ConversationStore

    @SceneStorage("AutumnDesktop.selectedSection") private var selectedSectionRaw = AppSection.workspace.rawValue
    @AppStorage("AutumnDesktop.onboardingDismissed") private var onboardingDismissed: Bool = false

    var body: some View {
        Group {
            if shouldShowOnboarding {
                OnboardingView(
                    onDismiss: { onboardingDismissed = true },
                    onOpenSettings: {
                        onboardingDismissed = true
                        selectedSectionRaw = AppSection.settings.rawValue
                    }
                )
            } else {
                mainLayout
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnOpenSettings)) { _ in
            selectedSectionRaw = AppSection.settings.rawValue
        }
        #if os(macOS)
        .frame(minWidth: 1020, minHeight: 680)
        #endif
    }

    private var shouldShowOnboarding: Bool {
        !onboardingDismissed && !settings.anyModelConfigured
    }

    private var mainLayout: some View {
        NavigationSplitView {
            SidebarView(selection: $selectedSectionRaw)
                .navigationSplitViewColumnWidth(min: 220, ideal: Autumn.sizing.sidebarWidth)
        } detail: {
            NavigationStack {
                detailView
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(AutumnPageBackground())
            }
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch AppSection(rawValue: selectedSectionRaw) ?? .workspace {
        case .workspace:
            WorkspaceView()
        case .memory:
            MemoryView(settings: settings)
        case .terrs:
            TerrsView(settings: settings)
        case .settings:
            SettingsView()
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppSettings())
        .environmentObject(LocalServerManager())
        .environmentObject(OllamaManager())
        .environmentObject(ConversationStore())
        .environmentObject(ProjectStore())
}
