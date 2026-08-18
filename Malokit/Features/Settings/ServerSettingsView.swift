import SwiftUI

struct ServerSettingsView: View {
    @Environment(ServerSettings.self) private var settings
    @State private var health: HealthReport?
    @State private var isChecking = false
    @State private var reconHealth: HealthReport?
    @State private var isCheckingRecon = false

    var body: some View {
        @Bindable var settings = settings

        Form {
            Section {
                Toggle("Use the DHC server", isOn: $settings.useRemote)
            } footer: {
                Text("Off means the app runs on built-in sample data and never touches the network.")
            }

            Section("DHC server address") {
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

            Section {
                TextField(ServerReconstructor.defaultBaseURL, text: $settings.reconstructionBaseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .font(.system(.body, design: .monospaced))

                Button {
                    Task { await checkReconstruction() }
                } label: {
                    HStack {
                        Text("Test connection")
                        Spacer()
                        if isCheckingRecon { ProgressView().controlSize(.small) }
                    }
                }
                .disabled(!settings.isReconstructionConfigured || isCheckingRecon)

                if let reconHealth {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: reconHealth.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        Text(reconHealth.message)
                    }
                    .font(.caption)
                    .foregroundStyle(reconHealth.ok ? Theme.calm : Theme.urgent)
                }
            } header: {
                Text("3D model server")
            } footer: {
                Text("Separate Smartee service used only for the 3D reconstruction. Checks /health.")
            }

            Section("Notes") {
                labelled("Photos sent", "5 per case, JPEG")
                labelled("Produced here", "DHC and Angle")
                labelled("Elsewhere", "AC on device, 3D on the model server")
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

    private func checkReconstruction() async {
        isCheckingRecon = true
        reconHealth = nil
        reconHealth = await SmarteeReconstructionClient.checkHealth(settings: settings)
        isCheckingRecon = false
    }
}
