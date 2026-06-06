import SwiftUI

struct ChatView: View {
    @StateObject private var vm: ChatViewModel
    @FocusState private var composerFocused: Bool
    @State private var intentPopoverVisible: Bool = false

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

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: Autumn.spacing.sm) {
            ZStack(alignment: .topTrailing) {
                TextField("输入消息…  ⌘L 聚焦此处", text: $vm.input, axis: .vertical)
                    .lineLimit(1...8)
                    .textFieldStyle(.plain)
                    .font(Autumn.typography.body)
                    .padding(.trailing, 132)
                    .autumnInputSurface(isFocused: composerFocused)
                    .focused($composerFocused)
                    .disabled(vm.isRunning)
                    .onSubmit { vm.submitOrStop() }
                    .onChange(of: vm.input) { _, _ in vm.inputDidChange() }

                IntentBadgeButton(
                    preview: vm.intentPreview,
                    inputKind: vm.effectiveInputKind,
                    taskKind: vm.effectiveTaskKind,
                    isLoading: vm.isPreviewingIntent,
                    isPresented: $intentPopoverVisible,
                    setInput: vm.setInputOverride,
                    setTask: vm.setTaskOverride,
                    routeOverride: vm.routeOverride,
                    setRoute: vm.setRouteOverride
                )
                .padding(.top, 7)
                .padding(.trailing, 8)
                .disabled(vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            runButton
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

    private var runButton: some View {
        Button(action: vm.submitOrStop) {
            Image(systemName: vm.isRunning ? "stop.fill" : "paperplane.fill")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 34)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(vm.isRunning ? Autumn.colors.danger : Color.accentColor)
                )
        }
        .buttonStyle(.plain)
        .disabled(!vm.isRunning && vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        .help(vm.isRunning ? "停止生成" : "发送")
    }
}

private struct IntentBadgeButton: View {
    let preview: IntentPreview?
    let inputKind: WorkflowInputKind?
    let taskKind: WorkflowTaskKind?
    let isLoading: Bool
    @Binding var isPresented: Bool
    let setInput: (WorkflowInputKind) -> Void
    let setTask: (WorkflowTaskKind) -> Void
    let routeOverride: MissionRouteMode?
    let setRoute: (MissionRouteMode?) -> Void

    var body: some View {
        Button {
            isPresented.toggle()
        } label: {
            HStack(spacing: Autumn.spacing.xs) {
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                        .scaleEffect(0.7)
                }
                AutumnBadge(title, icon: icon, tone: tone)
            }
        }
        .buttonStyle(.plain)
        .popover(isPresented: $isPresented, arrowEdge: .top) {
            IntentOverridePopover(
                selectedInput: inputKind ?? .mission,
                selectedTask: taskKind ?? .general,
                routeOverride: routeOverride,
                setInput: setInput,
                setTask: setTask,
                setRoute: setRoute
            )
        }
        .help("查看或覆盖本次输入意图")
    }

    private var title: String {
        if let preview {
            return preview.badgeTitle
        }
        if let inputKind, inputKind == .task {
            return taskKind?.badgeTitle ?? WorkflowTaskKind.general.badgeTitle
        }
        return inputKind?.badgeTitle ?? "意图"
    }

    private var icon: String {
        (inputKind ?? preview?.inputKind ?? .mission).icon
    }

    private var tone: AutumnBadge.Tone {
        guard let preview else { return .neutral }
        return preview.confidence < 0.7 ? .warning : .accent
    }
}

private struct IntentOverridePopover: View {
    let selectedInput: WorkflowInputKind
    let selectedTask: WorkflowTaskKind
    let routeOverride: MissionRouteMode?
    let setInput: (WorkflowInputKind) -> Void
    let setTask: (WorkflowTaskKind) -> Void
    let setRoute: (MissionRouteMode?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.md) {
            Text("本次意图")
                .font(Autumn.typography.headline)

            Picker("输入", selection: inputBinding) {
                ForEach(WorkflowInputKind.allCases) { kind in
                    Text(kind.title).tag(kind)
                }
            }
            .pickerStyle(.segmented)

            if selectedInput == .task {
                Picker("任务类型", selection: taskBinding) {
                    ForEach(WorkflowTaskKind.allCases) { kind in
                        Text(kind.title).tag(kind)
                    }
                }
            } else {
                Picker("Mission 路由", selection: routeBinding) {
                    Text("跟随默认").tag("__default__")
                    ForEach(MissionRouteMode.allCases) { route in
                        Text(route.title).tag(route.rawValue)
                    }
                }
            }
        }
        .padding(Autumn.spacing.lg)
        .frame(width: 260)
    }

    private var inputBinding: Binding<WorkflowInputKind> {
        Binding(get: { selectedInput }, set: setInput)
    }

    private var taskBinding: Binding<WorkflowTaskKind> {
        Binding(get: { selectedTask }, set: setTask)
    }

    private var routeBinding: Binding<String> {
        Binding(
            get: { routeOverride?.rawValue ?? "__default__" },
            set: { value in
                setRoute(value == "__default__" ? nil : MissionRouteMode(rawValue: value))
            }
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
