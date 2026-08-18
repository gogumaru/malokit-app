import Foundation

/// Every push destination in the app. Kept as one enum so the navigation
/// graph stays readable in a single place instead of scattered across views.
enum Route: Hashable {
    case capture(UUID)
    case review(UUID)
    case analyzing(UUID)
    case result(UUID)
    case dhc(UUID)
    case ac(UUID)
    case teeth3D(UUID)
    case settings
}
