import SwiftUI
#if os(macOS)
import AppKit
#endif

/// Compact, hover-revealed actions under a chat message. Currently a single
/// Copy action that confirms inline ("已复制 ✓") for ~1.5 s — the calmest
/// top-tier affordance: invisible at rest, one tap to lift the text out.
struct MessageActionBar: View {
    let text: String

    @State private var copied = false

    var body: some View {
        HStack(spacing: Qcowork.spacing.xs) {
            Button(action: copy) {
                Label(copied ? "已复制" : "复制",
                      systemImage: copied ? "checkmark" : "doc.on.doc")
                    .labelStyle(.titleAndIcon)
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(copied ? Qcowork.colors.success : .secondary)
            }
            .buttonStyle(.plain)
            .help("复制内容")
        }
    }

    private func copy() {
        #if os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
        withAnimation(Qcowork.motion.soft) { copied = true }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            withAnimation(Qcowork.motion.soft) { copied = false }
        }
    }
}
