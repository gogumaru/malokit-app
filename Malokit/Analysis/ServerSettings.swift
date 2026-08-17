import Foundation
import Observation

/// Where the DHC pipeline server lives, and how to reach it.
///
/// Kept in UserDefaults rather than hardcoded because the server address
/// changes constantly during research: a laptop on the lab wifi today, a
/// different IP tomorrow. Baking a URL into the binary would mean a rebuild
/// every time someone's DHCP lease changes.
@Observable
final class ServerSettings {

    /// Example: http://192.168.1.24:8000
    var baseURL: String {
        didSet { defaults.set(baseURL, forKey: Keys.baseURL) }
    }

    /// Sent as `X-API-Key` when non-empty. The server does not require it yet,
    /// but the field exists now so adding auth later needs no app update.
    var apiKey: String {
        didSet { defaults.set(apiKey, forKey: Keys.apiKey) }
    }

    /// When false the app uses MockEngine and never touches the network.
    var useRemote: Bool {
        didSet { defaults.set(useRemote, forKey: Keys.useRemote) }
    }

    /// Separate local Smartee service; never reused for DHC requests.
    var reconstructionBaseURL: String {
        didSet { defaults.set(reconstructionBaseURL, forKey: Keys.reconstructionBaseURL) }
    }

    private let defaults = UserDefaults.standard

    private enum Keys {
        static let baseURL = "server.baseURL"
        static let apiKey = "server.apiKey"
        static let useRemote = "server.useRemote"
        static let reconstructionBaseURL = "server.reconstructionBaseURL"
    }

    init() {
        baseURL = defaults.string(forKey: Keys.baseURL) ?? ""
        apiKey = defaults.string(forKey: Keys.apiKey) ?? ""
        useRemote = defaults.bool(forKey: Keys.useRemote)
        let savedReconstructionURL = defaults.string(forKey: Keys.reconstructionBaseURL).map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let savedReconstructionURL,
           !savedReconstructionURL.isEmpty,
           !ServerReconstructor.retiredDefaultBaseURLs.contains(savedReconstructionURL) {
            reconstructionBaseURL = savedReconstructionURL
        } else {
            reconstructionBaseURL = ServerReconstructor.defaultBaseURL
        }
    }

    var isConfigured: Bool {
        URL(string: baseURL.trimmingCharacters(in: .whitespaces)) != nil && !baseURL.isEmpty
    }

    func url(path: String) -> URL? {
        let trimmed = baseURL.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return URL(string: trimmed + path)
    }

    var isReconstructionConfigured: Bool {
        let value = reconstructionBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: value),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme) else {
            return false
        }
        return url.host != nil
    }

    func reconstructionURL(path: String) -> URL? {
        let trimmed = reconstructionBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard isReconstructionConfigured else { return nil }
        return URL(string: trimmed + path)
    }

    /// Builds the engine the pipeline should use, based on the current setting.
    /// This is the single place that decides mock versus real DHC.
    ///
    /// AC is a separate, on-device pipeline (`ACCoreMLEngine`) and always
    /// runs regardless of this choice, so switching DHC between mock and the
    /// real server never turns off the real aesthetic component score.
    func makeEngine() -> AnalysisEngine {
        let dhcSource: AnalysisEngine = (useRemote && isConfigured) ? RemoteEngine(settings: self) : MockEngine()
        return ACCoreMLEngine(fallback: dhcSource)
    }

    func makeReconstructor() -> any ReconstructionClient {
        SmarteeReconstructionClient(settings: self)
    }
}
