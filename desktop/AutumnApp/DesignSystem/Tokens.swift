import SwiftUI

/// Centralised design tokens for AutumnDesktop.
///
/// Updating a token here propagates to every view that uses `Autumn.colors`,
/// `Autumn.typography`, etc. Views should never hard-code colors, sizes, or
/// durations — go through this module.
///
/// Design language — "Paper & Clay". A calm, neutral canvas (the way ChatGPT
/// and Codex keep surfaces quiet) warmed by a single restrained clay/terracotta
/// accent (the way Claude carries its identity through one warm tone rather than
/// a rainbow). Hairline borders do the structural work; shadows stay almost
/// invisible. Typography is clean system sans, not rounded.
enum Autumn {
    enum colors {
        // ── brand spine ──────────────────────────────────────────────────────
        // One warm accent — clay/terracotta — carries the whole identity. The
        // remaining hues are desaturated companions used only for semantic
        // status and the four workspace identities, never as decoration.
        static let clay = Color(red: 0.80, green: 0.40, blue: 0.27)   // primary accent
        static let claydeep = Color(red: 0.61, green: 0.27, blue: 0.18) // gradient anchor
        static let sand = Color(red: 0.76, green: 0.62, blue: 0.45)   // soft warm neutral
        static let sage = Color(red: 0.44, green: 0.56, blue: 0.45)   // muted green
        static let slate = Color(red: 0.32, green: 0.48, blue: 0.52)  // muted blue-green

        // Back-compat aliases — the rest of the app refers to these names. They
        // now point at the calmer Paper & Clay palette rather than the old
        // ember/flame/gold ramp, so every view restyles without code changes.
        static let ember = claydeep
        static let flame = clay
        static let gold = sand
        static let leaf = sage
        static let teal = slate

        // Brand accent. Root `.tint` also uses this token so the whole app
        // follows the same single-accent direction.
        static let accent: Color = clay

        // Surface hierarchy (lighter → heavier emphasis). Neutral and
        // theme-adaptive — built from `primary` so light and dark both stay
        // quiet, the way a modern assistant canvas does.
        static let surface = Color.clear                         // page background (uses material)
        static let surfaceElevated = Color.primary.opacity(0.040)
        static let surfaceHover = Color.primary.opacity(0.070)
        static let surfaceActive = Color.primary.opacity(0.105)

        // Bubble palettes (chat). User turns carry a hint of the clay accent;
        // assistant turns stay neutral and near-borderless.
        static let userBubble = clay.opacity(0.12)
        static let userBubbleStroke = clay.opacity(0.30)
        static let assistantBubble = Color.primary.opacity(0.035)
        static let assistantBubbleStroke = Color.primary.opacity(0.085)

        // Status semantics — calmer, desaturated so they sit on paper without
        // shouting. `warning` is its own amber, distinct from the clay accent.
        static let success = Color(red: 0.36, green: 0.60, blue: 0.42)
        static let warning = Color(red: 0.84, green: 0.58, blue: 0.26)
        static let danger = Color(red: 0.80, green: 0.33, blue: 0.30)
        static let info = slate
        static let muted = Color.secondary

        // 4D memory / WP4 identity. One token so the brain icon, push stage,
        // mode badges and the 四维 detail card all read as the same system.
        static let memory = Color(red: 0.51, green: 0.41, blue: 0.62)

        static var brandGradient: LinearGradient {
            LinearGradient(
                colors: [claydeep, clay],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }

        // Page washes — barely-there warmth over the material canvas, so the app
        // reads as warm paper rather than a tinted orange panel.
        static var pageWarmth: LinearGradient {
            LinearGradient(
                colors: [
                    clay.opacity(0.045),
                    sand.opacity(0.025),
                    Color.clear,
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }

        static var pageFoundation: LinearGradient {
            LinearGradient(
                colors: [
                    clay.opacity(0.022),
                    Color.clear,
                    slate.opacity(0.015),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        }

        static func section(_ section: AppSection) -> Color {
            switch section {
            case .workspace: return clay
            case .memory: return memory
            case .terrs: return sage
            }
        }

        static func workspace(_ name: String) -> Color {
            switch name {
            case "WP1": return clay
            case "WP2": return warning
            case "WP3": return slate
            case "WP4": return memory
            default:    return muted
            }
        }
    }

    enum typography {
        // Clean system sans (SF) — no rounded design — to match the restrained,
        // editorial feel of modern assistant clients.
        static let display = Font.system(.largeTitle, design: .default).weight(.semibold)
        static let title = Font.system(.title2, design: .default).weight(.semibold)
        static let headline = Font.system(.headline, design: .default)
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
        static let sm: CGFloat = 7
        static let md: CGFloat = 11
        static let lg: CGFloat = 16
        static let xl: CGFloat = 22
        static let pill: CGFloat = 999
    }

    enum stroke {
        static let hairline: CGFloat = 0.5
        static let thin: CGFloat = 1
        static let medium: CGFloat = 1.5
    }

    enum shadow {
        // Flattened — the new language leans on hairline borders, not shadows.
        static let subtle = ShadowStyle(color: .black.opacity(0.04), radius: 3, y: 1)
        static let elevated = ShadowStyle(color: .black.opacity(0.07), radius: 10, y: 3)
        static let floating = ShadowStyle(color: .black.opacity(0.12), radius: 20, y: 7)
    }

    enum motion {
        static let snappy = Animation.spring(response: 0.28, dampingFraction: 0.86)
        static let smooth = Animation.easeOut(duration: 0.24)
        static let soft = Animation.easeInOut(duration: 0.18)
        static let pulse = Animation.easeInOut(duration: 1.1).repeatForever(autoreverses: true)
    }

    enum sizing {
        static let bubbleMaxWidth: CGFloat = 580
        static let inspectorWidth: CGFloat = 296
        static let sidebarWidth: CGFloat = 236
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
            RoundedRectangle(cornerRadius: size * 0.30, style: .continuous)
                .fill(Autumn.colors.brandGradient)
                .autumnShadow(Autumn.shadow.subtle)
            Image(systemName: "leaf.fill")
                .font(.system(size: size * 0.44, weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
    }
}
