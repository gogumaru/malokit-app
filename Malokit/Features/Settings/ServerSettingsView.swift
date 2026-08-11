import SwiftUI

struct ServerSettingsView: View {
    @Environment(ServerSettings.self) private var settings
    @State private var health: HealthReport?
    @State private var isChecking = false

    var body: some View {
        @Bindable var settings = settings

        Form {
            Section {
                Toggle("Use the DHC server", isOn: $settings.useRemote)
            } footer: {
                Text("Off means the app runs on built-in sample data and never touches the network.")
            }

            Section("Server address") {
                TextField("http://192.168.1.24:8000", text: $settings.baseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .font(.system(.body, design: .monospaced))

                SecureField("API key (leave empty if not required)", text: $settings.apiKey)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            Section {
                Button {
                    Task { await check() }
                } label: {
                    HStack {
                        Text("Test connection")
                        Spacer()
                        if isChecking { ProgressView().controlSize(.small) }
                    }
                }
                .disabled(!settings.isConfigured || isChecking)

                if let health {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: health.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        Text(health.message)
                    }
                    .font(.caption)
                    .foregroundStyle(health.ok ? Theme.calm : Theme.urgent)
                }
            } footer: {
                Text("Checks /v1/health. The phone and the server must be on the same network.")
            }

            Section("Notes") {
                labelled("Photos sent", "5 per case, JPEG")
                labelled("Produced here", "DHC and Angle")
                labelled("Not produced here", "AC and 3D, separate pipelines")
            }
        }
        .navigationTitle("Server")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func labelled(_ key: String, _ value: String) -> some View {
        HStack {
            Text(key).foregroundStyle(Theme.inkSoft)
            Spacer()
            Text(value).foregroundStyle(Theme.ink)
        }
        .font(.caption)
    }

    private func check() async {
        isChecking = true
        health = nil
        health = await RemoteEngine.checkHealth(settings: settings)
        isChecking = false
    }
}
