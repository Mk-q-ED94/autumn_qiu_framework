import SwiftUI

/// ButtonStyle that adds a subtle 0.97× scale on press, used by all Qcowork
/// custom buttons so keyboard and pointer interactions feel the same.
struct QcoworkPressButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0, anchor: .center)
            .animation(Qcowork.motion.snappy, value: configuration.isPressed)
    }
}

/// Primary action button with gradient fill, hover brightness, and press scale.
struct QcoworkPrimaryButton<Label: View>: View {
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
            case .small: return Qcowork.typography.captionStrong
            case .regular: return Qcowork.typography.bodyMedium
            case .large: return Qcowork.typography.headline
            }
        }
    }

    let size: Size
    let isLoading: Bool
    let action: () -> Void
    @ViewBuilder var label: () -> Label

    @State private var isHovering = false

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
            HStack(spacing: Qcowork.spacing.sm) {
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
                Qcowork.colors.brandGradient,
                in: RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
            )
            .qcoworkShadow(Qcowork.shadow.subtle)
            .brightness(isHovering && !isLoading ? 0.05 : 0)
        }
        .buttonStyle(QcoworkPressButtonStyle())
        .disabled(isLoading)
        .onHover { h in withAnimation(Qcowork.motion.soft) { isHovering = h } }
    }
}

/// Subtle ghost button for secondary actions.
struct QcoworkGhostButton<Label: View>: View {
    let action: () -> Void
    @ViewBuilder var label: () -> Label

    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            label()
                .font(Qcowork.typography.captionStrong)
                .foregroundStyle(.primary)
                .padding(.horizontal, Qcowork.spacing.sm)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                        .fill(isHovering ? Qcowork.colors.surfaceHover : Qcowork.colors.surfaceElevated)
                )
        }
        .buttonStyle(QcoworkPressButtonStyle())
        .onHover { hovering in
            withAnimation(Qcowork.motion.soft) { isHovering = hovering }
        }
    }
}
