import Foundation

/// Default endpoint for the separately hosted Smartee reconstruction service.
/// DHC keeps using Malokit's own server settings; this value is used only for
/// `/health` and `/reconstruct` requests made by `SmarteeReconstructionClient`.
enum ServerReconstructor {
    static let defaultBaseURL = "http://10.67.32.116:8000"
    static let retiredDefaultBaseURLs: Set<String> = [
        "http://10.67.49.60:8000"
    ]
}
