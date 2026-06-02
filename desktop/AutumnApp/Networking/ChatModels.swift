import Foundation

struct ProcessRequest: Encodable {
    let input: String
}

struct ProcessResponse: Decodable {
    let output: String
}

struct StreamPayload: Decodable {
    let chunk: String?
    let error: String?
}

struct HealthResponse: Decodable {
    let status: String
    let configured: Bool
}
