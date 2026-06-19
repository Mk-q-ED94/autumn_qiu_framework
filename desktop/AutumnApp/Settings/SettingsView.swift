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

    // Platform integrations (GitHub etc.) — catalog + live connection state.
    @State private var integrationCatalog: [IntegrationCatalogEntry] = []
    @State private var integrationStatuses: [String: IntegrationStatus] = [:]
    @State private var integrationBusy: Set<String> = []
    @State private var integrationErrors: [String: String] = [:]
    @State private var integrationsLoaded = false

    enum ConnectionState {
        case unknown
        case ok(configured: Bool)
        case failed(String)
    }

    enum SettingsTab: String, CaseIterable, Identifiable {
        case server, models, memory, integrations, advanced

        var id: String { rawValue }

        var title: String {
            switch self {
            case .server:       return "服务器"
            case .models:       return "模型"
            case .memory:       return "记忆"
            case .integrations: return "集成"
            case .advanced:     return "高级"
            }
        }

        var icon: String {
            switch self {
            case .server:       return "server.rack"
            case .models:       return "cpu"
            case .memory:       return "brain"
            case .integrations: return "key.fill"
            case .advanced:     return "slider.horizontal.3"
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
        // Same flush `.bar` tab bar as Memory/Terrs — hide the window title
        // bar's automatic material so it can't overshoot and cover the top edge.
        .toolbarBackground(.hidden, for: .windowToolbar)
        .onAppear {
            Task { await checkConnection() }
            Task { await loadFourD() }
            Task { await loadIntegrations() }
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
        case .server:       serverTab
        case .models:       modelsTab
        case .memory:       memoryTab
        case .integrations: integrationsTab
        case .advanced:     advancedTab
        }
    }

    // ── server tab ────────────────────────────────────────────────────────────

    private var serverTab: some View {
        SettingsScroll {
            SettingsSection(
                title: "Autumn 服务器",
                footer: "默认本地服务器地址为 http://127.0.0.1:8765。应用启动时会自动拉起捆绑的本地服务。"
            ) {
                LabeledContent("本地服务", value: localServer.statusText)

                SettingsFieldRow("服务器 URL") {
                    TextField("服务器 URL", text: $settings.serverURL)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                }

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
            }

            SettingsSection(
                title: "访问密钥",
                footer: "当服务器设置了 AUTUMN_API_KEY（部署到本机以外时强烈建议开启）时，在此填入同一密钥；客户端会在每个请求上携带它。本地单用户运行可留空。"
            ) {
                SettingsFieldRow("API Key（本地服务器可留空）") {
                    SecureField("API Key", text: $settings.serverAPIKey)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                }
            }
        }
    }

    // ── models tab ────────────────────────────────────────────────────────────

    private var modelsTab: some View {
        SettingsScroll {
            SettingsSection(
                title: "A1 · A2 · A3",
                footer: "已保存且验证可用的配置会自动同步；只有更新 API key 后，需要点击确认应用以切换到新凭据。"
            ) {
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
            }
        }
    }

    // ── memory tab ────────────────────────────────────────────────────────────

    private var memoryTab: some View {
        SettingsScroll {
            SettingsSection(
                title: "记忆模型 A4",
                footer: "A4 用于 recall 技能中向量搜索结果的合成。建议配置本地 Ollama 模型以降低成本，未启用时 recall 直接返回原始片段。"
            ) {
                Toggle("启用 A4", isOn: $settings.a4Enabled)

                if settings.a4Enabled {
                    LabeledContent("Ollama 后台", value: ollamaManager.statusText)

                    SettingsFieldRow("API Key（本地模型可留空）") {
                        SecureField("API Key", text: $settings.a4APIKey)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                    }

                    SettingsFieldRow("Base URL") {
                        TextField("Base URL", text: $settings.a4BaseURL)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                            #if os(iOS)
                            .textInputAutocapitalization(.never)
                            .keyboardType(.URL)
                            #endif
                    }

                    SettingsFieldRow("协议") {
                        Picker("协议", selection: $settings.a4Protocol) {
                            Text("OpenAI").tag("openai")
                            Text("Anthropic").tag("anthropic")
                            Text("Hermes").tag("hermes")
                        }
                        .pickerStyle(.segmented)
                    }

                    SettingsFieldRow("模型名称") {
                        TextField("模型名称", text: $settings.a4Model)
                            .textFieldStyle(.roundedBorder)
                            .autocorrectionDisabled()
                    }

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
            }

            SettingsSection(
                title: "4D 记忆引擎",
                footer: "运行时开关会立即对当前服务器生效，不写回 .env；重启服务后回到 .env 默认值。"
            ) {
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
            }

            SettingsSection(
                title: "记忆分区",
                footer: "每个分区可以挂载不同后端（DictBackend / VectorBackend / 自定义），通过 Autumn.add_memory_skills(area) 暴露 recall / remember 给模型调用。"
            ) {
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
            }
        }
    }

    // ── integrations tab ──────────────────────────────────────────────────────

    private var integrationsTab: some View {
        SettingsScroll {
            SettingsSection(
                title: "平台集成",
                footer: "填入平台令牌后点击连接，Autumn 会在服务器侧启动对应的 MCP 服务。当你的请求涉及读写该平台内容（如 GitHub 的 issues、PR、仓库文件）时，agent 会自行调用这些工具，无需每次手动提供凭据。令牌仅保存在本地与运行中的服务器进程，状态接口不会回传明文。需要服务器主机安装 npx / uvx。"
            ) {
                if integrationCatalog.isEmpty {
                    HStack(spacing: Autumn.spacing.sm) {
                        if !integrationsLoaded {
                            ProgressView().controlSize(.small)
                        } else {
                            Image(systemName: "wifi.slash").foregroundStyle(.secondary)
                        }
                        Text(integrationsLoaded ? "服务器未提供集成目录，或尚未连接。" : "正在加载平台目录…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    ForEach(integrationCatalog) { entry in
                        IntegrationRow(
                            entry: entry,
                            settings: settings,
                            status: integrationStatuses[entry.id],
                            isBusy: integrationBusy.contains(entry.id),
                            errorMessage: integrationErrors[entry.id],
                            onConnect: { writeEnabled in
                                Task { await connectIntegration(entry, writeEnabled: writeEnabled) }
                            },
                            onDisconnect: { Task { await disconnectIntegration(entry) } }
                        )
                        if entry.id != integrationCatalog.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }

    // ── advanced tab ──────────────────────────────────────────────────────────

    private var advancedTab: some View {
        SettingsScroll {
            SettingsSection(title: "Mission 默认路由") {
                Picker("路由模式", selection: $settings.routeMode) {
                    Text("自动 (A3 决定)").tag("auto")
                    Text("直接回答").tag("direct")
                    Text("转为任务").tag("convert")
                }
                .pickerStyle(.segmented)

                Text(routeDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            SettingsSection(title: "关于") {
                LabeledContent("版本", value: appVersion)
                Text("秋 / Autumn — 多模型协作工作流框架。")
                    .font(.callout)
                Text("A1/A2/A3 驱动主工作流，A4/WP4 负责记忆管理、项目元数据和归并。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
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

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
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

    // ── platform integrations ───────────────────────────────────────────────────

    private func loadIntegrations() async {
        guard let url = URL(string: settings.serverURL) else { return }
        let client = AutumnClient(baseURL: url)
        if let catalog = try? await client.integrationCatalog() {
            integrationCatalog = catalog
        }
        await refreshIntegrationStatus(client: client)
        integrationsLoaded = true
    }

    private func refreshIntegrationStatus(client: AutumnClient) async {
        if let statuses = try? await client.integrationStatus() {
            integrationStatuses = Dictionary(statuses.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
        }
    }

    private func connectIntegration(_ entry: IntegrationCatalogEntry, writeEnabled: Bool) async {
        guard let url = URL(string: settings.serverURL) else { return }
        integrationErrors[entry.id] = nil
        integrationBusy.insert(entry.id)
        defer { integrationBusy.remove(entry.id) }
        let client = AutumnClient(baseURL: url)
        do {
            let status = try await client.connectIntegration(
                id: entry.id,
                args: settings.integrationArgs(for: entry),
                writeEnabled: writeEnabled
            )
            integrationStatuses[entry.id] = status
        } catch {
            integrationErrors[entry.id] = error.localizedDescription
            await refreshIntegrationStatus(client: client)
        }
    }

    private func disconnectIntegration(_ entry: IntegrationCatalogEntry) async {
        guard let url = URL(string: settings.serverURL) else { return }
        integrationErrors[entry.id] = nil
        integrationBusy.insert(entry.id)
        defer { integrationBusy.remove(entry.id) }
        let client = AutumnClient(baseURL: url)
        do {
            let status = try await client.disconnectIntegration(id: entry.id)
            integrationStatuses[entry.id] = status
        } catch {
            integrationErrors[entry.id] = error.localizedDescription
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

// MARK: - Settings surface

private struct SettingsScroll<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Autumn.spacing.xl) {
                content()
            }
            .frame(maxWidth: 980, alignment: .topLeading)
            .padding(.horizontal, Autumn.spacing.xxl)
            .padding(.vertical, Autumn.spacing.xl)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .scrollContentBackground(.hidden)
        .background(Color.clear)
    }
}

private struct SettingsSection<Content: View>: View {
    let title: String
    var footer: String?
    @ViewBuilder var content: () -> Content

    init(
        title: String,
        footer: String? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.footer = footer
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            Text(title)
                .font(Autumn.typography.headline)
                .padding(.horizontal, Autumn.spacing.sm)

            AutumnCard(padding: Autumn.spacing.md) {
                VStack(alignment: .leading, spacing: Autumn.spacing.md) {
                    content()
                }
            }

            if let footer, !footer.isEmpty {
                Text(footer)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, Autumn.spacing.sm)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct SettingsFieldRow<Content: View>: View {
    let title: String
    @ViewBuilder var content: () -> Content

    init(_ title: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.md) {
            Text(title)
                .font(Autumn.typography.callout.weight(.medium))
                .foregroundStyle(.primary)
                .frame(width: 230, alignment: .leading)
            content()
                .frame(maxWidth: .infinity)
        }
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

// MARK: - 4D runtime row

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

// MARK: - Integration row

private struct IntegrationRow: View {
    let entry: IntegrationCatalogEntry
    @ObservedObject var settings: AppSettings
    let status: IntegrationStatus?
    let isBusy: Bool
    let errorMessage: String?
    let onConnect: (Bool) -> Void
    let onDisconnect: () -> Void

    /// User's pending write-access choice. Mirrors the server's truth when the
    /// platform is connected; takes effect on the next (re)connect.
    @State private var writeEnabled: Bool = false

    private var connected: Bool { status?.connected == true }

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            header
            ForEach(entry.fields) { field in
                fieldEditor(field)
            }
            writeAccessControl
            if let msg = displayedError, !msg.isEmpty {
                Label(msg, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(Autumn.colors.danger)
                    .lineLimit(2)
            }
            actions
        }
        .padding(.vertical, Autumn.spacing.xs)
        .onAppear { writeEnabled = status?.writeEnabled ?? false }
        .onChange(of: status?.writeEnabled) { _, newValue in
            writeEnabled = newValue ?? false
        }
    }

    private var writeAccessControl: some View {
        VStack(alignment: .leading, spacing: 2) {
            Toggle(isOn: $writeEnabled) {
                Text("允许写操作（创建 / 编辑 / 删除 / 发送）")
                    .font(Autumn.typography.caption)
            }
            #if os(macOS)
            .toggleStyle(.switch)
            .controlSize(.mini)
            #endif
            Text(writeEnabled
                 ? "Agent 可在该平台上修改你的真实账户内容，连接后立即生效。"
                 : "默认只读：Agent 仅能读取，无法修改你的账户。开启后需（重新）连接才生效。")
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            Image(systemName: iconName)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(connected ? Autumn.colors.success : Autumn.colors.muted)
                .frame(width: 26, height: 26)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill((connected ? Autumn.colors.success : Autumn.colors.muted).opacity(0.12))
                )
            VStack(alignment: .leading, spacing: 1) {
                Text(entry.name).font(Autumn.typography.bodyMedium)
                Text(entry.description)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            if connected {
                VStack(alignment: .trailing, spacing: 3) {
                    AutumnBadge("已连接 · \(status?.toolCount ?? 0) 工具",
                                icon: "checkmark.circle.fill", tone: .success)
                    if status?.writeEnabled == true {
                        AutumnBadge("可写", icon: "pencil", tone: .warning)
                    } else {
                        AutumnBadge(blockedBadgeText, icon: "lock.fill", tone: .neutral)
                    }
                }
            }
        }
    }

    private var blockedBadgeText: String {
        let blocked = status?.blockedToolCount ?? 0
        return blocked > 0 ? "只读 · 屏蔽 \(blocked) 个写工具" : "只读"
    }

    @ViewBuilder
    private func fieldEditor(_ field: IntegrationField) -> some View {
        if field.secret {
            SecureField(field.label, text: binding(for: field.key))
                .textFieldStyle(.roundedBorder)
        } else {
            TextField(field.label, text: binding(for: field.key))
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
        }
    }

    private var actions: some View {
        HStack(spacing: Autumn.spacing.sm) {
            if connected {
                Button(role: .destructive, action: onDisconnect) {
                    Text("断开")
                }
                .disabled(isBusy)
            }
            Spacer()
            Button(action: { onConnect(writeEnabled) }) {
                if isBusy {
                    ProgressView().controlSize(.small)
                } else {
                    Text(connected ? "更新凭据" : "连接")
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isBusy || !hasRequiredFields)
        }
    }

    private var displayedError: String? {
        errorMessage ?? status?.error
    }

    private var hasRequiredFields: Bool {
        entry.fields.filter { !$0.optional }.allSatisfy { field in
            !settings.integrationValue(entry.id, field.key)
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private func binding(for key: String) -> Binding<String> {
        Binding(
            get: { settings.integrationValue(entry.id, key) },
            set: { settings.setIntegrationValue(entry.id, key, $0) }
        )
    }

    private var iconName: String {
        switch entry.id {
        case "github":       return "chevron.left.forwardslash.chevron.right"
        case "gitlab":       return "arrow.triangle.branch"
        case "slack":        return "number"
        case "brave_search": return "magnifyingglass"
        case "google_maps":  return "map.fill"
        case "postgres":     return "cylinder.split.1x2"
        default:             return "key.fill"
        }
    }
}

// MARK: - Memory area card

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
