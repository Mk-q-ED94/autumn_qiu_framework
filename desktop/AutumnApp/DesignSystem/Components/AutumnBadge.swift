import SwiftUI

/// Compact pill used for tags, status, route labels.
struct AutumnBadge: View {
    enum Tone {
        case neutral, accent, success, warning, danger, info

        var foreground: Color {
            switch self {
            case .neutral: return .secondary
            case .accent: return .accentColor
            case .success: return Autumn.colors.success
            case .warning: return Autumn.colors.warning
            case .danger: return Autumn.colors.danger
            case .info: return Autumn.colors.info
            }
        }

        var background: Color {
            foreground.opacity(0.14)
        }
    }

    let text: String
    let icon: String?
    let tone: Tone

    init(_ text: String, icon: String? = nil, tone: Tone = .neutral) {
        self.text = text
        self.icon = icon
        self.tone = tone
    }

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            if let icon {
                Image(systemName: icon)
                    .font(.caption2.weight(.semibold))
            }
            Text(text)
                .font(Autumn.typography.captionStrong)
                .lineLimit(1)
        }
        .padding(.horizontal, Autumn.spacing.sm)
        .padding(.vertical, 3)
        .foregroundStyle(tone.foreground)
        .background(tone.background, in: Capsule(style: .continuous))
    }
}
