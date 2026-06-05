import SwiftUI

/// Primary action button with subtle press feedback.
struct AutumnPrimaryButton<Label: View>: View {
    enum Size {
        case small, regular, large

        var verticalPadding: CGFloat {
            switch self {
            case .small: return 5
            case .regular: return 8
            case .large: return 12
            }
        }

        var horizontalPadding: CGFloat {
            switch self {
            case .small: return 10
            case .regular: return 14
            case .large: return 18
            }
        }

        var font: Font {
            switch self {
            case .small: return Autumn.typography.captionStrong
            case .regular: return Autumn.typography.bodyMedium
            case .large: return Autumn.typography.headline
            }
        }
    }

    let size: Size
    let isLoading: Bool
    let action: () -> Void
    @ViewBuilder var label: () -> Label

    init(
        size: Size = .regular,
        isLoading: Bool = false,
        action: @escaping () -> Void,
        @ViewBuilder label: @escaping () -> Label
    ) {
        self.size = size
        self.isLoading = isLoading
        self.action = action
        self.label = label
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: Autumn.spacing.sm) {
                if isLoading {
                    ProgressView().controlSize(.small)
                } else {
                    label()
                }
            }
            .font(size.font)
            .foregroundStyle(.white)
            .padding(.horizontal, size.horizontalPadding)
            .padding(.vertical, size.verticalPadding)
            .background(
                LinearGradient(
                    colors: [Color.accentColor, Color.accentColor.opacity(0.86)],
                    startPoint: .top,
                    endPoint: .bottom
                ),
                in: RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
            )
            .autumnShadow(Autumn.shadow.subtle)
        }
        .buttonStyle(.plain)
        .disabled(isLoading)
    }
}

/// Subtle ghost button for secondary actions.
struct AutumnGhostButton<Label: View>: View {
    let action: () -> Void
    @ViewBuilder var label: () -> Label

    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            label()
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(.primary)
                .padding(.horizontal, Autumn.spacing.sm)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(isHovering ? Autumn.colors.surfaceHover : Autumn.colors.surfaceElevated)
                )
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(Autumn.motion.soft) { isHovering = hovering }
        }
    }
}
