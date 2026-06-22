import Foundation
import OSLog

@MainActor
final class LocalServerManager: ObservableObject {
    enum Status: Equatable {
        case idle
        case checking
        case starting
        case restarting
        case running(external: Bool)
        case unmanaged
        case failed(String)

        var text: String {
            switch self {
            case .idle:
                return "未启动"
            case .checking:
                return "检测中"
            case .starting:
                return "启动中"
            case .restarting:
                return "更新服务中"
            case .running(let external):
                return external ? "已连接已有服务" : "已由 App 启动"
            case .unmanaged:
                return "使用外部服务器"
            case .failed(let message):
                return "启动失败：\(message)"
            }
        }
    }

    /// The minimum server `api_revision` this client build needs. A reachable but
    /// older local server (e.g. a process left running across a `git pull`) is
    /// auto-restarted from the repo so the UI never talks to a stale backend.
    static let requiredAPIRevision = 1

    @Published private(set) var status: Status = .idle
    private let logger = Logger(subsystem: "com.autumn.desktop", category: "LocalServer")

    var statusText: String {
        status.text
    }

    #if os(macOS)
    private var process: Process?

    func startIfNeeded(serverURL rawValue: String) async {
        logger.info("Local server startup check for \(rawValue, privacy: .private)")
        guard let serverURL = URL(string: rawValue) else {
            logger.error("Local server startup skipped: invalid server URL")
            status = .failed("服务器 URL 无效")
            return
        }
        guard Self.canAutoStart(serverURL) else {
            logger.info("Local server startup skipped: URL is not local HTTP")
            status = .unmanaged
            return
        }
        if process?.isRunning == true {
            logger.info("Local server startup skipped: managed process is already running")
            return
        }

        status = .checking
        if await isHealthy(serverURL) {
            let revision = await serverAPIRevision(serverURL) ?? 0
            if revision >= Self.requiredAPIRevision {
                logger.info("Local server startup skipped: existing server is healthy (api_revision \(revision))")
                status = .running(external: true)
                return
            }
            // A reachable but stale server — restart it, but only if we can put a
            // replacement back from the repo, so we never kill the only server
            // with nothing to launch in its place.
            guard Self.repositoryRoot() != nil else {
                logger.warning("Existing server is stale (api_revision \(revision)) but no repo root to relaunch; leaving it")
                status = .running(external: true)
                return
            }
            logger.info("Existing server is stale (api_revision \(revision) < \(Self.requiredAPIRevision)); restarting")
            status = .restarting
            await Self.terminateLocalServer(onPort: serverURL.port ?? 8765)
            // Wait for the port to free before relaunching.
            for _ in 0..<12 {
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled { return }
                if !(await isHealthy(serverURL)) { break }
            }
        }

        await launch(serverURL)
    }

    /// Spawn the bundled server from the repo and wait for it to come up.
    private func launch(_ serverURL: URL) async {
        guard let repositoryRoot = Self.repositoryRoot() else {
            logger.error("Local server startup failed: repository root was not found")
            status = .failed("未找到仓库根目录")
            return
        }

        do {
            logger.info("Starting local server from \(repositoryRoot.path, privacy: .private)")
            try startServer(at: repositoryRoot, for: serverURL)
            status = .starting

            for _ in 0..<24 {
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled {
                    return
                }
                if await isHealthy(serverURL) {
                    logger.info("Local server became healthy")
                    status = .running(external: false)
                    return
                }
                if process?.isRunning == false {
                    break
                }
            }

            logger.error("Local server did not become healthy after launch")
            status = .failed("查看 build/logs/autumn_server.log")
        } catch {
            logger.error("Local server startup failed: \(error.localizedDescription, privacy: .public)")
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

    private func startServer(at repositoryRoot: URL, for serverURL: URL) throws {
        let fileManager = FileManager.default
        let logDirectory = repositoryRoot.appendingPathComponent("build/logs")
        try fileManager.createDirectory(at: logDirectory, withIntermediateDirectories: true)

        let logURL = logDirectory.appendingPathComponent("autumn_server.log")
        logger.info("Local server stdout/stderr log: \(logURL.path, privacy: .private)")
        if !fileManager.fileExists(atPath: logURL.path) {
            _ = fileManager.createFile(atPath: logURL.path, contents: nil)
        }
        let logHandle = try FileHandle(forWritingTo: logURL)
        _ = try? logHandle.seekToEnd()
        if let header = "\n--- Qcowork server launch \(Date()) ---\n".data(using: .utf8) {
            logHandle.write(header)
        }

        let process = Process()
        process.currentDirectoryURL = repositoryRoot

        let venvPython = repositoryRoot.appendingPathComponent(".venv/bin/python")
        if fileManager.isExecutableFile(atPath: venvPython.path) {
            process.executableURL = venvPython
            process.arguments = ["-m", "autumn.server"]
        } else {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["python3", "-m", "autumn.server"]
        }

        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["AUTUMN_HOST"] = Self.bindHost(for: serverURL)
        environment["AUTUMN_PORT"] = String(serverURL.port ?? 8765)
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

    private func isHealthy(_ serverURL: URL) async -> Bool {
        var request = URLRequest(url: serverURL.appendingPathComponent("health"))
        request.timeoutInterval = 1

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return http.statusCode == 200
        } catch {
            return false
        }
    }

    /// The `api_revision` a reachable server advertises on `/health`. Returns 0
    /// for an older server that doesn't send the field, and nil on transport
    /// failure (caller treats nil as "couldn't tell" → 0).
    private func serverAPIRevision(_ serverURL: URL) async -> Int? {
        var request = URLRequest(url: serverURL.appendingPathComponent("health"))
        request.timeoutInterval = 2
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let health = try? JSONDecoder().decode(HealthResponse.self, from: data)
        else { return nil }
        return health.apiRevision
    }

    /// SIGKILL whatever is *listening* on the local server port and wait for it
    /// to die. We target only LISTEN sockets (the server), never the client
    /// sockets the app itself holds open, so this can't take down the app.
    private static func terminateLocalServer(onPort port: Int) async {
        await Task.detached(priority: .userInitiated) {
            for pid in LocalServerManager.listenerPIDs(onPort: port) {
                _ = LocalServerManager.runTool("kill", ["-KILL", String(pid)])
            }
        }.value
    }

    private nonisolated static func listenerPIDs(onPort port: Int) -> [Int32] {
        guard let out = runTool("lsof", ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN", "-t"]) else {
            return []
        }
        return out
            .split(whereSeparator: { $0 == "\n" || $0 == " " })
            .compactMap { Int32($0) }
    }

    /// Run a command-line tool via `/usr/bin/env` (so PATH resolves lsof/kill)
    /// and return its stdout. Best-effort: any failure yields nil.
    @discardableResult
    private nonisolated static func runTool(_ tool: String, _ args: [String]) -> String? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = [tool] + args
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = Pipe()
        do {
            try proc.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            proc.waitUntilExit()
            return String(data: data, encoding: .utf8)
        } catch {
            return nil
        }
    }

    private static func canAutoStart(_ serverURL: URL) -> Bool {
        guard serverURL.scheme?.lowercased() == "http" else { return false }
        guard let host = serverURL.host?.lowercased() else { return false }
        return ["127.0.0.1", "localhost", "::1"].contains(host)
    }

    private static func bindHost(for serverURL: URL) -> String {
        let host = serverURL.host?.lowercased() ?? "127.0.0.1"
        return host == "localhost" ? "127.0.0.1" : host
    }

    private static func repositoryRoot() -> URL? {
        if let rawValue = Bundle.main.object(forInfoDictionaryKey: "QcoworkRepositoryRoot") as? String {
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
    func startIfNeeded(serverURL _: String) async {
        status = .unmanaged
    }

    func stop() {}
    #endif
}
