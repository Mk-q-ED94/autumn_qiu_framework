import SwiftUI

/// Sidebar conversation list with rename/delete and new-chat affordance.
struct ConversationListView: View {
    @EnvironmentObject private var store: ConversationStore
    @State private var editingID: UUID?
    @State private var draftTitle: String = ""

    var body: some View {
        VStack(spacing: 0) {
            header

            if store.isLoading {
                VStack(spacing: Autumn.spacing.sm) {
                    ForEach(0..<5, id: \.self) { _ in
                        SkeletonRow()
                    }
                }
                .padding(.horizontal, Autumn.spacing.md)
                .padding(.top, Autumn.spacing.sm)
            } else {
                List(selection: bindingSelection) {
                    ForEach(store.conversations) { conversation in
                        ConversationRow(
                            conversation: conversation,
                            isEditing: editingID == conversation.id,
                            draftTitle: $draftTitle,
                            onCommitRename: {
                                store.rename(conversation.id, to: draftTitle)
                                editingID = nil
                            },
                            onCancelRename: { editingID = nil },
                            onStartFirstMessage: { store.select(conversation.id) }
                        )
                        .tag(conversation.id)
                        .contextMenu {
                            Button("重命名") {
                                draftTitle = conversation.title
                                editingID = conversation.id
                            }
                            Button("删除", role: .destructive) {
                                store.delete(conversation.id)
                            }
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        }
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            Text("对话")
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(.secondary)
            Spacer()
            Button(action: { store.newConversation() }) {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .help("新建对话 (⌘N)")
        }
        .padding(.horizontal, Autumn.spacing.md)
        .padding(.vertical, Autumn.spacing.sm)
    }

    private var bindingSelection: Binding<UUID?> {
        Binding(
            get: { store.selectedID },
            set: { if let id = $0 { store.select(id) } }
        )
    }
}

private struct ConversationRow: View {
    let conversation: Conversation
    let isEditing: Bool
    @Binding var draftTitle: String
    let onCommitRename: () -> Void
    let onCancelRename: () -> Void
    let onStartFirstMessage: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if isEditing {
                TextField("标题", text: $draftTitle, onCommit: onCommitRename)
                    .textFieldStyle(.plain)
                    .font(Autumn.typography.callout)
                    .autumnInputSurface(isFocused: focused)
                    .focused($focused)
                    .onAppear { focused = true }
                    .onSubmit(onCommitRename)
                    .onExitCommand(perform: onCancelRename)
            } else {
                Text(conversation.title)
                    .font(Autumn.typography.callout)
                    .lineLimit(1)
            }

            Text(subtitle)
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            if conversation.messages.isEmpty && !isEditing {
                Button("发送第一条消息", action: onStartFirstMessage)
                    .buttonStyle(.plain)
                    .font(Autumn.typography.captionStrong)
                    .foregroundStyle(.tint)
            }
        }
        .padding(.vertical, 3)
    }

    private var subtitle: String {
        let messageCount = conversation.messages.count
        if messageCount == 0 { return "空对话" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        let when = formatter.localizedString(for: conversation.updatedAt, relativeTo: Date())
        return "\(messageCount) 条 · \(when)"
    }
}

private struct SkeletonRow: View {
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            Capsule()
                .fill(Color.secondary.opacity(pulse ? 0.18 : 0.08))
                .frame(width: 120, height: 10)
            Capsule()
                .fill(Color.secondary.opacity(pulse ? 0.12 : 0.06))
                .frame(width: 72, height: 8)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, Autumn.spacing.sm)
        .onAppear {
            withAnimation(Autumn.motion.pulse) { pulse = true }
        }
    }
}
