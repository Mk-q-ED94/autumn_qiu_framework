import SwiftUI

/// Soft card container used across panels.
struct AutumnCard<Content: View>: View {
    enum Emphasis {
        case standard, subtle, elevated
    }

    let emphasis: Emphasis
    let padding: CGFloat
    @ViewBuilder var content: () -> Content

    init(
        emphasis: Emphasis = .standard,
        padding: CGFloat = Autumn.spacing.md,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.emphasis = emphasis
        self.padding = padding
        self.content = content
    }

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background)
            .overlay(stroke)
            .clipShape(RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous))
    }

    @ViewBuilder
    private var background: some View {
        switch emphasis {
        case .standard:
            Autumn.colors.surfaceElevated
        case .subtle:
            Color.clear
        case .elevated:
            RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                .fill(.background)
                .autumnShadow(Autumn.shadow.elevated)
        }
    }

    private var stroke: some View {
        RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
            .strokeBorder(Color.secondary.opacity(emphasis == .subtle ? 0.08 : 0.14),
                          lineWidth: Autumn.stroke.hairline)
    }
}
