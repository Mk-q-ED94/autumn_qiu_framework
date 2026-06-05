import SwiftUI

struct ChatView: View {
    @StateObject private var vm: ChatViewModel
    @FocusState private var composerFocused: Bool

    init(settings: AppSettings, store: ConversationStore) {
        _vm = StateObject(wrappedValue: ChatViewModel(settings: settings, store: store))
    }

    var body: some View {
        VStack(spacing: 0) {
            messagesList
            errorBanner
            inputBar
        }
        .background(Color.clear)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button("清空对话", role: .destructive) { vm.clear() }
                    Button("结束会话") { Task { await vm.endSession() } }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnClearConversation)) { _ in
            vm.clear()
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnEndSession)) { _ in
            Task { await vm.endSession() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .autumnFocusComposer)) { _ in
            composerFocused = true
        }
    }

    private var messagesList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Autumn.spacing.md) {
                    if vm.messages.isEmpty {
                        EmptyStateView(
                            icon: "leaf.fill",
                            title: "开始一次协作",
                            message: "输入任务或问题，Autumn 会路由给合适的工作区并把过程展示在这里。"
                        )
                        .frame(minHeight: 360)
                    } else {
                        ForEach(vm.messages) { message in
                            MessageRow(message: message)
                                .id(message.id)
                                .transition(.asymmetric(
                                    insertion: .move(edge: .bottom).combined(with: .opacity),
                                    removal: .opacity
                                ))
                        }
                    }
                }
                .padding(Autumn.spacing.lg)
            }
            .onChange(of: vm.messages.last?.id) { _, newID in
                guard let newID else { return }
                withAnimation(Autumn.motion.smooth) {
                    proxy.scrollTo(newID, anchor: .bottom)
                }
            }
        }
    }

    @ViewBuilder
    private var errorBanner: some View {
        if let error = vm.errorMessage {
            HStack(spacing: Autumn.spacing.sm) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Autumn.colors.danger)
                Text(error)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.primary)
                Spacer()
            }
            .padding(.horizontal, Autumn.spacing.md)
            .padding(.vertical, Autumn.spacing.sm)
            .background(Autumn.colors.danger.opacity(0.10))
            .overlay(
                Rectangle()
                    .fill(Autumn.colors.danger.opacity(0.4))
                    .frame(height: Autumn.stroke.hairline),
                alignment: .top
            )
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: Autumn.spacing.sm) {
            TextField("输入消息…  ⌘L 聚焦此处", text: $vm.input, axis: .vertical)
                .lineLimit(1...8)
                .textFieldStyle(.plain)
                .font(Autumn.typography.body)
                .padding(.horizontal, Autumn.spacing.md)
                .padding(.vertical, Autumn.spacing.sm)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                        .fill(Autumn.colors.surfaceElevated)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                        .strokeBorder(composerFocused ? Color.accentColor.opacity(0.6) : Color.clear,
                                      lineWidth: Autumn.stroke.medium)
                )
                .focused($composerFocused)
                .disabled(vm.isRunning)
                .onSubmit { Task { await vm.send() } }

            AutumnPrimaryButton(
                isLoading: vm.isRunning,
                action: { Task { await vm.send() } }
            ) {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 14, weight: .bold))
            }
            .disabled(vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.isRunning)
        }
        .padding(Autumn.spacing.md)
        .background(.bar)
        .overlay(
            Rectangle()
                .fill(Color.secondary.opacity(0.15))
                .frame(height: Autumn.stroke.hairline),
            alignment: .top
        )
    }
}

private struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            if message.role == .user {
                Spacer(minLength: Autumn.spacing.xxl)
                bubble
            } else {
                Image(systemName: "leaf.fill")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.tint)
                    .padding(.top, 6)
                bubble
                Spacer(minLength: Autumn.spacing.xxl)
            }
        }
    }

    private var bubble: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            if message.text.isEmpty {
                TypingIndicator()
            } else {
                Text(message.text)
                    .font(Autumn.typography.body)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if message.role == .assistant, let trace = message.trace {
                WorkflowTraceView(trace: trace)
            }
        }
        .padding(.horizontal, Autumn.spacing.md)
        .padding(.vertical, Autumn.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.lg, style: .continuous)
                .fill(message.role == .user
                      ? Autumn.colors.userBubble
                      : Autumn.colors.assistantBubble)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Autumn.radius.lg, style: .continuous)
                .strokeBorder(message.role == .user
                              ? Autumn.colors.userBubbleStroke
                              : Autumn.colors.assistantBubbleStroke,
                              lineWidth: Autumn.stroke.hairline)
        )
        .frame(maxWidth: Autumn.sizing.bubbleMaxWidth,
               alignment: message.role == .user ? .trailing : .leading)
    }
}

private struct TypingIndicator: View {
    @State private var phase: Int = 0
    private let dots = 3

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            ForEach(0..<dots, id: \.self) { i in
                Circle()
                    .fill(Color.secondary)
                    .frame(width: 5, height: 5)
                    .opacity(phase == i ? 1 : 0.3)
            }
        }
        .frame(height: 18)
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 320_000_000)
                phase = (phase + 1) % dots
            }
        }
    }
}
