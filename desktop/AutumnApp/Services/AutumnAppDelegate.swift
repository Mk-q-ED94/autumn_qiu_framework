import Foundation

#if os(macOS)
import AppKit
import OSLog

@MainActor
final class AutumnAppDelegate: NSObject, NSApplicationDelegate {
    static var settings: AppSettings?
    static var localServer: LocalServerManager?
    static var ollamaManager: OllamaManager?

    private let logger = Logger(subsystem: "com.autumn.desktop", category: "Lifecycle")

    func applicationDidFinishLaunching(_ notification: Notification) {
        logger.info("Application did finish launching")
        Task { @MainActor in
            guard
                let settings = Self.settings,
                let localServer = Self.localServer,
                let ollamaManager = Self.ollamaManager
            else {
                logger.error("Local server startup skipped: shared app objects are missing")
                return
            }
            async let serverStartup: Void = localServer.startIfNeeded(serverURL: settings.serverURL)
            async let ollamaStartup: Void = ollamaManager.startIfNeeded(
                enabled: settings.a4Enabled,
                baseURL: settings.a4BaseURL
            )
            _ = await (serverStartup, ollamaStartup)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        logger.info("Application will terminate")
        Self.ollamaManager?.stop()
        Self.localServer?.stop()
    }
}
#endif
