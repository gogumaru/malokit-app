import SwiftUI
import UIKit

/// Thin wrapper around UIActivityViewController, the system share sheet.
///
/// SwiftUI's ShareLink needs its item ready at view-build time. The report
/// PDF is generated on demand, so this presents once the file actually
/// exists rather than requiring the item up front.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
