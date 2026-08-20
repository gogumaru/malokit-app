import SwiftUI

/// A single Form row: put `AboutButton()` inside any `Section` and it opens
/// the licensing sheet on tap. Carries its own presentation state, the same
/// self-contained pattern as `ReportExportButton`, so dropping it in never
/// requires touching whatever `@State` already exists on the screen around it.
struct AboutButton: View {
    @State private var isPresented = false

    var body: some View {
        Button {
            isPresented = true
        } label: {
            HStack {
                Text("About Malokit")
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(Theme.hairline)
            }
        }
        .foregroundStyle(Theme.ink)
        .sheet(isPresented: $isPresented) {
            AboutMalokitView()
        }
    }
}
