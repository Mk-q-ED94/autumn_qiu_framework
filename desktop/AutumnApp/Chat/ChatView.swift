import SwiftUI

struct ChatView: View {
    @StateObject private var vm: ChatViewModel
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var conversationStore: ConversationStore
    @EnvironmentObject private var projectStore: ProjectStore
    @FocusState private var composerFocused: Bool
    @State private var isRunButtonHovered = false
    @State private var selectedTraceMessageID: UUID?
    private let conversationID: UUID?
    private let showRunInspector: () -> Void
    @Binding private var inspectorTrace: WorkflowTrace?

    init(
        settings: AppSettings,
        store: ConversationStore,
        projects: ProjectStore? = nil,
        conversationID: UUID?,
        inspectorTrace: Binding<WorkflowTrace?>,
        showRunInspector: @escaping () -> Void
    ) {
        self.conversationID = conversationID
        self.showRunInspector = showRunInspector
        _inspectorTrace = inspectorTrace
        _vm = StateObject(wrappedValue: ChatViewModel(
            settings: settings,
            store: store,
            projects: projects,
            conversationID: conversationID
        ))
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
        .focusedSceneValue(
            \.chatCommandActions,
            ChatCommandActions(
                clearConversation: vm.clear,
                endSession: { Task { await vm.endSession() } },
                focusComposer: { composerFocused = true }
            )
        )
        .onChange(of: traceSnapshots, initial: true) { oldSnapshots, newSnapshots in
            DispatchQueue.main.async {
                synchronizeInspectorSelection(from: oldSnapshots, to: newSnapshots)
            }
        }
        .task(id: conversationID) {
            vm.syncActiveRouteOverride()
        }
    }

    @ViewBuilder
    private var projectBanner: some View {
        if let project = activeProject {
            HStack(spacing: Qcowork.spacing.sm) {
                Image(systemName: ProjectPalette.icon(for: project.colorTag))
                    .foregroundStyle(ProjectPalette.color(for: project.colorTag))
                VStack(alignment: .leading, spacing: 1) {
                    Text(project.name)
                        .font(Qcowork.typography.captionStrong)
                    if !project.trimmedInstructions.isEmpty {
                        Text(project.trimmedInstructions)
                            .font(Qcowork.typography.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    } else {
                        Text("项目无附加指令")
                            .font(Qcowork.typography.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
                Spacer()
            }
            .padding(.horizontal, Qcowork.spacing.lg)
            .padding(.vertical, Qcowork.spacing.sm)
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
            let conversationID,
            let convo = conversationStore.conversations.first(where: { $0.id == conversationID }),
            let projectID = convo.projectID
        else { return nil }
        return projectStore.project(id: projectID)
    }

    private var messagesList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Qcowork.spacing.md) {
                    if vm.messages.isEmpty {
                        ChatWelcomeView { prompt in
                            // Setting `input` triggers the composer's onChange,
                            // which runs the intent preview — so picking a starter
                            // shows A1's predicted route before the user sends.
                            vm.input = prompt
                            composerFocused = true
                        }
                        .frame(minHeight: 420)
                    } else {
                        ForEach(vm.messages) { message in
                            MessageRow(
                                message: message,
                                isTraceSelected: selectedTraceMessageID == message.id,
                                onSelectTrace: { selectTrace(message) }
                            )
                                .id(message.id)
                                .transition(.asymmetric(
                                    insertion: .move(edge: .bottom).combined(with: .opacity),
                                    removal: .opacity
                                ))
                        }
                    }
                }
                .padding(Qcowork.spacing.lg)
            }
            .onChange(of: vm.messages.last?.id) { _, newID in
                guard let newID else { return }
                withAnimation(Qcowork.motion.smooth) {
                    proxy.scrollTo(newID, anchor: .bottom)
                }
            }
        }
    }

    private var traceSnapshots: [MessageTraceSnapshot] {
        vm.messages.compactMap { message in
            message.trace.map { trace in
                MessageTraceSnapshot(messageID: message.id, trace: trace)
            }
        }
    }

    private func synchronizeInspectorSelection(
        from oldSnapshots: [MessageTraceSnapshot],
        to newSnapshots: [MessageTraceSnapshot]
    ) {
        let oldIDs = Set(oldSnapshots.map(\.messageID))
        let newestTrace = newSnapshots.last

        if let newestTrace, !oldIDs.contains(newestTrace.messageID) {
            selectedTraceMessageID = newestTrace.messageID
        } else if let selectedTraceMessageID,
                  !newSnapshots.contains(where: { $0.messageID == selectedTraceMessageID }) {
            self.selectedTraceMessageID = newestTrace?.messageID
        } else if selectedTraceMessageID == nil {
            selectedTraceMessageID = newestTrace?.messageID
        }

        inspectorTrace = selectedTraceMessageID.flatMap { selectedID in
            newSnapshots.first(where: { $0.messageID == selectedID })?.trace
        }
    }

    private func selectTrace(_ message: ChatMessage) {
        guard let trace = message.trace else { return }
        selectedTraceMessageID = message.id
        inspectorTrace = trace
        showRunInspector()
    }

    @ViewBuilder
    private var errorBanner: some View {
        if !vm.errors.isEmpty {
            VStack(spacing: Qcowork.spacing.xs) {
                ForEach(vm.errors) { error in
                    HStack(spacing: Qcowork.spacing.sm) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(Qcowork.colors.danger)
                        Text(error.message)
                            .font(Qcowork.typography.caption)
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
                    .padding(.horizontal, Qcowork.spacing.md)
                    .padding(.vertical, Qcowork.spacing.sm)
                    .background(Qcowork.colors.danger.opacity(0.10))
                    .overlay(
                        Rectangle()
                            .fill(Qcowork.colors.danger.opacity(0.4))
                            .frame(height: Qcowork.stroke.hairline),
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
            HStack(spacing: Qcowork.spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                    .scaleEffect(0.74)
                QcoworkBadge("流式运行", icon: "waveform.path", tone: .info)
                if let kind = vm.effectiveInputKind {
                    QcoworkBadge(kind.badgeTitle, icon: kind.icon, tone: .accent)
                }
                if let task = vm.effectiveTaskKind {
                    QcoworkBadge(task.badgeTitle, tone: .neutral)
                } else if vm.effectiveInputKind == .mission {
                    QcoworkBadge(vm.effectiveRoute.title, icon: vm.effectiveRoute.icon, tone: .neutral)
                }
                if vm.shouldShowAgentRunHint {
                    QcoworkBadge("Agent 接管", icon: "cpu", tone: .warning)
                }
                Spacer()
                QcoworkBadge("Trace 同步", icon: "point.3.connected.trianglepath.dotted", tone: .info)
            }
            .padding(.horizontal, Qcowork.spacing.md)
            .padding(.vertical, Qcowork.spacing.sm)
            .background(Qcowork.colors.info.opacity(0.08))
            .overlay(
                Rectangle()
                    .fill(Qcowork.colors.info.opacity(0.18))
                    .frame(height: Qcowork.stroke.hairline),
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
        HStack(alignment: .bottom, spacing: Qcowork.spacing.sm) {
            TextField("输入消息…", text: $vm.input, axis: .vertical)
                .lineLimit(1...8)
                .textFieldStyle(.plain)
                .font(Qcowork.typography.body)
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
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.vertical, Qcowork.spacing.md)
        .background(.bar)
    }

    private var tokenCounterLabel: some View {
        let tokens = ContextLimit.estimateTokens(vm.input)
        let limit = ContextLimit.limit(for: settings.a2Model)
        let ratio = Double(tokens) / Double(limit)
        let color: Color = ratio > 0.8 ? Qcowork.colors.danger : (ratio > 0.6 ? Qcowork.colors.warning : Qcowork.colors.muted)
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
                    RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                        .fill(vm.isRunning
                              ? AnyShapeStyle(Qcowork.colors.danger)
                              : AnyShapeStyle(Qcowork.colors.brandGradient))
                )
                .brightness(isRunButtonHovered ? 0.07 : 0)
        }
        .buttonStyle(QcoworkPressButtonStyle())
        .onHover { h in withAnimation(Qcowork.motion.soft) { isRunButtonHovered = h } }
        .disabled(!vm.isRunning && vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        .help(vm.isRunning ? "停止生成" : "发送")
    }
}

private struct MessageTraceSnapshot: Equatable {
    let messageID: UUID
    let trace: WorkflowTrace
}

private struct MessageRow: View {
    let message: ChatMessage
    let isTraceSelected: Bool
    let onSelectTrace: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Qcowork.spacing.sm) {
            if message.role == .user {
                Spacer(minLength: Qcowork.spacing.xxl)
                bubble
            } else {
                Image(systemName: "leaf.fill")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.tint)
                    .padding(.top, 6)
                bubble
                Spacer(minLength: Qcowork.spacing.xxl)
            }
        }
    }

    private var bubble: some View {
        VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
            if message.text.isEmpty {
                TypingIndicator()
            } else {
                MessageContentView(text: message.text)
            }

            if message.role == .assistant, let trace = message.trace {
                WorkflowTraceView(
                    trace: trace,
                    isSelected: isTraceSelected,
                    onSelect: onSelectTrace
                )
            }
        }
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.vertical, Qcowork.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Qcowork.radius.lg, style: .continuous)
                .fill(message.role == .user
                      ? Qcowork.colors.userBubble
                      : Qcowork.colors.assistantBubble)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Qcowork.radius.lg, style: .continuous)
                .strokeBorder(message.role == .user
                              ? Qcowork.colors.userBubbleStroke
                              : Qcowork.colors.assistantBubbleStroke,
                              lineWidth: Qcowork.stroke.hairline)
        )
        .frame(maxWidth: Qcowork.sizing.bubbleMaxWidth,
               alignment: message.role == .user ? .trailing : .leading)
    }
}

private struct TypingIndicator: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: Int = 0
    private let dots = 3

    var body: some View {
        HStack(spacing: Qcowork.spacing.xs) {
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
