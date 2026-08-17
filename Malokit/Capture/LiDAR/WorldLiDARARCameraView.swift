//
//  WorldLiDARARCameraView.swift
//  TeethLidar
//
//  RealityKit camera feed backed by the scanner's single ARKit session.
//

import ARKit
import RealityKit
import SwiftUI

struct WorldLiDARARCameraView: UIViewRepresentable {
    @ObservedObject var controller: WorldLiDARCaptureController

    func makeUIView(context: Context) -> ARView {
        let view = ARView(
            frame: .zero,
            cameraMode: .ar,
            automaticallyConfigureSession: false
        )
        controller.attach(session: view.session)
        controller.start()
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        guard controller.sweepState == .accumulating,
              let worldTransform = controller.sweepTeethAnchorWorldTransform else {
            context.coordinator.reticle.removeFromScene()
            return
        }
        context.coordinator.reticle.update(
            worldTransform: worldTransform,
            reached: controller.sweepTargetReached,
            in: uiView.scene
        )
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        coordinator.reticle.removeFromScene()
        uiView.session.pause()
    }

    @MainActor
    final class Coordinator {
        let reticle = Figure8ARReticle()
    }
}
