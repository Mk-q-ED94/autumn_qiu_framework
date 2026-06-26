import SwiftUI

/// Custom sidebar navigation item — replaces the stock List row + tag pattern.
///
/// Selected: section-accent tinted background + accent-coloured text/icon.
/// Hovered:  `surfaceHover` fill, neutral text.
/// Default:  transparent.
struct QcoworkNavItem: View {
    let section: AppSection
    let isSelected: Bool
    let action: () -> Void

    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: Qcowork.spacing.sm) {
                Image(systemName: section.systemImage)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(iconColor)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 1) {
                    Text(section.title)
                        .font(Qcowork.typography.bodyMedium)
                        .foregroundStyle(labelColor)
                    Text(section.subtitle)
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(sublabelColor)
                }
                Spacer()
            }
            .padding(.horizontal, Qcowork.spacing.md)
            .padding(.vertical, Qcowork.spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                    .fill(backgroundFill)
            )
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(Qcowork.motion.soft) { isHovered = h } }
    }

    private var accent: Color { Qcowork.colors.section(section) }

    private var backgroundFill: Color {
        if isSelected { return accent.opacity(0.13) }
        if isHovered  { return Qcowork.colors.surfaceHover }
        return .clear
    }

    private var iconColor: Color  { isSelected ? accent : .secondary }
    private var labelColor: Color { isSelected ? accent : .primary }
    private var sublabelColor: Color { isSelected ? accent.opacity(0.7) : .secondary }
}
