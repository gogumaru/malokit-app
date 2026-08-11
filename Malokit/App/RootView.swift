import SwiftUI

struct RootView: View {
    @State private var path: [Route] = []

    var body: some View {
        NavigationStack(path: $path) {
            HomeView(path: $path)
                .navigationDestination(for: Route.self) { route in
                    destination(for: route)
                }
        }
    }

    @ViewBuilder
    private func destination(for route: Route) -> some View {
        switch route {
        case .capture(let id):   CaptureFlowView(caseID: id, path: $path)
        case .review(let id):    ReviewView(caseID: id, path: $path)
        case .analyzing(let id): AnalyzingView(caseID: id, path: $path)
        case .result(let id):    ResultSummaryView(caseID: id, path: $path)
        case .dhc(let id):       DHCDetailView(caseID: id)
        case .ac(let id):        ACDetailView(caseID: id)
        case .teeth3D(let id):   Teeth3DView(caseID: id)
        case .settings:          ServerSettingsView()
        }
    }
}
