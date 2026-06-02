import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @State private var connectionState: ConnectionState = .unknown
    @State private var isChecking: Bool = false

    enum ConnectionState {
        case unknown
        case ok(configured: Bool)
        case failed(String)
    }

    var body: some View {
        Form {
            Section("服务器") {
                TextField("Server URL", text: $settings.serverURL)
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
            }

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
                Text("秋/Autumn — 多模型协作工作流框架。")
                    .font(.callout)
                Text("API 凭据 (A1/A2/A3) 在服务器端的 .env 文件中配置。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("设置")
        #if os(macOS)
        .formStyle(.grouped)
        #endif
    }

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
}
