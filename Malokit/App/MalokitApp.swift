import SwiftUI

@main
struct MalokitApp: App {
    @State private var store = CaseStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .tint(Theme.accent)
                .preferredColorScheme(.light)
        }
    }
}
