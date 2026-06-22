import Foundation
import SwiftUI

struct ChatError: Identifiable, Equatable {
    let id = UUID()
    let message: String
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input: String = ""
    @Published var isRunning: Bool = false
    @Published var errors: [ChatError] = []
    @Published var intentPreview: IntentPreview? = nil
    @Published var intentOverride: WorkflowInputKind? = nil
    @Published var taskOverride: WorkflowTaskKind? = nil
    @Published var routeOverride: MissionRouteMode? = nil
    @Published var isPreviewingIntent: Bool = false

    private let settings: AppSettings
    private let store: ConversationStore
    private let projects: ProjectStore?
    private let conversationID: UUID?
    private var intentTask: Task<Void, Never>?
    private var runTask: Task<Void, Never>?

    init(
        settings: AppSettings,
        store: ConversationStore,
        projects: ProjectStore? = nil,
        conversationID: UUID?
    ) {
        self.settings = settings
        self.store = store
        self.projects = projects
        self.conversationID = conversationID
        loadFromStore()
    }

    /// The currently-active project for the loaded conversation, if any.
    private var activeProject: Project? {
        guard
            let conversationID,
            let conversation = store.conversations.first(where: { $0.id == conversationID }),
            let projectID = conversation.projectID
        else { return nil }
        return projects?.project(id: projectID)
    }

    /// Project instructions to attach to the next outbound request, trimmed.
    private var activeProjectInstructions: String? {
        let trimmed = activeProject?.trimmedInstructions
        return (trimmed?.isEmpty ?? true) ? nil : trimmed
    }

    private var activeProjectIDString: String? {
        activeProject?.id.uuidString
    }

    private func loadFromStore() {
        if let conversationID,
           let conv = store.conversations.first(where: { $0.id == conversationID }) {
            messages = conv.messages.map { $0.toChatMessage() }
        } else {
            messages = []
        }
        errors.removeAll()
        input = ""
        intentPreview = nil
        intentOverride = nil
        taskOverride = nil
        routeOverride = nil
        settings.activeRouteOverride = nil
    }

    private var client: QcoworkClient? {
        guard let url = URL(string: settings.serverURL) else { return nil }
        return QcoworkClient(baseURL: url)
    }

    var effectiveRoute: MissionRouteMode {
        routeOverride ?? MissionRouteMode(rawValue: settings.routeMode) ?? .auto
    }

    var effectiveInputKind: WorkflowInputKind? {
        intentOverride ?? intentPreview?.inputKind
    }

    var effectiveTaskKind: WorkflowTaskKind? {
        guard effectiveInputKind == .task else { return nil }
        return taskOverride ?? intentPreview?.taskKind ?? .general
    }

    var shouldShowAgentRunHint: Bool {
        if effectiveInputKind == .task {
            return true
        }
        guard effectiveInputKind == .mission else {
            return false
        }
        if effectiveRoute == .convert {
            return true
        }
        return intentPreview?.routeMode == .convert
    }

    func inputDidChange() {
        scheduleIntentPreview()
    }

    func setInputOverride(_ kind: WorkflowInputKind) {
        intentOverride = kind
        if kind == .mission {
            taskOverride = nil
        } else if taskOverride == nil {
            taskOverride = intentPreview?.taskKind ?? .general
        }
        scheduleIntentPreview(delay: 0)
    }

    func setTaskOverride(_ kind: WorkflowTaskKind) {
        intentOverride = .task
        taskOverride = kind
        scheduleIntentPreview(delay: 0)
    }

    func setRouteOverride(_ route: MissionRouteMode?) {
        routeOverride = route
        settings.activeRouteOverride = route?.rawValue
        scheduleIntentPreview(delay: 0)
    }

    func clearOverrides() {
        intentOverride = nil
        taskOverride = nil
        routeOverride = nil
        settings.activeRouteOverride = nil
        scheduleIntentPreview(delay: 0)
    }

    func submitOrStop() {
        if isRunning {
            stop()
            return
        }
        runTask = Task { await send() }
    }

    func stop() {
        runTask?.cancel()
        runTask = nil
        isRunning = false
        pushError("已停止，保留当前已生成内容。")
        persistMessages()
    }

    func send() async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isRunning else { return }
        guard let client = client else {
            pushError("服务器 URL 无效")
            return
        }

        input = ""
        intentTask?.cancel()
        errors.removeAll()

        withAnimation(Qcowork.motion.snappy) {
            messages.append(ChatMessage(role: .user, text: text))
            messages.append(ChatMessage(
                role: .assistant,
                text: "",
                trace: provisionalTrace(for: text, status: "active")
            ))
        }
        persistMessages()

        let assistantIndex = messages.count - 1
        isRunning = true
        defer {
            isRunning = false
            runTask = nil
            persistMessages()
        }

        do {
            let projectInstructions = activeProjectInstructions
            let projectID = activeProjectIDString
            var streamed = ""
            var finalTrace: WorkflowTrace?
            for try await event in client.stream(
                text,
                route: effectiveRoute.rawValue,
                inputType: intentOverride?.rawValue,
                taskType: effectiveTaskKind?.rawValue,
                projectInstructions: projectInstructions,
                projectID: projectID
            ) {
                try Task.checkCancellation()
                guard messages.indices.contains(assistantIndex) else { return }
                switch event {
                case .chunk(let chunk):
                    streamed += chunk
                    messages[assistantIndex].text = streamed
                case .trace(let trace):
                    finalTrace = trace
                    messages[assistantIndex].trace = trace
                }
            }
            if Task.isCancelled { return }
            guard messages.indices.contains(assistantIndex) else { return }

            // Prefer the validated trace output, but never clobber what we already
            // streamed when the trace arrives empty (e.g. failure mid-pipeline).
            let resolved: String
            if let trace = finalTrace, !trace.output.isEmpty {
                resolved = trace.output
            } else if !streamed.isEmpty {
                resolved = streamed
            } else {
                resolved = "(empty response)"
            }
            withAnimation(Qcowork.motion.smooth) {
                messages[assistantIndex].text = resolved
                if let trace = finalTrace {
                    messages[assistantIndex].trace = trace
                }
            }
            if let trace = finalTrace {
                intentPreview = IntentPreview(
                    inputType: trace.inputType,
                    taskType: trace.taskType,
                    route: trace.route,
                    confidence: 1.0,
                    reasoning: nil
                )
            }
        } catch is CancellationError {
            if messages.indices.contains(assistantIndex), messages[assistantIndex].text.isEmpty {
                messages[assistantIndex].text = "已停止"
            }
        } catch {
            pushError(error.localizedDescription)
            if messages.indices.contains(assistantIndex) {
                messages[assistantIndex].text +=
                    (messages[assistantIndex].text.isEmpty ? "" : "\n\n") +
                    "[错误] \(error.localizedDescription)"
                messages[assistantIndex].trace = failedTrace(for: text, message: error.localizedDescription)
            }
        }
    }

    func clear() {
        // Cancel any in-flight stream before mutating the message buffer so the
        // background task doesn't try to write into an emptied array.
        runTask?.cancel()
        runTask = nil
        isRunning = false
        withAnimation(Qcowork.motion.smooth) {
            messages.removeAll()
            errors.removeAll()
        }
        if let id = conversationID {
            store.clearMessages(id)
        }
    }

    func endSession() async {
        guard let client = client else { return }
        do {
            try await client.endSession()
            clear()
        } catch {
            pushError(error.localizedDescription)
        }
    }

    // ── private ───────────────────────────────────────────────────────────────

    private func scheduleIntentPreview(delay: UInt64 = 450_000_000) {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        intentTask?.cancel()
        guard text.count >= 2, let client else {
            intentPreview = nil
            return
        }

        intentTask = Task { [weak self] in
            if delay > 0 {
                try? await Task.sleep(nanoseconds: delay)
            }
            if Task.isCancelled { return }
            await self?.refreshIntentPreview(text: text, client: client)
        }
    }

    private func refreshIntentPreview(text: String, client: QcoworkClient) async {
        isPreviewingIntent = true
        defer { isPreviewingIntent = false }
        do {
            intentPreview = try await client.previewIntent(
                text,
                route: effectiveRoute.rawValue,
                inputType: intentOverride?.rawValue,
                taskType: effectiveTaskKind?.rawValue,
                projectInstructions: activeProjectInstructions,
                projectID: activeProjectIDString
            )
        } catch {
            // Intent preview is advisory; keep typing smooth and surface the state through the badge.
            intentPreview = IntentPreview(
                inputType: intentOverride?.rawValue ?? "mission",
                taskType: taskOverride?.rawValue,
                route: routeOverride?.rawValue,
                confidence: 0.0,
                reasoning: nil
            )
        }
    }

    private func provisionalTrace(for input: String, status: String) -> WorkflowTrace {
        let preview = intentPreview ?? IntentPreview(
            inputType: intentOverride?.rawValue ?? "mission",
            taskType: taskOverride?.rawValue,
            route: routeOverride?.rawValue,
            confidence: 1.0,
            reasoning: nil
        )
        var stages = [
            WorkflowStage(
                id: "wp1.select",
                title: "A1 分类",
                detail: preview.badgeTitle,
                workspace: "WP1",
                status: "completed"
            )
        ]
        if preview.inputKind == .task {
            stages.append(WorkflowStage(
                id: "wp2.agent",
                title: "WP2 Agent",
                detail: "Agent 待命，等待可用工具或技能接入",
                workspace: "WP2",
                status: status,
                kind: "agent"
            ))
            stages.append(WorkflowStage(
                id: "wp2.task",
                title: "A2 执行任务",
                detail: "流式响应进行中",
                workspace: "WP2",
                status: status
            ))
        } else {
            let route = effectiveRoute
            stages.append(WorkflowStage(
                id: "wp3.route",
                title: "A3 路由",
                detail: route == .auto ? "等待 A3 判断路由" : "Mission 路由为 \(route.rawValue)",
                workspace: "WP3",
                status: route == .auto ? "active" : "completed"
            ))
            stages.append(WorkflowStage(
                id: route == .convert ? "wp3.convert" : "wp3.direct",
                title: route == .convert ? "A3 转换任务" : "A3 直接回答",
                detail: "流式响应进行中",
                workspace: "WP3",
                status: status
            ))
            if route == .convert {
                stages.append(WorkflowStage(
                    id: "wp2.agent",
                    title: "WP2 Agent",
                    detail: "Agent 待命，等待转换后的任务",
                    workspace: "WP2",
                    status: "pending",
                    kind: "agent"
                ))
                stages.append(WorkflowStage(
                    id: "wp2.task",
                    title: "A2 执行任务",
                    detail: "等待转换后的任务",
                    workspace: "WP2",
                    status: "pending"
                ))
            }
        }
        stages.append(WorkflowStage(
            id: "wp1.final_check",
            title: "A1 最终检查",
            detail: "等待输出完成",
            workspace: "WP1",
            status: "pending"
        ))

        return WorkflowTrace(
            output: "",
            inputType: preview.inputType,
            route: effectiveRoute == .auto ? preview.route : effectiveRoute.rawValue,
            taskType: preview.taskType,
            stages: stages
        )
    }

    private func failedTrace(for input: String, message: String) -> WorkflowTrace {
        let trace = provisionalTrace(for: input, status: "failed")
        let stages = trace.stages + [WorkflowStage(
            id: "error",
            title: "运行失败",
            detail: message,
            workspace: "系统",
            status: "failed"
        )]
        return WorkflowTrace(
            output: trace.output,
            inputType: trace.inputType,
            route: trace.route,
            taskType: trace.taskType,
            stages: stages
        )
    }

    private func pushError(_ message: String) {
        let error = ChatError(message: message)
        withAnimation(Qcowork.motion.smooth) {
            errors.append(error)
        }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            await MainActor.run {
                self?.dismissError(error.id)
            }
        }
    }

    func dismissError(_ id: UUID) {
        withAnimation(Qcowork.motion.smooth) {
            errors.removeAll { $0.id == id }
        }
    }

    private func persistMessages() {
        guard let id = conversationID else { return }
        store.updateMessages(id, messages: messages)
    }
}
