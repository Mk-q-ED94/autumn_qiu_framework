import SwiftUI

/// Centralised design tokens for AutumnDesktop.
///
/// Updating a token here propagates to every view that uses `Autumn.colors`,
/// `Autumn.typography`, etc. Views should never hard-code colors, sizes, or
/// durations — go through this module.
enum Autumn {
    enum colors {
        // Brand accent: follows the system tint (set on the root via `.tint`),
        // so adding an `AccentColor` color set to an Asset Catalog overrides
        // every use site in one place.
        static let accent: Color = .accentColor

        // Surface hierarchy (lighter → heavier emphasis).
        static let surface = Color.clear                         // page background (uses material)
        static let surfaceElevated = Color.secondary.opacity(0.06)
        static let surfaceHover = Color.secondary.opacity(0.10)
        static let surfaceActive = Color.secondary.opacity(0.16)

        // Bubble palettes (chat).
        static let userBubble = Color.accentColor.opacity(0.16)
        static let userBubbleStroke = Color.accentColor.opacity(0.32)
        static let assistantBubble = Color.secondary.opacity(0.08)
        static let assistantBubbleStroke = Color.secondary.opacity(0.18)

        // Status semantics.
        static let success = Color.green
        static let warning = Color.orange
        static let danger = Color.red
        static let info = Color.blue
        static let muted = Color.secondary

        static func workspace(_ name: String) -> Color {
            switch name {
            case "WP1": return accent
            case "WP2": return warning
            case "WP3": return info
            default:    return muted
            }
        }
    }

    enum typography {
        static let display = Font.system(.largeTitle, design: .rounded).weight(.semibold)
        static let title = Font.system(.title2, design: .rounded).weight(.semibold)
        static let headline = Font.system(.headline, design: .rounded)
        static let body = Font.system(.body, design: .default)
        static let bodyMedium = Font.system(.body, design: .default).weight(.medium)
        static let callout = Font.system(.callout, design: .default)
        static let caption = Font.system(.caption, design: .default)
        static let captionMedium = Font.system(.caption, design: .default).weight(.medium)
        static let captionStrong = Font.system(.caption, design: .default).weight(.semibold)
        static let mono = Font.system(.callout, design: .monospaced)
    }

    enum spacing {
        static let micro: CGFloat = 2
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 32
    }

    enum radius {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 6
        static let md: CGFloat = 10
        static let lg: CGFloat = 14
        static let xl: CGFloat = 20
        static let pill: CGFloat = 999
    }

    enum stroke {
        static let hairline: CGFloat = 0.5
        static let thin: CGFloat = 1
        static let medium: CGFloat = 1.5
    }

    enum shadow {
        static let subtle = ShadowStyle(color: .black.opacity(0.05), radius: 4, y: 1)
        static let elevated = ShadowStyle(color: .black.opacity(0.10), radius: 12, y: 4)
        static let floating = ShadowStyle(color: .black.opacity(0.16), radius: 24, y: 8)
    }

    enum motion {
        static let snappy = Animation.spring(response: 0.28, dampingFraction: 0.86)
        static let smooth = Animation.easeOut(duration: 0.24)
        static let soft = Animation.easeInOut(duration: 0.18)
        static let pulse = Animation.easeInOut(duration: 1.1).repeatForever(autoreverses: true)
    }

    enum sizing {
        static let bubbleMaxWidth: CGFloat = 560
        static let inspectorWidth: CGFloat = 296
        static let sidebarWidth: CGFloat = 232
        static let composerMinHeight: CGFloat = 44
    }

    enum format {
        static func duration(_ ms: Double) -> String {
            ms >= 1000 ? String(format: "%.1fs", ms / 1000) : "\(Int(ms.rounded()))ms"
        }

        static func tokens(_ count: Int) -> String {
            count >= 1000 ? String(format: "%.1fk", Double(count) / 1000) : "\(count)"
        }

        static func cost(_ usd: Double) -> String {
            String(format: "$%.4f", usd)
        }
    }
}

struct ShadowStyle: Equatable {
    let color: Color
    let radius: CGFloat
    let x: CGFloat
    let y: CGFloat

    init(color: Color, radius: CGFloat, x: CGFloat = 0, y: CGFloat = 0) {
        self.color = color
        self.radius = radius
        self.x = x
        self.y = y
    }
}

extension View {
    func autumnShadow(_ style: ShadowStyle) -> some View {
        shadow(color: style.color, radius: style.radius, x: style.x, y: style.y)
    }
}
