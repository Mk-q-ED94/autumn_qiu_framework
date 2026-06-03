import SwiftUI
#if os(macOS)
import AppKit
#endif

@main
struct AutumnApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(AutumnAppDelegate.self) private var appDelegate
    #endif

    @StateObject private var settings: AppSettings
    @StateObject private var localServer: LocalServerManager

    init() {
        let settings = AppSettings()
        let localServer = LocalServerManager()
        _settings = StateObject(wrappedValue: settings)
        _localServer = StateObject(wrappedValue: localServer)

        #if os(macOS)
        AutumnAppDelegate.settings = settings
        AutumnAppDelegate.localServer = localServer
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(localServer)
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        #endif
    }
}
