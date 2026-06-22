import SwiftUI

/// Soft card container used across panels.
struct QcoworkCard<Content: View>: View {
    enum Emphasis {
        case standard, subtle, elevated
    }

    let emphasis: Emphasis
    let padding: CGFloat
    @ViewBuilder var content: () -> Content

    init(
        emphasis: Emphasis = .standard,
        padding: CGFloat = Qcowork.spacing.md,
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
            .clipShape(RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous))
    }

    @ViewBuilder
    private var background: some View {
        switch emphasis {
        case .standard:
            Qcowork.colors.surfaceElevated
        case .subtle:
            Color.clear
        case .elevated:
            RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
                .fill(.background)
                .qcoworkShadow(Qcowork.shadow.elevated)
        }
    }

    private var stroke: some View {
        RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
            .strokeBorder(Color.secondary.opacity(emphasis == .subtle ? 0.08 : 0.14),
                          lineWidth: Qcowork.stroke.hairline)
    }
}
