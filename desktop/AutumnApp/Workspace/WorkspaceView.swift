import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @EnvironmentObject private var store: ConversationStore
    @EnvironmentObject private var projects: ProjectStore

    @SceneStorage("AutumnDesktop.inspectorVisible") private var inspectorVisible: Bool = true
    @Binding var selectedConversationID: UUID?
    @State private var inspectorMode: WorkspaceInspectorMode = .run
    @State private var inspectorTrace: WorkflowTrace?

    var body: some View {
        ChatView(
            settings: settings,
            store: store,
            projects: projects,
            conversationID: selectedConversationID,
            inspectorTrace: $inspectorTrace,
            showRunInspector: showRunInspector
        )
        .id(selectedConversationID)
        .inspector(isPresented: $inspectorVisible) {
            WorkspaceInspectorView(
                mode: $inspectorMode,
                trace: inspectorTrace,
                settings: settings,
                localServer: localServer
            )
            .inspectorColumnWidth(
                min: Autumn.sizing.inspectorWidth,
                ideal: Autumn.sizing.inspectorWidth,
                max: 380
            )
        }
        .navigationTitle(navigationTitleText)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: toggleInspector) {
                    Image(systemName: "sidebar.right")
                        .foregroundStyle(inspectorVisible ? Color.accentColor : Color.secondary)
                }
                .help("切换检视面板 (⌘⇧I)")
            }
        }
        .focusedSceneValue(
            \.workspaceCommandActions,
            WorkspaceCommandActions(
                newConversation: {
                    selectedConversationID = store.newConversation()
                },
                toggleInspector: toggleInspector
            )
        )
    }

    private var navigationTitleText: String {
        let selected = selectedConversationID.flatMap { id in
            store.conversations.first(where: { $0.id == id })
        }
        let title = selected?.title ?? "协作"
        if let projectID = selected?.projectID,
           let project = projects.project(id: projectID) {
            return "\(project.name) › \(title)"
        }
        return title
    }

    private func toggleInspector() {
        withAnimation(Autumn.motion.snappy) {
            inspectorVisible.toggle()
        }
    }

    private func showRunInspector() {
        withAnimation(Autumn.motion.snappy) {
            inspectorMode = .run
            inspectorVisible = true
        }
    }
}
