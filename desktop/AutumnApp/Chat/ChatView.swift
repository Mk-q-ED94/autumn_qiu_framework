import SwiftUI

struct ChatView: View {
    @StateObject private var vm: ChatViewModel
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var conversationStore: ConversationStore
    @EnvironmentObject private var projectStore: ProjectStore
    @FocusState private var composerFocused: Bool
    @State private var inspectorVisible: Bool = false
    @State private var isRunButtonHovered = false

    init(settings: AppSettings, store: ConversationStore, projects: ProjectStore? = nil) {
        _vm = StateObject(wrappedValue: ChatViewModel(
            settings: settings,
            store: store,
            projects: projects
        ))
    }

    /// The trace surfaced in the inspector — the most recent assistant turn
    /// that finished classification (i.e. has a populated trace).
    private var inspectorTrace: WorkflowTrace? {
        vm.messages.reversed().first(where: { $0.role == .assistant && $0.trace != nil })?.trace
    }

    var body: some View {
        VStack(spacing: 0) {
            projectBanner
            messagesList
            errorBanner
            runStatusBar
            composerIntentBar
            inputBar
        }
        .background(Color.clear)
        .inspector(isPresented: $inspectorVisible) {
            MessageInspectorView(trace: inspectorTrace)
                .inspectorColumnWidth(min: 260, ideal: 296, max: 360)
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    withAnimation(Autumn.motion.snappy) { inspectorVisible.toggle() }
                } label: {
                    Image(systemName: inspectorVisible
                          ? "sidebar.trailing"
                          : "sidebar.squares.trailing")
                }
                .help(inspectorVisible ? "隐藏流水线详情" : "显示流水线详情")
            }
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

    @ViewBuilder
    private var projectBanner: some View {
        if let project = activeProject {
            HStack(spacing: Autumn.spacing.sm) {
                Image(systemName: ProjectPalette.icon(for: project.colorTag))
                    .foregroundStyle(ProjectPalette.color(for: project.colorTag))
                VStack(alignment: .leading, spacing: 1) {
                    Text(project.name)
                        .font(Autumn.typography.captionStrong)
                    if !project.trimmedInstructions.isEmpty {
                        Text(project.trimmedInstructions)
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    } else {
                        Text("项目无附加指令")
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
                Spacer()
            }
            .padding(.horizontal, Autumn.spacing.lg)
            .padding(.vertical, Autumn.spacing.sm)
            .background(ProjectPalette.color(for: project.colorTag).opacity(0.08))
            .overlay(
                Rectangle()
                    .fill(ProjectPalette.color(for: project.colorTag).opacity(0.25))
                    .frame(height: 1),
                alignment: .bottom
            )
        }
    }

    private var activeProject: Project? {
        guard
            let id = conversationStore.selectedID,
            let convo = conversationStore.conversations.first(where: { $0.id == id }),
            let projectID = convo.projectID
        else { return nil }
        return projectStore.project(id: projectID)
    }

    private var messagesList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Autumn.spacing.md) {
                    if vm.messages.isEmpty {
                        EmptyStateView(
                            icon: "leaf.fill",
                            title: "协作工作台",
                            message: "A1 分类 · A2 执行 · A3 路由"
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
        if !vm.errors.isEmpty {
            VStack(spacing: Autumn.spacing.xs) {
                ForEach(vm.errors) { error in
                    HStack(spacing: Autumn.spacing.sm) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(Autumn.colors.danger)
                        Text(error.message)
                            .font(Autumn.typography.caption)
                            .foregroundStyle(.primary)
                        Spacer()
                        Button {
                            vm.dismissError(error.id)
                        } label: {
                            Image(systemName: "xmark")
                                .font(.caption2.weight(.bold))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
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
        }
    }

    @ViewBuilder
    private var runStatusBar: some View {
        if vm.isRunning {
            HStack(spacing: Autumn.spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                    .scaleEffect(0.74)
                AutumnBadge("流式运行", icon: "waveform.path", tone: .info)
                if let kind = vm.effectiveInputKind {
                    AutumnBadge(kind.badgeTitle, icon: kind.icon, tone: .accent)
                }
                if let task = vm.effectiveTaskKind {
                    AutumnBadge(task.badgeTitle, tone: .neutral)
                } else if vm.effectiveInputKind == .mission {
                    AutumnBadge(vm.effectiveRoute.title, icon: vm.effectiveRoute.icon, tone: .neutral)
                }
                if vm.shouldShowAgentRunHint {
                    AutumnBadge("Agent 接管", icon: "cpu", tone: .warning)
                }
                Spacer()
                AutumnBadge("Trace 同步", icon: "point.3.connected.trianglepath.dotted", tone: .info)
            }
            .padding(.horizontal, Autumn.spacing.md)
            .padding(.vertical, Autumn.spacing.sm)
            .background(Autumn.colors.info.opacity(0.08))
            .overlay(
                Rectangle()
                    .fill(Autumn.colors.info.opacity(0.18))
                    .frame(height: Autumn.stroke.hairline),
                alignment: .top
            )
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private var composerIntentBar: some View {
        ComposerIntentBar(
            preview: vm.intentPreview,
            inputKind: vm.effectiveInputKind,
            taskKind: vm.effectiveTaskKind,
            routeOverride: vm.routeOverride,
            inputOverride: vm.intentOverride,
            taskOverride: vm.taskOverride,
            effectiveRoute: vm.effectiveRoute,
            isLoading: vm.isPreviewingIntent,
            hasInput: !vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            setInput: vm.setInputOverride,
            setTask: vm.setTaskOverride,
            setRoute: vm.setRouteOverride,
            clearOverrides: vm.clearOverrides
        )
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: Autumn.spacing.sm) {
            TextField("输入消息…", text: $vm.input, axis: .vertical)
                .lineLimit(1...8)
                .textFieldStyle(.plain)
                .font(Autumn.typography.body)
                .padding(.trailing, vm.input.isEmpty ? 0 : 108)
                .padding(.bottom, vm.input.isEmpty ? 0 : 12)
                .autumnInputSurface(isFocused: composerFocused)
                .focused($composerFocused)
                .disabled(vm.isRunning)
                .onSubmit { vm.submitOrStop() }
                .onChange(of: vm.input) { _, _ in vm.inputDidChange() }
                .overlay(alignment: .bottomTrailing) {
                    if !vm.input.isEmpty {
                        tokenCounterLabel
                            .padding(.bottom, 7)
                            .padding(.trailing, 10)
                            .allowsHitTesting(false)
                    }
                }

            runButton
        }
        .padding(.horizontal, Autumn.spacing.md)
        .padding(.vertical, Autumn.spacing.md)
        .background(.bar)
    }

    private var tokenCounterLabel: some View {
        let tokens = ContextLimit.estimateTokens(vm.input)
        let limit = ContextLimit.limit(for: settings.a2Model)
        let ratio = Double(tokens) / Double(limit)
        let color: Color = ratio > 0.8 ? Autumn.colors.danger : (ratio > 0.6 ? Autumn.colors.warning : Autumn.colors.muted)
        return Text("\(ContextLimit.format(tokens)) / \(ContextLimit.format(limit))")
            .font(.system(size: 10, weight: .regular, design: .monospaced))
            .foregroundStyle(color)
    }

    private var runButton: some View {
        Button(action: vm.submitOrStop) {
            Image(systemName: vm.isRunning ? "stop.fill" : "paperplane.fill")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 34)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(vm.isRunning
                              ? AnyShapeStyle(Autumn.colors.danger)
                              : AnyShapeStyle(Autumn.colors.brandGradient))
                )
                .brightness(isRunButtonHovered ? 0.07 : 0)
        }
        .buttonStyle(AutumnPressButtonStyle())
        .onHover { h in withAnimation(Autumn.motion.soft) { isRunButtonHovered = h } }
        .disabled(!vm.isRunning && vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        .help(vm.isRunning ? "停止生成" : "发送")
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
                MessageContentView(text: message.text)
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: Int = 0
    private let dots = 3

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            ForEach(0..<dots, id: \.self) { i in
                Circle()
                    .fill(Color.secondary)
                    .frame(width: 5, height: 5)
                    .opacity(reduceMotion ? 0.6 : (phase == i ? 1 : 0.3))
            }
        }
        .frame(height: 18)
        .task {
            guard !reduceMotion else { return }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 320_000_000)
                phase = (phase + 1) % dots
            }
        }
    }
}
