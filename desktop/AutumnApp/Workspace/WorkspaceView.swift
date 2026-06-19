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
        VStack(spacing: 0) {
            WorkspaceTopBar(
                title: navigationTitleText,
                isInspectorVisible: inspectorVisible,
                toggleInspector: toggleInspector
            )

            HStack(spacing: 0) {
                ChatView(
                    settings: settings,
                    store: store,
                    projects: projects,
                    conversationID: selectedConversationID,
                    inspectorTrace: $inspectorTrace,
                    showRunInspector: showRunInspector
                )
                .id(selectedConversationID)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                if inspectorVisible {
                    Rectangle()
                        .fill(Color.primary.opacity(0.08))
                        .frame(width: Autumn.stroke.hairline)
                        .transition(.opacity)

                    WorkspaceInspectorView(
                        mode: $inspectorMode,
                        trace: inspectorTrace,
                        settings: settings,
                        localServer: localServer
                    )
                    .frame(width: Autumn.sizing.inspectorWidth)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()
        }
        .focusedSceneValue(
            \.workspaceCommandActions,
            WorkspaceCommandActions(
                newConversation: { selectedConversationID = store.newConversation() },
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

// MARK: - Top bar

private struct WorkspaceTopBar: View {
    let title: String
    let isInspectorVisible: Bool
    let toggleInspector: () -> Void

    var body: some View {
        HStack(spacing: Autumn.spacing.sm) {
            Text(title)
                .font(Autumn.typography.headline)
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button(action: toggleInspector) {
                Image(systemName: "sidebar.right")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(isInspectorVisible ? Autumn.colors.clay : .secondary)
            }
            .buttonStyle(.plain)
            .help("切换检视面板 (⌘⇧I)")
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(Color.primary.opacity(0.035))
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.primary.opacity(0.08))
                .frame(height: Autumn.stroke.hairline)
        }
    }
}
