import SwiftUI

/// Centralised design tokens for AutumnDesktop.
///
/// Updating a token here propagates to every view that uses `Autumn.colors`,
/// `Autumn.typography`, etc. Views should never hard-code colors, sizes, or
/// durations — go through this module.
enum Autumn {
    enum colors {
        // Logo-derived accents: ember red, hot orange, leaf gold, and a small
        // green counterpoint from the project palette. Keep the app warm without
        // turning every surface into one flat orange theme.
        static let ember = Color(red: 0.72, green: 0.08, blue: 0.07)
        static let flame = Color(red: 0.96, green: 0.36, blue: 0.10)
        static let gold = Color(red: 1.00, green: 0.72, blue: 0.18)
        static let leaf = Color(red: 0.39, green: 0.66, blue: 0.36)
        static let teal = Color(red: 0.10, green: 0.52, blue: 0.55)

        // Brand accent. Root `.tint` also uses this token so the whole app
        // follows the same warmer logo direction.
        static let accent: Color = flame

        // Surface hierarchy (lighter → heavier emphasis).
        static let surface = Color.clear                         // page background (uses material)
        static let surfaceElevated = flame.opacity(0.075)
        static let surfaceHover = flame.opacity(0.13)
        static let surfaceActive = flame.opacity(0.19)

        // Bubble palettes (chat).
        static let userBubble = flame.opacity(0.18)
        static let userBubbleStroke = flame.opacity(0.40)
        static let assistantBubble = gold.opacity(0.10)
        static let assistantBubbleStroke = gold.opacity(0.24)

        // Status semantics.
        static let success = Color.green
        static let warning = flame
        static let danger = Color.red
        static let info = teal
        static let muted = Color.secondary

        // 4D memory / WP4 identity. One token so the brain icon, push stage,
        // mode badges and the 四维 detail card all read as the same system.
        static let memory = Color(red: 0.56, green: 0.31, blue: 0.70)

        static var brandGradient: LinearGradient {
            LinearGradient(
                colors: [ember, flame, gold],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }

        static var pageWarmth: LinearGradient {
            LinearGradient(
                colors: [
                    ember.opacity(0.13),
                    flame.opacity(0.12),
                    gold.opacity(0.08),
                    leaf.opacity(0.045),
                    Color.clear,
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }

        static var pageFoundation: LinearGradient {
            LinearGradient(
                colors: [
                    ember.opacity(0.08),
                    gold.opacity(0.045),
                    teal.opacity(0.035),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        }

        static func section(_ section: AppSection) -> Color {
            switch section {
            case .workspace: return flame
            case .memory: return memory
            case .terrs: return leaf
            case .settings: return gold
            }
        }

        static func workspace(_ name: String) -> Color {
            switch name {
            case "WP1": return accent
            case "WP2": return warning
            case "WP3": return info
            case "WP4": return memory
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

struct AutumnPageBackground: View {
    var body: some View {
        Rectangle()
            .fill(.regularMaterial)
            .overlay(Autumn.colors.pageFoundation)
            .overlay(Autumn.colors.pageWarmth)
            .ignoresSafeArea()
    }
}

struct AutumnLogoMark: View {
    var size: CGFloat = 28

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                .fill(Autumn.colors.brandGradient)
                .autumnShadow(Autumn.shadow.subtle)
            Image(systemName: "leaf.fill")
                .font(.system(size: size * 0.46, weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
    }
}
