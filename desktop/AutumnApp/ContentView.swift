import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var store: ConversationStore
    @Environment(\.openSettings) private var openSettings

    @SceneStorage("AutumnDesktop.selectedSection") private var selectedSectionRaw = AppSection.workspace.rawValue
    @SceneStorage("AutumnDesktop.selectedConversation") private var selectedConversationRaw: String?
    @AppStorage("AutumnDesktop.onboardingDismissed") private var onboardingDismissed: Bool = false

    var body: some View {
        Group {
            if shouldShowOnboarding {
                OnboardingView(
                    onDismiss: { onboardingDismissed = true },
                    onOpenSettings: {
                        onboardingDismissed = true
                        openSettings()
                    }
                )
            } else {
                mainLayout
            }
        }
        .onAppear {
            repairConversationSelection()
        }
        .onChange(of: store.conversations.map(\.id)) { _, _ in
            repairConversationSelection()
        }
        #if os(macOS)
        .frame(minWidth: 1020, minHeight: 680)
        #endif
    }

    private var shouldShowOnboarding: Bool {
        !onboardingDismissed && !settings.anyModelConfigured
    }

    private var mainLayout: some View {
        HStack(spacing: 0) {
            SidebarView(
                selection: $selectedSectionRaw,
                selectedConversationID: conversationSelection
            )
            .frame(width: Autumn.sizing.sidebarWidth)

            Rectangle()
                .fill(Color.primary.opacity(0.08))
                .frame(width: Autumn.stroke.hairline)

            detailView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(AutumnPageBackground())
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch AppSection(rawValue: selectedSectionRaw) ?? .workspace {
        case .workspace:
            WorkspaceView(selectedConversationID: conversationSelection)
        case .memory:
            MemoryView(settings: settings)
        case .terrs:
            TerrsView(settings: settings)
        }
    }

    private var conversationSelection: Binding<UUID?> {
        Binding(
            get: { selectedConversationRaw.flatMap(UUID.init(uuidString:)) },
            set: { selectedConversationRaw = $0?.uuidString }
        )
    }

    private func repairConversationSelection() {
        let selectedID = conversationSelection.wrappedValue
        guard selectedID == nil || !store.conversations.contains(where: { $0.id == selectedID }) else {
            return
        }
        conversationSelection.wrappedValue = store.conversations.first?.id
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
