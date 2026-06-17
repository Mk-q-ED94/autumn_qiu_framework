import SwiftUI

/// ButtonStyle that adds a subtle 0.97× scale on press, used by all Autumn
/// custom buttons so keyboard and pointer interactions feel the same.
struct AutumnPressButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0, anchor: .center)
            .animation(Autumn.motion.snappy, value: configuration.isPressed)
    }
}

/// Primary action button with gradient fill, hover brightness, and press scale.
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
                Autumn.colors.brandGradient,
                in: RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
            )
            .autumnShadow(Autumn.shadow.subtle)
            .brightness(isHovering && !isLoading ? 0.05 : 0)
        }
        .buttonStyle(AutumnPressButtonStyle())
        .disabled(isLoading)
        .onHover { h in withAnimation(Autumn.motion.soft) { isHovering = h } }
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
        .buttonStyle(AutumnPressButtonStyle())
        .onHover { hovering in
            withAnimation(Autumn.motion.soft) { isHovering = hovering }
        }
    }
}
