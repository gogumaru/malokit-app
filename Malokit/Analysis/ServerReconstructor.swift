import Foundation

/// Default endpoint for the separately hosted Smartee reconstruction service.
/// DHC keeps using Malokit's own server settings; this value is used only for
/// `/health` and `/reconstruct` requests made by `SmarteeReconstructionClient`.
enum ServerReconstructor {
    static let defaultBaseURL = "http://10.67.32.141:8000"

    /// Addresses that used to be the default. A device that ran an older build
    /// has one of these saved in UserDefaults, where it would win over the new
    /// default forever. Listing the old value here lets the new default take
    /// over, so nobody has to know to go clear the field by hand in Settings.
    /// Never put the current default in this set.
    static let retiredDefaultBaseURLs: Set<String> = [
        "http://172.20.10.2:8000",
        "http://10.67.49.60:8000",
        "http://10.67.32.116:8000"
    ]
}
