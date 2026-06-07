import Foundation
import SwiftUI

/// A named workspace that groups conversations and carries optional
/// system-prompt instructions threaded through to A1/A2/A3.
struct Project: Identifiable, Codable, Equatable {
    let id: UUID
    var name: String
    var instructions: String
    var colorTag: String          // one of ProjectPalette.allTags
    let createdAt: Date
    var updatedAt: Date

    init(
        id: UUID = UUID(),
        name: String = "新项目",
        instructions: String = "",
        colorTag: String = ProjectPalette.allTags.first ?? "leaf",
        createdAt: Date = Date(),
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.instructions = instructions
        self.colorTag = colorTag
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    var trimmedInstructions: String {
        instructions.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

/// Visual identity palette for project tags. Stable string keys keep
/// persisted projects portable across colour scheme changes.
enum ProjectPalette {
    static let allTags: [String] = ["leaf", "berry", "ocean", "amber", "lavender", "moss", "rose"]

    static func color(for tag: String) -> Color {
        switch tag {
        case "leaf":     return Color(red: 0.39, green: 0.66, blue: 0.36)
        case "berry":    return Color(red: 0.85, green: 0.36, blue: 0.50)
        case "ocean":    return Color(red: 0.31, green: 0.55, blue: 0.82)
        case "amber":    return Color(red: 0.93, green: 0.66, blue: 0.20)
        case "lavender": return Color(red: 0.58, green: 0.51, blue: 0.82)
        case "moss":     return Color(red: 0.45, green: 0.55, blue: 0.34)
        case "rose":     return Color(red: 0.92, green: 0.49, blue: 0.55)
        default:         return Color.accentColor
        }
    }

    static func icon(for tag: String) -> String {
        switch tag {
        case "leaf":     return "leaf.fill"
        case "berry":    return "circle.hexagongrid.fill"
        case "ocean":    return "drop.fill"
        case "amber":    return "flame.fill"
        case "lavender": return "moon.stars.fill"
        case "moss":     return "tree.fill"
        case "rose":     return "heart.fill"
        default:         return "folder.fill"
        }
    }
}
