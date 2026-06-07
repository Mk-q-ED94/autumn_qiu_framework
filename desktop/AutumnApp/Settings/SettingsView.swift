import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var localServer: LocalServerManager
    @State private var selectedTab: SettingsTab = .server
    @State private var connectionState: ConnectionState = .unknown
    @State private var isChecking: Bool = false
    @State private var modelOptions: [ModelSlot: [String]] = [:]
    @State private var modelErrors: [ModelSlot: String] = [:]
    @State private var refreshTasks: [ModelSlot: Task<Void, Never>] = [:]
    @State private var isApplying: Bool = false
    @State private var applyMessage: String? = nil

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
            for slot in ModelSlot.allCases {
                scheduleModelRefresh(slot, delay: 0)
            }
        }
        .onChange(of: settings.a1APIKey)   { _, _ in scheduleModelRefresh(.a1) }
        .onChange(of: settings.a1BaseURL)  { _, _ in scheduleModelRefresh(.a1) }
        .onChange(of: settings.a1Protocol) { _, _ in scheduleModelRefresh(.a1) }
        .onChange(of: settings.a2APIKey)   { _, _ in scheduleModelRefresh(.a2) }
        .onChange(of: settings.a2BaseURL)  { _, _ in scheduleModelRefresh(.a2) }
        .onChange(of: settings.a2Protocol) { _, _ in scheduleModelRefresh(.a2) }
        .onChange(of: settings.a3APIKey)   { _, _ in scheduleModelRefresh(.a3) }
        .onChange(of: settings.a3BaseURL)  { _, _ in scheduleModelRefresh(.a3) }
        .onChange(of: settings.a3Protocol) { _, _ in scheduleModelRefresh(.a3) }
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
            Section("Autumn 服务器") {
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
            Section("A1 · A2 · A3") {
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
                        } else {
                            Text("应用配置")
                        }
                    }
                    .disabled(isApplying)
                    Spacer()
                    if let applyMessage {
                        Text(applyMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } footer: {
                Text("三个 slot 都填好后点击「应用配置」才会推送到 Autumn 服务器。")
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
                }
            } header: {
                Text("记忆模型 A4")
            } footer: {
                Text("A4 用于 recall 技能中向量搜索结果的合成。建议配置本地 Ollama 模型以降低成本，未启用时 recall 直接返回原始片段。")
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
            Section("Mission 默认路由") {
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

            Section("关于") {
                LabeledContent("版本", value: "0.1.0")
                Text("秋 / Autumn — 多模型协作工作流框架。")
                    .font(.callout)
                Text("A1/A2/A3 配置由本页应用到本地 Autumn 服务器。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
            HStack(spacing: 4) {
                Image(systemName: configured ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                Text(configured ? "已连接" : "已连接（服务器未配置 API key）")
            }
            .font(.caption)
            .foregroundStyle(configured ? .green : .orange)
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

    private func checkConnection() async {
        guard let url = URL(string: settings.serverURL) else {
            connectionState = .failed("URL 无效")
            return
        }
        isChecking = true
        defer { isChecking = false }

        let client = AutumnClient(baseURL: url)
        if let health = await client.health() {
            connectionState = .ok(configured: health.configured)
        } else {
            connectionState = .failed("无法连接到服务器")
        }
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
            settings.setModelState(.unconfigured, for: slot)
            return
        }
        guard !config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            modelErrors[slot] = "Base URL 为空"
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
        } catch {
            modelErrors[slot] = error.localizedDescription
            settings.setModelState(.failed, for: slot)
        }
    }

    private func applyConfiguration() async {
        guard let url = URL(string: settings.serverURL) else {
            applyMessage = "服务器 URL 无效"
            connectionState = .failed("URL 无效")
            return
        }
        guard hasCompleteConfiguration else {
            applyMessage = "请填写 A1/A2/A3 的 Key 和模型"
            return
        }

        isApplying = true
        applyMessage = nil
        defer { isApplying = false }

        do {
            let client = AutumnClient(baseURL: url)
            let response = try await client.applyConfiguration(settings.applyConfigRequest())
            connectionState = .ok(configured: response.configured)
            applyMessage = "已应用"
            for slot in ModelSlot.allCases {
                settings.setModelState(.ready, for: slot)
            }
        } catch {
            applyMessage = error.localizedDescription
            connectionState = .failed(error.localizedDescription)
        }
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
                Capsule().fill(isSelected ? Color.accentColor : Color.secondary.opacity(0.10))
            )
        }
        .buttonStyle(.plain)
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
                    RoundedRectangle(cornerRadius: 4, style: .continuous)
                        .fill(Color.accentColor.opacity(0.12))
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
