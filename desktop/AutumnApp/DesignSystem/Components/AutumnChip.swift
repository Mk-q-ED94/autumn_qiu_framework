import SwiftUI

/// A pill-shaped chip used for route labels, status indicators, and count badges.
///
/// Sizes:
/// - `.regular` — icon at 9 pt + captionStrong text; route pills and status labels
/// - `.compact` — icon at 7 pt + monospaced 9 pt text; inline strip chips (ToolCount, Agent)
struct AutumnChip: View {
    let label: String
    let icon: String?
    let color: Color
    var size: ChipSize = .regular

    enum ChipSize { case compact, regular }

    init(_ label: String, icon: String? = nil, color: Color = Autumn.colors.muted, size: ChipSize = .regular) {
        self.label = label
        self.icon = icon
        self.color = color
        self.size = size
    }

    var body: some View {
        HStack(spacing: size == .compact ? 2 : 4) {
            if let icon {
                Image(systemName: icon)
                    .font(size == .compact
                        ? .system(size: 7, weight: .bold)
                        : .system(size: 9, weight: .bold))
            }
            Text(label)
                .font(size == .compact
                    ? .system(size: 9, weight: .semibold, design: .monospaced)
                    : Autumn.typography.captionStrong)
        }
        .foregroundStyle(color)
        .padding(.horizontal, size == .compact ? 5 : 7)
        .padding(.vertical, size == .compact ? 1 : 2)
        .background(Capsule().fill(color.opacity(0.12)))
        .overlay(Capsule().strokeBorder(color.opacity(0.28), lineWidth: 0.5))
    }
}
