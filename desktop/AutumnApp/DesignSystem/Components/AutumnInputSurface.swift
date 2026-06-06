import SwiftUI

extension View {
    func autumnInputSurface(isFocused: Bool = false) -> some View {
        self
            .padding(.horizontal, Autumn.spacing.md)
            .padding(.vertical, Autumn.spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                    .fill(Autumn.colors.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                    .strokeBorder(
                        isFocused ? Color.accentColor.opacity(0.6) : Color.secondary.opacity(0.12),
                        lineWidth: isFocused ? Autumn.stroke.medium : Autumn.stroke.hairline
                    )
            )
    }
}
