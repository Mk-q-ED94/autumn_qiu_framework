import Foundation
import OSLog

@MainActor
final class OllamaManager: ObservableObject {
    enum Status: Equatable {
        case disabled
        case idle
        case checking
        case starting
        case running(external: Bool)
        case unmanaged
        case failed(String)

        var text: String {
            switch self {
            case .disabled:
                return "A4 未启用"
            case .idle:
                return "未启动"
            case .checking:
                return "检测中"
            case .starting:
                return "启动中"
            case .running(let external):
                return external ? "已连接已有 Ollama" : "已由 App 启动"
            case .unmanaged:
                return "使用外部 Ollama"
            case .failed(let message):
                return "启动失败：\(message)"
            }
        }
    }

    @Published private(set) var status: Status = .idle

    private let logger = Logger(subsystem: "com.autumn.desktop", category: "Ollama")

    var statusText: String {
        status.text
    }

    #if os(macOS)
    private var process: Process?

    func startIfNeeded(enabled: Bool, baseURL rawValue: String) async {
        guard enabled else {
            status = .disabled
            return
        }
        guard let baseURL = Self.normalizedBaseURL(from: rawValue) else {
            status = .failed("Ollama Base URL 无效")
            return
        }
        guard Self.canAutoStart(baseURL) else {
            status = .unmanaged
            return
        }
        if case .starting = status {
            return
        }
        if process?.isRunning == true {
            if await isHealthy(baseURL) {
                status = .running(external: false)
            } else {
                status = .starting
            }
            return
        }

        status = .checking
        if await isHealthy(baseURL) {
            status = .running(external: true)
            return
        }

        do {
            if let command = Self.ollamaServeCommand() {
                try startOllamaServe(command: command, baseURL: baseURL)
                status = .starting
            } else if try Self.openOllamaAppIfAvailable() {
                status = .starting
            } else {
                status = .failed("未找到 ollama 命令或 Ollama.app")
                return
            }

            for _ in 0..<32 {
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled {
                    return
                }
                if await isHealthy(baseURL) {
                    status = process?.isRunning == true
                        ? .running(external: false)
                        : .running(external: true)
                    return
                }
                if process?.isRunning == false {
                    break
                }
            }

            status = .failed("查看 build/logs/ollama.log")
        } catch {
            logger.error("Ollama startup failed: \(error.localizedDescription, privacy: .public)")
            status = .failed(error.localizedDescription)
        }
    }

    func stop() {
        guard let process else { return }
        if process.isRunning {
            process.terminate()
        }
        self.process = nil
        if status == .running(external: false) || status == .starting {
            status = .idle
        }
    }

    private func startOllamaServe(command: OllamaCommand, baseURL: URL) throws {
        let logURL = try Self.prepareLogFile()
        logger.info("Ollama stdout/stderr log: \(logURL.path, privacy: .private)")

        let logHandle = try FileHandle(forWritingTo: logURL)
        _ = try? logHandle.seekToEnd()
        if let header = "\n--- Ollama launch \(Date()) ---\n".data(using: .utf8) {
            logHandle.write(header)
        }

        let process = Process()
        process.executableURL = command.executableURL
        process.arguments = command.arguments

        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = Self.shellPath(environment["PATH"])
        environment["OLLAMA_HOST"] = Self.ollamaHost(for: baseURL)
        process.environment = environment
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self, logHandle, process] _ in
            logHandle.closeFile()
            Task { @MainActor in
                guard let self, self.process === process else { return }
                self.process = nil
                if self.status == .running(external: false) || self.status == .starting {
                    self.status = .idle
                }
            }
        }

        try process.run()
        self.process = process
    }

    private func isHealthy(_ baseURL: URL) async -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/version"))
        request.timeoutInterval = 1

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private static func normalizedBaseURL(from rawValue: String) -> URL? {
        var value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            value = "http://127.0.0.1:11434"
        }
        if !value.contains("://") {
            value = "http://\(value)"
        }

        guard var components = URLComponents(string: value) else { return nil }
        if components.path == "/v1" || components.path == "/api" {
            components.path = ""
        }
        return components.url
    }

    private static func canAutoStart(_ baseURL: URL) -> Bool {
        guard baseURL.scheme?.lowercased() == "http" else { return false }
        guard let host = baseURL.host?.lowercased() else { return false }
        return ["127.0.0.1", "localhost", "::1"].contains(host)
    }

    private static func ollamaHost(for baseURL: URL) -> String {
        let rawHost = baseURL.host?.lowercased() ?? "127.0.0.1"
        let host = (rawHost == "localhost" || rawHost == "::1") ? "127.0.0.1" : rawHost
        return "\(host):\(baseURL.port ?? 11434)"
    }

    private static func ollamaServeCommand() -> OllamaCommand? {
        let fileManager = FileManager.default
        let candidates = [
            "/opt/homebrew/bin/ollama",
            "/usr/local/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama",
            "\(NSHomeDirectory())/Applications/Ollama.app/Contents/Resources/ollama",
        ]

        for path in candidates where fileManager.isExecutableFile(atPath: path) {
            return OllamaCommand(
                executableURL: URL(fileURLWithPath: path),
                arguments: ["serve"]
            )
        }

        for directory in shellPath(ProcessInfo.processInfo.environment["PATH"]).split(separator: ":") {
            let path = "\(directory)/ollama"
            if fileManager.isExecutableFile(atPath: path) {
                return OllamaCommand(
                    executableURL: URL(fileURLWithPath: path),
                    arguments: ["serve"]
                )
            }
        }

        return nil
    }

    private static func openOllamaAppIfAvailable() throws -> Bool {
        let fileManager = FileManager.default
        let appPaths = [
            "/Applications/Ollama.app",
            "\(NSHomeDirectory())/Applications/Ollama.app",
        ]
        guard appPaths.contains(where: { fileManager.fileExists(atPath: $0) }) else {
            return false
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-gj", "-a", "Ollama"]
        try process.run()
        return true
    }

    private static func shellPath(_ inherited: String?) -> String {
        let preferred = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
        let inheritedParts = inherited?.split(separator: ":").map(String.init) ?? []
        return (preferred + inheritedParts).reduce(into: [String]()) { paths, path in
            if !paths.contains(path) {
                paths.append(path)
            }
        }
        .joined(separator: ":")
    }

    private static func prepareLogFile() throws -> URL {
        let fileManager = FileManager.default
        let logDirectory: URL
        if let repositoryRoot = repositoryRoot() {
            logDirectory = repositoryRoot.appendingPathComponent("build/logs")
        } else {
            logDirectory = fileManager
                .urls(for: .libraryDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Logs/AutumnDesktop")
        }
        try fileManager.createDirectory(at: logDirectory, withIntermediateDirectories: true)

        let logURL = logDirectory.appendingPathComponent("ollama.log")
        if !fileManager.fileExists(atPath: logURL.path) {
            _ = fileManager.createFile(atPath: logURL.path, contents: nil)
        }
        return logURL
    }

    private static func repositoryRoot() -> URL? {
        if let rawValue = Bundle.main.object(forInfoDictionaryKey: "AutumnRepositoryRoot") as? String {
            let expanded = (rawValue as NSString).expandingTildeInPath
            let candidate = URL(fileURLWithPath: expanded).standardizedFileURL
            if isRepositoryRoot(candidate) {
                return candidate
            }
        }

        var candidate = Bundle.main.bundleURL.deletingLastPathComponent()
        for _ in 0..<8 {
            if isRepositoryRoot(candidate) {
                return candidate
            }
            candidate.deleteLastPathComponent()
        }
        return nil
    }

    private static func isRepositoryRoot(_ url: URL) -> Bool {
        let fileManager = FileManager.default
        return fileManager.fileExists(atPath: url.appendingPathComponent("pyproject.toml").path)
            && fileManager.fileExists(atPath: url.appendingPathComponent("autumn/server/app.py").path)
    }
    #else
    func startIfNeeded(enabled: Bool, baseURL _: String) async {
        status = enabled ? .unmanaged : .disabled
    }

    func stop() {}
    #endif
}

private struct OllamaCommand {
    let executableURL: URL
    let arguments: [String]
}
