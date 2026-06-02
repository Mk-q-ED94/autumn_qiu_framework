import Foundation
import SwiftUI

@MainActor
final class AppSettings: ObservableObject {
    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: Self.serverURLKey) }
    }

    @Published var routeMode: String {
        didSet { UserDefaults.standard.set(routeMode, forKey: Self.routeModeKey) }
    }

    private static let serverURLKey = "AutumnDesktop.serverURL"
    private static let routeModeKey = "AutumnDesktop.routeMode"
    private static let defaultServerURL = "http://127.0.0.1:8765"

    init() {
        self.serverURL =
            UserDefaults.standard.string(forKey: Self.serverURLKey) ?? Self.defaultServerURL
        self.routeMode = UserDefaults.standard.string(forKey: Self.routeModeKey) ?? "auto"
    }
}
