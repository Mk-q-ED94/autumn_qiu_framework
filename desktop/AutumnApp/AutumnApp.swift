import SwiftUI

@main
struct AutumnApp: App {
    @StateObject private var settings = AppSettings()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        #endif
    }
}
