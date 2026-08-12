import SwiftUI

/// A reusable name prompt for a case.
///
/// Kept as one component so naming a case at the start and renaming it later
/// behave identically. Two separate implementations would drift, and this is
/// the field the whole record is identified by.
struct CaseNamePrompt: ViewModifier {
    @Binding var isPresented: Bool
    let title: String
    let currentName: String
    let onSave: (String) -> Void

    @State private var draft = ""

    func body(content: Content) -> some View {
        content
            .alert(title, isPresented: $isPresented) {
                TextField("Patient name or ID", text: $draft)
                    .textInputAutocapitalization(.words)
                Button("Cancel", role: .cancel) {}
                Button("Save") { onSave(draft) }
            } message: {
                // Named cases are easier to find later, but this is medical
                // data on a shared device, so an initials-and-date style ID is
                // often the better habit than a full name.
                Text("Used to identify this case in the list. An ID works as well as a name.")
            }
            .onChange(of: isPresented) { _, showing in
                if showing { draft = currentName }
            }
    }
}

extension View {
    func caseNamePrompt(
        isPresented: Binding<Bool>,
        title: String = "Name this case",
        currentName: String = "",
        onSave: @escaping (String) -> Void
    ) -> some View {
        modifier(CaseNamePrompt(
            isPresented: isPresented,
            title: title,
            currentName: currentName,
            onSave: onSave
        ))
    }
}
