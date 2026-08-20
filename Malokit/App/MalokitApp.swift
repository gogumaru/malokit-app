import SwiftUI

@main
struct MalokitApp: App {
    @State private var store = CaseStore()
    @State private var settings = ServerSettings()
    @State private var reconstructionService = ReconstructionService()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .environment(settings)
                .environment(reconstructionService)
                .tint(Theme.accent)
                .preferredColorScheme(.light)
        }
    }
}
