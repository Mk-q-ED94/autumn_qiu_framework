import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @EnvironmentObject private var ollamaManager: OllamaManager
    @State private var selectedTab: SettingsTab = .server
    @State private var connectionState: ConnectionState = .unknown
    @State private var serverLastError: String? = nil
    @State private var isChecking: Bool = false
    @State private var modelOptions: [ModelSlot: [String]] = [:]
    @State private var modelErrors: [ModelSlot: String] = [:]
    @State private var refreshTasks: [ModelSlot: Task<Void, Never>] = [:]
    @State private var validatedSlots: Set<ModelSlot> = []
    @State private var isApplying: Bool = false
    @State private var manualApplyRequired: Bool = false
    @State private var lastAppliedFingerprint: String?
    @State private var autoApplyTask: Task<Void, Never>?
    @State private var applyMessage: String? = nil
    @State private var ollamaStatus: OllamaStatus?
    @State private var ollamaModels: [OllamaModel] = []
    @State private var ollamaRecommended: [OllamaRecommendedModel] = []
    @State private var isLoadingOllama = false
    @State private var pullingOllamaModel: String?
    @State private var ollamaPullProgress: String?
    @State private var ollamaError: String?

    // 4D memory runtime switches (read from / written to the server live).
    @State private var fourdMemoryEnabled = false
    @State private var fourdPushOnTurn = false
    @State private var mom1AccessEnabled = true
    @State private var fourdLoaded = false
    @State private var fourdApplying = false
    @State private var fourdError: String?

    enum ConnectionState {
        case unknown
        case ok(configured: Bool)
        case failed(String)
    }

    enum SettingsTab: String, CaseIterable, Identifiable {
        case server, models, memory, advanced

        var id: String { rawValue }

        var title: String {
            switch self {
            case .server:   return "服务器"
            case .models:   return "模型"
            case .memory:   return "记忆"
            case .advanced: return "高级"
            }
        }

        var icon: String {
            switch self {
            case .server:   return "server.rack"
            case .models:   return "cpu"
            case .memory:   return "brain"
            case .advanced: return "slider.horizontal.3"
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            tabBar
            Divider()
            tabContent
        }
        .navigationTitle("设置")
        .onAppear {
            Task { await checkConnection() }
            Task { await loadFourD() }
            for slot in ModelSlot.allCases {
                scheduleModelRefresh(slot, delay: 0)
            }
            if settings.a4Enabled {
                Task {
                    await ensureOllamaRunning()
                    await loadOllama()
                }
            }
        }
        .onChange(of: settings.a1APIKey)   { _, _ in apiKeyChanged(.a1) }
        .onChange(of: settings.a1BaseURL)  { _, _ in modelEndpointChanged(.a1) }
        .onChange(of: settings.a1Protocol) { _, _ in modelEndpointChanged(.a1) }
        .onChange(of: settings.a1Model)    { _, _ in modelSelectionChanged() }
        .onChange(of: settings.a2APIKey)   { _, _ in apiKeyChanged(.a2) }
        .onChange(of: settings.a2BaseURL)  { _, _ in modelEndpointChanged(.a2) }
        .onChange(of: settings.a2Protocol) { _, _ in modelEndpointChanged(.a2) }
        .onChange(of: settings.a2Model)    { _, _ in modelSelectionChanged() }
        .onChange(of: settings.a3APIKey)   { _, _ in apiKeyChanged(.a3) }
        .onChange(of: settings.a3BaseURL)  { _, _ in modelEndpointChanged(.a3) }
        .onChange(of: settings.a3Protocol) { _, _ in modelEndpointChanged(.a3) }
        .onChange(of: settings.a3Model)    { _, _ in modelSelectionChanged() }
        .onChange(of: settings.a4Enabled) { _, enabled in
            if enabled {
                Task {
                    await ensureOllamaRunning()
                    await loadOllama()
                }
            }
        }
        .onChange(of: settings.a4BaseURL) { _, _ in
            guard settings.a4Enabled else { return }
            Task {
                await ensureOllamaRunning()
                await loadOllama()
            }
        }
    }

    // ── tab bar ───────────────────────────────────────────────────────────────

    private var tabBar: some View {
        HStack(spacing: Autumn.spacing.xs) {
            ForEach(SettingsTab.allCases) { tab in
                TabPill(
                    title: tab.title,
                    icon: tab.icon,
                    isSelected: selectedTab == tab,
                    action: { withAnimation(Autumn.motion.snappy) { selectedTab = tab } }
                )
            }
            Spacer()
        }
        .padding(.horizontal, Autumn.spacing.lg)
        .padding(.vertical, Autumn.spacing.sm)
        .background(.bar)
    }

    @ViewBuilder
    private var tabContent: some View {
        switch selectedTab {
        case .server:   serverTab
        case .models:   modelsTab
        case .memory:   memoryTab
        case .advanced: advancedTab
        }
    }

    // ── server tab ────────────────────────────────────────────────────────────

    private var serverTab: some View {
        Form {
            Section {
                LabeledContent("本地服务", value: localServer.statusText)

                TextField("服务器 URL", text: $settings.serverURL)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    #endif

                HStack {
                    Button(action: { Task { await checkConnection() } }) {
                        if isChecking {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("检测连接")
                        }
                    }
                    .disabled(isChecking)
                    Spacer()
                    statusLabel
                }
            } header: {
                Text("Autumn 服务器")
            } footer: {
                Text("默认本地服务器地址为 http://127.0.0.1:8765。应用启动时会自动拉起捆绑的本地服务。")
                    .font(.caption)
            }
        }
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

    // ── models tab ────────────────────────────────────────────────────────────

    private var modelsTab: some View {
        Form {
            Section {
                ForEach(ModelSlot.allCases) { slot in
                    ModelConfigRow(
                        slot: slot,
                        apiKey: apiKeyBinding(for: slot),
                        baseURL: baseURLBinding(for: slot),
                        apiProtocol: protocolBinding(for: slot),
                        model: modelBinding(for: slot),
                        models: pickerModels(for: slot),
                        state: settings.modelState(for: slot),
                        errorMessage: modelErrors[slot],
                        refresh: { scheduleModelRefresh(slot, delay: 0) }
                    )
                    if slot != ModelSlot.allCases.last {
                        Divider()
                    }
                }

                HStack {
                    Button(action: { Task { await applyConfiguration() } }) {
                        if isApplying {
                            ProgressView().controlSize(.small)
                        } else if manualApplyRequired {
                            Text("确认应用更新")
                        } else {
                            Text("应用配置")
                        }
                    }
                    .disabled(isApplying || !hasCompleteConfiguration)
                    Spacer()
                    if let applyMessage {
                        Text(applyMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else if manualApplyRequired {
                        Text("API key 已更新，确认后才切换服务器配置")
                            .font(.caption)
                            .foregroundStyle(Autumn.colors.warning)
                    } else if hasCompleteConfiguration {
                        Text("可用配置会在验证后自动同步到本地服务")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } header: {
                Text("A1 · A2 · A3")
            } footer: {
                Text("已保存且验证可用的配置会自动同步；只有更新 API key 后，需要点击确认应用以切换到新凭据。")
                    .font(.caption)
            }
        }
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

    // ── memory tab ────────────────────────────────────────────────────────────

    private var memoryTab: some View {
        Form {
            Section {
                Toggle("启用 A4", isOn: $settings.a4Enabled)

                if settings.a4Enabled {
                    LabeledContent("Ollama 后台", value: ollamaManager.statusText)

                    SecureField("API Key（本地模型可留空）", text: $settings.a4APIKey)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()

                    TextField("Base URL", text: $settings.a4BaseURL)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif

                    Picker("协议", selection: $settings.a4Protocol) {
                        Text("OpenAI").tag("openai")
                        Text("Anthropic").tag("anthropic")
                        Text("Hermes").tag("hermes")
                    }
                    .pickerStyle(.segmented)

                    TextField("模型名称", text: $settings.a4Model)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()

                    OllamaPanel(
                        status: ollamaStatus,
                        installedModels: ollamaModels,
                        recommendedModels: ollamaRecommended,
                        selectedModel: settings.a4Model,
                        isLoading: isLoadingOllama,
                        pullingModel: pullingOllamaModel,
                        pullProgress: ollamaPullProgress,
                        errorMessage: ollamaError,
                        refresh: {
                            Task {
                                await ensureOllamaRunning()
                                await loadOllama()
                            }
                        },
                        useModel: useOllamaModel,
                        pullModel: { name in Task { await pullOllamaModel(name) } }
                    )
                }
            } header: {
                Text("记忆模型 A4")
            } footer: {
                Text("A4 用于 recall 技能中向量搜索结果的合成。建议配置本地 Ollama 模型以降低成本，未启用时 recall 直接返回原始片段。")
                    .font(.caption)
            }

            Section {
                FourDRuntimeRow(
                    title: "4D 激活排序",
                    detail: "回忆、归并和淘汰时按 use / scope / trigger / retention 参与排序。",
                    icon: "brain",
                    tint: Autumn.colors.memory,
                    isOn: fourdMemoryBinding,
                    isApplying: fourdApplying
                )
                FourDRuntimeRow(
                    title: "回合推送",
                    detail: "每轮开始前自动注入 CONSTRAIN / REMIND 记忆片段。",
                    icon: "bolt.fill",
                    tint: Autumn.colors.warning,
                    isOn: fourdPushBinding,
                    isApplying: fourdApplying
                )
                FourDRuntimeRow(
                    title: "Mom1 访问治理",
                    detail: "Mom2/Mom3 读取 Mom1 前由 A1 裁决，并写入 WP4 审计日志。",
                    icon: "checkmark.shield.fill",
                    tint: Autumn.colors.teal,
                    isOn: mom1AccessBinding,
                    isApplying: fourdApplying
                )
                HStack(spacing: Autumn.spacing.sm) {
                    if fourdApplying {
                        ProgressView().controlSize(.small)
                    }
                    if let fourdError {
                        Label(fourdError, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(Autumn.colors.danger)
                            .lineLimit(1)
                    } else if fourdLoaded {
                        Label("已同步到运行中的服务", systemImage: "checkmark.circle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("刷新") { Task { await loadFourD() } }
                        .controlSize(.small)
                }
            } header: {
                Text("4D 记忆引擎")
            } footer: {
                Text("运行时开关会立即对当前服务器生效，不写回 .env；重启服务后回到 .env 默认值。")
                    .font(.caption)
            }

            Section {
                MemoryAreaCard(
                    code: "Mom1",
                    title: "顶层会话日志",
                    description: "WP1 完整对话历史 + Shared Zone 共享上下文。"
                )
                MemoryAreaCard(
                    code: "Mom2",
                    title: "任务执行记忆",
                    description: "WP2 处理 task 时的工具调用与中间产物。"
                )
                MemoryAreaCard(
                    code: "Mom3",
                    title: "Mission 记忆",
                    description: "WP3 处理 mission 时的路由判定与转换草稿。"
                )
            } header: {
                Text("记忆分区")
            } footer: {
                Text("每个分区可以挂载不同后端（DictBackend / VectorBackend / 自定义），通过 Autumn.add_memory_skills(area) 暴露 recall / remember 给模型调用。")
                    .font(.caption)
            }
        }
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

    // ── advanced tab ──────────────────────────────────────────────────────────

    private var advancedTab: some View {
        Form {
            Section {
                Picker("路由模式", selection: $settings.routeMode) {
                    Text("自动 (A3 决定)").tag("auto")
                    Text("直接回答").tag("direct")
                    Text("转为任务").tag("convert")
                }
                .pickerStyle(.segmented)

                Text(routeDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                Text("Mission 默认路由")
            }

            Section {
                LabeledContent("版本", value: "0.2.1")
                Text("秋 / Autumn — 多模型协作工作流框架。")
                    .font(.callout)
                Text("A1/A2/A3 驱动主工作流，A4/WP4 负责记忆管理、项目元数据和归并。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: {
                Text("关于")
            }
        }
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

    // ── shared helpers ────────────────────────────────────────────────────────

    @ViewBuilder
    private var statusLabel: some View {
        switch connectionState {
        case .unknown:
            Text("未检测").font(.caption).foregroundStyle(.secondary)
        case .ok(let configured):
            VStack(alignment: .trailing, spacing: 2) {
                HStack(spacing: 4) {
                    Image(systemName: configured ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    Text(configured ? "已连接" : "已连接（服务器未配置 API key）")
                }
                .font(.caption)
                .foregroundStyle(configured ? Autumn.colors.success : Autumn.colors.warning)
                if let err = serverLastError {
                    Text(err)
                        .font(.caption2)
                        .foregroundStyle(Autumn.colors.danger)
                }
            }
        case .failed(let msg):
            HStack(spacing: 4) {
                Image(systemName: "xmark.circle.fill")
                Text(msg)
            }
            .font(.caption)
            .foregroundStyle(.red)
        }
    }

    private var routeDescription: String {
        switch settings.routeMode {
        case "direct": return "mission 直接由 A3 回答，再经 WP1.checker。"
        case "convert": return "mission 由 A3 转为任务，再走 WP2 全流程。"
        default: return "由 A3 在运行时为每条 mission 选择路由。"
        }
    }

    private var fourdMemoryBinding: Binding<Bool> {
        Binding(
            get: { fourdMemoryEnabled },
            set: { fourdMemoryEnabled = $0; Task { await applyFourD() } }
        )
    }

    private var fourdPushBinding: Binding<Bool> {
        Binding(
            get: { fourdPushOnTurn },
            set: { fourdPushOnTurn = $0; Task { await applyFourD() } }
        )
    }

    private var mom1AccessBinding: Binding<Bool> {
        Binding(
            get: { mom1AccessEnabled },
            set: { mom1AccessEnabled = $0; Task { await applyFourD() } }
        )
    }

    private func checkConnection() async {
        guard let url = URL(string: settings.serverURL) else {
            connectionState = .failed("URL 无效")
            return
        }
        isChecking = true
        defer { isChecking = false }

        let client = AutumnClient(baseURL: url)
        if let health = await client.health() {
            serverLastError = health.lastError.flatMap { $0.isEmpty ? nil : $0 }
            connectionState = .ok(configured: health.configured)
        } else {
            serverLastError = nil
            connectionState = .failed("无法连接到服务器")
        }
    }

    // ── 4D runtime switches ─────────────────────────────────────────────────────

    private func loadFourD() async {
        guard let url = URL(string: settings.serverURL) else {
            fourdError = "服务器 URL 无效"
            fourdLoaded = false
            return
        }
        do {
            let status = try await AutumnClient(baseURL: url).fetch4DStatus()
            // Assign the @State directly (not via the toggles' bindings) so syncing
            // from the server does not trigger an apply round-trip.
            fourdMemoryEnabled = status.fourdMemoryEnabled
            fourdPushOnTurn = status.fourdPushOnTurn
            mom1AccessEnabled = status.mom1AccessEnabled
            fourdError = nil
            fourdLoaded = true
        } catch {
            fourdError = error.localizedDescription
            fourdLoaded = false
        }
    }

    private func applyFourD() async {
        guard let url = URL(string: settings.serverURL) else {
            fourdError = "服务器 URL 无效"
            return
        }
        fourdApplying = true
        defer { fourdApplying = false }
        do {
            let status = try await AutumnClient(baseURL: url).update4DConfig(
                memoryEnabled: fourdMemoryEnabled,
                pushOnTurn: fourdPushOnTurn,
                mom1AccessEnabled: mom1AccessEnabled
            )
            fourdMemoryEnabled = status.fourdMemoryEnabled
            fourdPushOnTurn = status.fourdPushOnTurn
            mom1AccessEnabled = status.mom1AccessEnabled
            fourdError = nil
            fourdLoaded = true
        } catch {
            fourdError = error.localizedDescription
        }
    }

    private func apiKeyChanged(_ slot: ModelSlot) {
        validatedSlots.remove(slot)
        manualApplyRequired = true
        applyMessage = "API key 已更新，检测通过后请确认应用"
        scheduleModelRefresh(slot)
    }

    private func modelEndpointChanged(_ slot: ModelSlot) {
        validatedSlots.remove(slot)
        applyMessage = manualApplyRequired ? applyMessage : "正在验证模型服务…"
        scheduleModelRefresh(slot)
    }

    private func modelSelectionChanged() {
        applyMessage = manualApplyRequired ? applyMessage : "模型已更新，准备自动同步…"
        scheduleAutoApplyConfiguration()
    }

    private func apiKeyBinding(for slot: ModelSlot) -> Binding<String> {
        switch slot {
        case .a1: return $settings.a1APIKey
        case .a2: return $settings.a2APIKey
        case .a3: return $settings.a3APIKey
        }
    }

    private func baseURLBinding(for slot: ModelSlot) -> Binding<String> {
        switch slot {
        case .a1: return $settings.a1BaseURL
        case .a2: return $settings.a2BaseURL
        case .a3: return $settings.a3BaseURL
        }
    }

    private func protocolBinding(for slot: ModelSlot) -> Binding<String> {
        switch slot {
        case .a1: return $settings.a1Protocol
        case .a2: return $settings.a2Protocol
        case .a3: return $settings.a3Protocol
        }
    }

    private func modelBinding(for slot: ModelSlot) -> Binding<String> {
        switch slot {
        case .a1: return $settings.a1Model
        case .a2: return $settings.a2Model
        case .a3: return $settings.a3Model
        }
    }

    private func currentModel(for slot: ModelSlot) -> String {
        switch slot {
        case .a1: return settings.a1Model
        case .a2: return settings.a2Model
        case .a3: return settings.a3Model
        }
    }

    private func setModel(_ value: String, for slot: ModelSlot) {
        switch slot {
        case .a1: settings.a1Model = value
        case .a2: settings.a2Model = value
        case .a3: settings.a3Model = value
        }
    }

    private func pickerModels(for slot: ModelSlot) -> [String] {
        var values = modelOptions[slot] ?? []
        let current = currentModel(for: slot)
        if !current.isEmpty && !values.contains(current) {
            values.insert(current, at: 0)
        }
        return values
    }

    private func scheduleModelRefresh(_ slot: ModelSlot, delay: UInt64 = 700_000_000) {
        refreshTasks[slot]?.cancel()
        refreshTasks[slot] = Task {
            if delay > 0 {
                try? await Task.sleep(nanoseconds: delay)
            }
            if Task.isCancelled { return }
            await refreshModels(for: slot)
        }
    }

    private func refreshModels(for slot: ModelSlot) async {
        guard let url = URL(string: settings.serverURL) else {
            modelErrors[slot] = "服务器 URL 无效"
            return
        }

        let config = settings.providerConfig(for: slot)
        guard !config.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            modelOptions[slot] = []
            modelErrors[slot] = nil
            validatedSlots.remove(slot)
            settings.setModelState(.unconfigured, for: slot)
            return
        }
        guard !config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            modelErrors[slot] = "Base URL 为空"
            validatedSlots.remove(slot)
            settings.setModelState(.unconfigured, for: slot)
            return
        }

        settings.setModelState(.connecting, for: slot)
        modelErrors[slot] = nil

        do {
            let client = AutumnClient(baseURL: url)
            let models = try await client.fetchModels(
                apiKey: config.apiKey,
                baseURL: config.baseURL,
                apiProtocol: config.apiProtocol
            )
            modelOptions[slot] = models
            if currentModel(for: slot).isEmpty, let first = models.first {
                setModel(first, for: slot)
            }
            settings.setModelState(.ready, for: slot)
            validatedSlots.insert(slot)
            scheduleAutoApplyConfiguration()
        } catch {
            validatedSlots.remove(slot)
            modelErrors[slot] = error.localizedDescription
            settings.setModelState(.failed, for: slot)
        }
    }

    private func applyConfiguration(automatic: Bool = false) async {
        guard let url = URL(string: settings.serverURL) else {
            applyMessage = "服务器 URL 无效"
            connectionState = .failed("URL 无效")
            return
        }
        guard hasCompleteConfiguration else {
            applyMessage = "请填写 A1/A2/A3 的 Key 和模型"
            return
        }
        guard hasValidatedConfiguration else {
            applyMessage = "请等待 A1/A2/A3 模型列表验证完成"
            return
        }

        isApplying = true
        applyMessage = nil
        defer { isApplying = false }

        do {
            let client = AutumnClient(baseURL: url)
            let response = try await client.applyConfiguration(settings.applyConfigRequest())
            connectionState = .ok(configured: response.configured)
            lastAppliedFingerprint = configurationFingerprint
            manualApplyRequired = false
            applyMessage = automatic ? "已自动应用可用配置" : "已应用"
            for slot in ModelSlot.allCases {
                settings.setModelState(.ready, for: slot)
            }
        } catch {
            applyMessage = error.localizedDescription
            connectionState = .failed(error.localizedDescription)
        }
    }

    private func scheduleAutoApplyConfiguration(delay: UInt64 = 350_000_000) {
        autoApplyTask?.cancel()
        autoApplyTask = Task {
            try? await Task.sleep(nanoseconds: delay)
            if Task.isCancelled { return }
            await maybeAutoApplyConfiguration()
        }
    }

    private func maybeAutoApplyConfiguration() async {
        guard !manualApplyRequired else { return }
        guard hasCompleteConfiguration, hasValidatedConfiguration else { return }
        guard !isApplying else { return }
        let fingerprint = configurationFingerprint
        guard fingerprint != lastAppliedFingerprint else { return }
        await applyConfiguration(automatic: true)
    }

    private var hasCompleteConfiguration: Bool {
        for slot in ModelSlot.allCases {
            let config = settings.providerConfig(for: slot)
            if config.apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return false
            }
            if config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return false
            }
            if (config.model ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return false
            }
        }
        return true
    }

    private var hasValidatedConfiguration: Bool {
        ModelSlot.allCases.allSatisfy { validatedSlots.contains($0) }
    }

    private var configurationFingerprint: String {
        ModelSlot.allCases.map { slot in
            let config = settings.providerConfig(for: slot)
            return [
                slot.rawValue,
                config.apiKey,
                config.baseURL,
                config.apiProtocol,
                config.model ?? "",
            ].joined(separator: "\u{1F}")
        }
        .joined(separator: "\u{1E}")
    }

    private func ensureOllamaRunning() async {
        await ollamaManager.startIfNeeded(
            enabled: settings.a4Enabled,
            baseURL: settings.a4BaseURL
        )
    }

    private func loadOllama() async {
        isLoadingOllama = true
        ollamaError = nil
        defer { isLoadingOllama = false }

        do {
            let localClient = try LocalOllamaClient(baseURL: settings.a4BaseURL)
            async let status = localClient.status()
            async let recommended = loadRecommendedOllamaModels()
            let resolvedStatus = await status
            ollamaStatus = resolvedStatus
            ollamaRecommended = await recommended
            if resolvedStatus.running {
                do {
                    ollamaModels = try await localClient.models()
                } catch {
                    ollamaModels = []
                    ollamaError = ollamaManagementError(error, baseURL: resolvedStatus.baseURL)
                }
            } else {
                ollamaModels = []
                ollamaError = ollamaUnavailableMessage(resolvedStatus)
            }
        } catch {
            ollamaModels = []
            ollamaError = error.localizedDescription
        }
    }

    private func loadRecommendedOllamaModels() async -> [OllamaRecommendedModel] {
        guard let url = URL(string: settings.serverURL) else {
            return fallbackOllamaRecommended
        }
        do {
            return try await AutumnClient(baseURL: url).ollamaRecommendedModels()
        } catch {
            return fallbackOllamaRecommended
        }
    }

    private func useOllamaModel(_ name: String) {
        settings.a4Enabled = true
        settings.a4Protocol = "openai"
        if settings.a4BaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            settings.a4BaseURL = "http://127.0.0.1:11434"
        }
        settings.a4APIKey = settings.a4APIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "ollama"
            : settings.a4APIKey
        settings.a4Model = name
    }

    private func pullOllamaModel(_ name: String) async {
        pullingOllamaModel = name
        ollamaPullProgress = "准备拉取"
        ollamaError = nil
        defer {
            pullingOllamaModel = nil
            ollamaPullProgress = nil
        }

        do {
            let localClient = try LocalOllamaClient(baseURL: settings.a4BaseURL)
            let status = await localClient.status()
            ollamaStatus = status
            guard status.running else {
                ollamaError = ollamaUnavailableMessage(status)
                return
            }
            for try await event in localClient.pullModel(name: name) {
                if let fraction = event.progressFraction {
                    ollamaPullProgress = "\(Int((fraction * 100).rounded()))%"
                } else if let status = event.status {
                    ollamaPullProgress = status
                }
            }
            useOllamaModel(name)
            await loadOllama()
        } catch {
            ollamaError = ollamaManagementError(error, baseURL: settings.a4BaseURL)
        }
    }

    private func ollamaUnavailableMessage(_ status: OllamaStatus) -> String {
        let base = status.baseURL.isEmpty ? settings.a4BaseURL : status.baseURL
        let raw = status.error?.isEmpty == false ? "\n\(status.error ?? "")" : ""
        return "无法连接本机 Ollama（\(base)）。Autumn Desktop 已尝试后台启动 Ollama；请确认 Ollama.app 或 `ollama serve` 正在运行。\(raw)"
    }

    private func ollamaManagementError(_ error: Error, baseURL: String) -> String {
        let base = baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "http://127.0.0.1:11434"
            : baseURL
        return "A4 本地模型操作失败（\(base)）：\(error.localizedDescription)"
    }

    private var fallbackOllamaRecommended: [OllamaRecommendedModel] {
        [
            OllamaRecommendedModel(
                name: "qwen2.5:1.5b",
                label: "Qwen2.5 1.5B",
                size: "~1.0 GB",
                note: "速度/质量平衡 · A4 推荐",
                recommended: true
            ),
            OllamaRecommendedModel(
                name: "qwen2.5:3b",
                label: "Qwen2.5 3B",
                size: "~2.0 GB",
                note: "更强理解 · 仍然轻量",
                recommended: false
            ),
            OllamaRecommendedModel(
                name: "llama3.2:3b",
                label: "Llama 3.2 3B",
                size: "~2.0 GB",
                note: "Meta 通用小模型",
                recommended: false
            ),
        ]
    }
}

// MARK: - Tab pill

private struct TabPill: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .semibold))
                Text(title)
                    .font(Autumn.typography.captionMedium)
            }
            .foregroundStyle(isSelected ? Color.white : .primary)
            .padding(.horizontal, 12)
            .padding(.vertical, 5)
            .background(
                Capsule().fill(isSelected
                               ? AnyShapeStyle(Autumn.colors.brandGradient)
                               : AnyShapeStyle(Autumn.colors.surfaceElevated))
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Memory area card

private struct FourDRuntimeRow: View {
    let title: String
    let detail: String
    let icon: String
    let tint: Color
    @Binding var isOn: Bool
    let isApplying: Bool

    var body: some View {
        HStack(alignment: .center, spacing: Autumn.spacing.sm) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 26, height: 26)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(tint.opacity(0.12))
                )

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Autumn.typography.captionMedium)
                Text(detail)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: Autumn.spacing.md)

            Toggle("", isOn: $isOn)
                .labelsHidden()
                .toggleStyle(.switch)
                .disabled(isApplying)
        }
        .padding(.vertical, 3)
    }
}

private struct MemoryAreaCard: View {
    let code: String
    let title: String
    let description: String

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            Text(code)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(.tint)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.xs, style: .continuous)
                        .fill(Autumn.colors.flame.opacity(0.13))
                )
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Autumn.typography.captionMedium)
                Text(description)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        .padding(.vertical, 2)
    }
}

private struct ModelConfigRow: View {
    let slot: ModelSlot
    @Binding var apiKey: String
    @Binding var baseURL: String
    @Binding var apiProtocol: String
    @Binding var model: String
    let models: [String]
    let state: ModelConnectionState
    let errorMessage: String?
    let refresh: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(slot.title)
                        .font(.headline)
                    Text(slot.subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Menu {
                    ForEach(ProviderPresets.all) { preset in
                        Button {
                            baseURL = preset.baseURL
                            apiProtocol = preset.apiProtocol
                        } label: {
                            if let note = preset.note {
                                Text("\(preset.name) · \(note)")
                            } else {
                                Text(preset.name)
                            }
                        }
                    }
                } label: {
                    Label("预置", systemImage: "wand.and.stars")
                        .font(.caption)
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("快速填入常见服务商")
                AutumnBadge(state.title, tone: state.tone)
                if state == .connecting {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            SecureField("API Key", text: $apiKey)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()

            TextField("Base URL", text: $baseURL)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                #endif
                .onChange(of: baseURL) { _, newValue in
                    guard apiProtocol != "hermes" else { return }
                    let detected = ProviderPresets.detectProtocol(baseURL: newValue)
                    if detected != apiProtocol {
                        apiProtocol = detected
                    }
                }

            Picker("协议", selection: $apiProtocol) {
                Text("OpenAI").tag("openai")
                Text("Anthropic").tag("anthropic")
                Text("Hermes").tag("hermes")
            }
            .pickerStyle(.segmented)

            HStack {
                Picker("模型", selection: $model) {
                    if models.isEmpty {
                        Text(model.isEmpty ? "未获取模型" : model).tag(model)
                    } else {
                        ForEach(models, id: \.self) { value in
                            Text(value).tag(value)
                        }
                    }
                }
                .disabled(models.isEmpty && model.isEmpty)

                Button(action: refresh) {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .disabled(state == .connecting || apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("刷新模型")
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(.vertical, 4)
    }
}
