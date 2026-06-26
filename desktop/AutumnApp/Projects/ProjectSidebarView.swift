import SwiftUI

/// Sidebar conversation/project explorer.
///
/// Layout:
///   • Header (label + "+" 新建项目 + "+" 新建对话)
///   • DisclosureGroup per project — header shows project chip & instructions hint
///     • New chat button (creates a conversation under this project)
///     • Conversation rows
///   • DisclosureGroup "未分组" — conversations without a project
struct ProjectSidebarView: View {
    @EnvironmentObject private var store: ConversationStore
    @EnvironmentObject private var projects: ProjectStore
    @Binding var selectedConversationID: UUID?

    @State private var renamingConversationID: UUID?
    @State private var draftTitle: String = ""

    @State private var editorMode: ProjectEditorView.Mode?
    @State private var projectPendingDelete: Project?

    @State private var dragTargetedProjectID: UUID?
    @State private var unfiledDropTargeted: Bool = false

    var body: some View {
        VStack(spacing: 0) {
            header
            if store.isLoading {
                skeletons
            } else {
                content
            }
        }
        .sheet(item: Binding(
            get: { editorMode.map(EditorPresentation.init) },
            set: { editorMode = $0?.mode }
        )) { presentation in
            ProjectEditorView(
                mode: presentation.mode,
                onSubmit: { name, instructions, color in
                    handleEditorSubmit(mode: presentation.mode,
                                       name: name,
                                       instructions: instructions,
                                       colorTag: color)
                },
                onCancel: { editorMode = nil }
            )
        }
        .alert(
            "删除项目「\(projectPendingDelete?.name ?? "")」?",
            isPresented: Binding(
                get: { projectPendingDelete != nil },
                set: { if !$0 { projectPendingDelete = nil } }
            ),
            presenting: projectPendingDelete
        ) { project in
            Button("删除项目", role: .destructive) {
                store.unfileConversations(belongingTo: project.id)
                projects.delete(project.id)
            }
            Button("取消", role: .cancel) { }
        } message: { _ in
            Text("项目下的对话不会被删除，将移至未分组。")
        }
    }

    // ── header ───────────────────────────────────────────────────────────────

    private var header: some View {
        HStack(spacing: Qcowork.spacing.sm) {
            Text("项目与对话")
                .font(Qcowork.typography.captionStrong)
                .foregroundStyle(.secondary)
            Spacer()
            Button(action: { editorMode = .create }) {
                Image(systemName: "folder.badge.plus")
                    .font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .help("新建项目")

            Button(action: { selectedConversationID = store.newConversation() }) {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .help("新建对话 (⌘N)")
        }
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.vertical, Qcowork.spacing.sm)
    }

    // ── body content ─────────────────────────────────────────────────────────

    private var content: some View {
        ScrollView {
            VStack(spacing: 0) {
                ForEach(projects.projects) { project in
                    projectSection(project)
                }
                unfiledSection
            }
            .padding(.horizontal, Qcowork.spacing.xs)
            .padding(.vertical, Qcowork.spacing.xs)
        }
    }

    @ViewBuilder
    private func projectSection(_ project: Project) -> some View {
        let isExpanded = Binding<Bool>(
            get: { projects.isExpanded(project.id) },
            set: { setProjectExpanded(project.id, $0) }
        )
        let projectConversations = store.conversations(in: project.id)

        DisclosureGroup(isExpanded: isExpanded) {
            ForEach(projectConversations) { conversation in
                conversationRow(conversation)
            }
            Button {
                selectedConversationID = store.newConversation(projectID: project.id)
            } label: {
                HStack(spacing: Qcowork.spacing.xs) {
                    Image(systemName: "plus.circle")
                    Text("在此项目新建对话")
                        .font(Qcowork.typography.caption)
                }
                .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 2)
        } label: {
            projectHeader(
                project: project,
                count: projectConversations.count,
                isDropTarget: dragTargetedProjectID == project.id
            )
            .contextMenu {
                Button("重命名 / 编辑指令") { editorMode = .edit(project) }
                Button("在此项目新建对话") {
                    selectedConversationID = store.newConversation(projectID: project.id)
                }
                Divider()
                Button("删除项目", role: .destructive) {
                    projectPendingDelete = project
                }
            }
            .dropDestination(for: String.self) { items, _ in
                guard let first = items.first, let id = UUID(uuidString: first) else { return false }
                store.moveConversation(id, toProject: project.id)
                projects.setExpanded(project.id, true)
                return true
            } isTargeted: { targeted in
                dragTargetedProjectID = targeted ? project.id : nil
            }
        }
    }

    private func projectHeader(project: Project, count: Int, isDropTarget: Bool = false) -> some View {
        HStack(spacing: Qcowork.spacing.sm) {
            Image(systemName: ProjectPalette.icon(for: project.colorTag))
                .foregroundStyle(isDropTarget ? Color.accentColor : ProjectPalette.color(for: project.colorTag))
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(project.name)
                    .font(Qcowork.typography.bodyMedium)
                    .lineLimit(1)
                if !project.trimmedInstructions.isEmpty {
                    Text(project.trimmedInstructions)
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
            Text("\(count)")
                .font(Qcowork.typography.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    private var unfiledSection: some View {
        let unfiled = store.unfiledConversations
        let isExpanded = Binding<Bool>(
            get: { projects.unfiledExpanded },
            set: { setUnfiledExpanded($0) }
        )
        return DisclosureGroup(isExpanded: isExpanded) {
            if unfiled.isEmpty {
                Text("空")
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(.tertiary)
                    .padding(.vertical, 2)
            } else {
                ForEach(unfiled) { conversation in
                    conversationRow(conversation)
                }
            }
        } label: {
            HStack(spacing: Qcowork.spacing.sm) {
                Image(systemName: "tray")
                    .foregroundStyle(unfiledDropTargeted ? Color.accentColor : Color.secondary)
                    .frame(width: 18)
                Text("未分组")
                    .font(Qcowork.typography.bodyMedium)
                Spacer()
                Text("\(unfiled.count)")
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 2)
            .dropDestination(for: String.self) { items, _ in
                guard let first = items.first, let id = UUID(uuidString: first) else { return false }
                store.moveConversation(id, toProject: nil)
                return true
            } isTargeted: { targeted in
                unfiledDropTargeted = targeted
            }
        }
    }

    // ── conversation row ─────────────────────────────────────────────────────

    @ViewBuilder
    private func conversationRow(_ conversation: Conversation) -> some View {
        let isSelected = selectedConversationID == conversation.id
        let isEditing = renamingConversationID == conversation.id
        ConversationRowContent(
            conversation: conversation,
            isEditing: isEditing,
            isSelected: isSelected,
            draftTitle: $draftTitle,
            onCommitRename: {
                store.rename(conversation.id, to: draftTitle)
                renamingConversationID = nil
            },
            onCancelRename: { renamingConversationID = nil },
            onStartFirstMessage: { selectedConversationID = conversation.id }
        )
        .contentShape(Rectangle())
        .onTapGesture { selectedConversationID = conversation.id }
        .draggable(conversation.id.uuidString)
        .contextMenu {
            Button("重命名") {
                draftTitle = conversation.title
                renamingConversationID = conversation.id
            }
            Menu("移动到项目") {
                ForEach(projects.projects) { project in
                    Button(project.name) {
                        store.moveConversation(conversation.id, toProject: project.id)
                        projects.setExpanded(project.id, true)
                    }
                    .disabled(conversation.projectID == project.id)
                }
                if !projects.projects.isEmpty {
                    Divider()
                }
                Button("移出项目") {
                    store.moveConversation(conversation.id, toProject: nil)
                }
                .disabled(conversation.projectID == nil)
            }
            Divider()
            Button("删除", role: .destructive) {
                store.delete(conversation.id)
                if selectedConversationID == conversation.id {
                    selectedConversationID = store.conversations.first?.id
                }
            }
        }
    }

    private var skeletons: some View {
        VStack(spacing: Qcowork.spacing.sm) {
            ForEach(0..<5, id: \.self) { _ in
                SidebarSkeletonRow()
            }
        }
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.top, Qcowork.spacing.sm)
    }

    private func handleEditorSubmit(
        mode: ProjectEditorView.Mode,
        name: String,
        instructions: String,
        colorTag: String
    ) {
        switch mode {
        case .create:
            projects.create(name: name, instructions: instructions, colorTag: colorTag)
        case .edit(let project):
            var updated = project
            updated.name = name
            updated.instructions = instructions
            updated.colorTag = colorTag
            projects.update(updated)
        }
        editorMode = nil
    }

    private func setProjectExpanded(_ id: UUID, _ value: Bool) {
        DispatchQueue.main.async {
            projects.setExpanded(id, value)
        }
    }

    private func setUnfiledExpanded(_ value: Bool) {
        DispatchQueue.main.async {
            projects.unfiledExpanded = value
        }
    }
}
/// Sheet presentation wrapper so ``editorMode`` can be Identifiable.
private struct EditorPresentation: Identifiable {
    let mode: ProjectEditorView.Mode

    var id: String {
        switch mode {
        case .create: return "create"
        case .edit(let project): return "edit-\(project.id.uuidString)"
        }
    }
}

private struct ConversationRowContent: View {
    let conversation: Conversation
    let isEditing: Bool
    let isSelected: Bool
    @Binding var draftTitle: String
    let onCommitRename: () -> Void
    let onCancelRename: () -> Void
    let onStartFirstMessage: () -> Void
    @FocusState private var focused: Bool
    @State private var isHovered = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if isEditing {
                TextField("标题", text: $draftTitle, onCommit: onCommitRename)
                    .textFieldStyle(.plain)
                    .font(Qcowork.typography.callout)
                    .autumnInputSurface(isFocused: focused)
                    .focused($focused)
                    .onAppear { focused = true }
                    .onSubmit(onCommitRename)
                    .onExitCommand(perform: onCancelRename)
            } else {
                Text(conversation.title)
                    .font(Qcowork.typography.callout)
                    .lineLimit(1)
            }

            Text(subtitle)
                .font(Qcowork.typography.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            if conversation.messages.isEmpty && !isEditing {
                Button("发送第一条消息", action: onStartFirstMessage)
                    .buttonStyle(.plain)
                    .font(Qcowork.typography.captionStrong)
                    .foregroundStyle(.tint)
            }
        }
        .padding(.horizontal, Qcowork.spacing.sm)
        .padding(.vertical, Qcowork.spacing.xs)
        .frame(maxWidth: .infinity, minHeight: Qcowork.sizing.sidebarRowMinHeight, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                .fill(rowFill)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                .stroke(isSelected ? Qcowork.colors.clay.opacity(0.18) : .clear,
                        lineWidth: Qcowork.stroke.hairline)
        )
        .onHover { isHovered = $0 }
        .animation(Qcowork.motion.soft, value: isHovered)
        .animation(Qcowork.motion.soft, value: isSelected)
    }

    private var rowFill: Color {
        if isSelected { return Qcowork.colors.clay.opacity(0.12) }
        if isHovered { return Qcowork.colors.surfaceHover }
        return .clear
    }

    private var subtitle: String {
        let messageCount = conversation.messages.count
        if messageCount == 0 { return "空对话" }
        if abs(conversation.updatedAt.timeIntervalSinceNow) < 60 {
            return "\(messageCount) 条 · 刚刚"
        }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        let when = formatter.localizedString(for: conversation.updatedAt, relativeTo: Date())
        return "\(messageCount) 条 · \(when)"
    }
}

private struct SidebarSkeletonRow: View {
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .leading, spacing: Qcowork.spacing.xs) {
            Capsule()
                .fill(Color.secondary.opacity(pulse ? 0.18 : 0.08))
                .frame(width: 120, height: 10)
            Capsule()
                .fill(Color.secondary.opacity(pulse ? 0.12 : 0.06))
                .frame(width: 72, height: 8)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, Qcowork.spacing.sm)
        .onAppear {
            withAnimation(Qcowork.motion.pulse) { pulse = true }
        }
    }
}
