import SwiftUI

@main
struct MalokitApp: App {
    @State private var store = CaseStore()
    @State private var settings = ServerSettings()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .environment(settings)
                .tint(Theme.accent)
                .preferredColorScheme(.light)
        }
    }
}
