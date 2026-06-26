import SwiftUI

struct WorkspaceView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @EnvironmentObject private var store: ConversationStore
    @EnvironmentObject private var projects: ProjectStore

    @SceneStorage("QcoworkDesktop.inspectorVisible") private var inspectorVisible: Bool = true
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
                        .frame(width: Qcowork.stroke.hairline)
                        .transition(.opacity)

                    WorkspaceInspectorView(
                        mode: $inspectorMode,
                        trace: inspectorTrace,
                        settings: settings,
                        localServer: localServer
                    )
                    .frame(width: Qcowork.sizing.inspectorWidth)
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
        withAnimation(Qcowork.motion.snappy) {
            inspectorVisible.toggle()
        }
    }

    private func showRunInspector() {
        withAnimation(Qcowork.motion.snappy) {
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
        HStack(spacing: Qcowork.spacing.sm) {
            Text(title)
                .font(Qcowork.typography.headline)
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button(action: toggleInspector) {
                Image(systemName: "sidebar.right")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(isInspectorVisible ? Qcowork.colors.clay : .secondary)
            }
            .buttonStyle(.plain)
            .help("切换检视面板 (⌘⇧I)")
        }
        .padding(.horizontal, Qcowork.spacing.lg)
        .padding(.vertical, Qcowork.spacing.sm)
        .background(Color.primary.opacity(0.035))
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Color.primary.opacity(0.08))
                .frame(height: Qcowork.stroke.hairline)
        }
    }
}
