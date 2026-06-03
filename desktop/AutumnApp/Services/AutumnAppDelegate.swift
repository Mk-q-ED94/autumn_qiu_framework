import Foundation

#if os(macOS)
import AppKit
import OSLog

@MainActor
final class AutumnAppDelegate: NSObject, NSApplicationDelegate {
    static var settings: AppSettings?
    static var localServer: LocalServerManager?

    private let logger = Logger(subsystem: "com.autumn.desktop", category: "Lifecycle")

    func applicationDidFinishLaunching(_ notification: Notification) {
        logger.info("Application did finish launching")
        Task { @MainActor in
            guard let settings = Self.settings, let localServer = Self.localServer else {
                logger.error("Local server startup skipped: shared app objects are missing")
                return
            }
            await localServer.startIfNeeded(serverURL: settings.serverURL)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        logger.info("Application will terminate")
        Self.localServer?.stop()
    }
}
#endif
