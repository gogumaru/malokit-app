//
//  Figure8ARReticle.swift
//  TeethLidar
//
//  A small RealityKit square-frame anchored in real AR space at the
//  teeth's measured position when a Figure-8 sweep begins — a fixed
//  landmark that visually stays stuck to the teeth (real AR parallax)
//  while a separate 2D ring guides movement to the next position. The
//  frame shape (rather than a filled square) keeps the tooth surface
//  underneath visible. Position is fixed once per sweep — RealityKit
//  renders its parallax at full framerate on its own — but its colour
//  still updates live from `sweepTargetReached`, matching the ring and
//  centre crosshair.
//

import RealityKit
import UIKit
import simd

@MainActor
final class Figure8ARReticle {
    private let anchor = AnchorEntity(world: matrix_identity_float4x4)
    private let edges: [ModelEntity]
    private var isAddedToScene = false
    private var isReached = false

    init() {
        let side: Float = 0.007
        let barThickness: Float = 0.0010
        let half = side / 2

        func edge(size: SIMD3<Float>, position: SIMD3<Float>) -> ModelEntity {
            let entity = ModelEntity(
                mesh: .generateBox(size: size),
                materials: [Self.material(reached: false)]
            )
            entity.position = position
            return entity
        }

        edges = [
            edge(size: SIMD3(side, barThickness, barThickness), position: SIMD3(0, half, 0)),
            edge(size: SIMD3(side, barThickness, barThickness), position: SIMD3(0, -half, 0)),
            edge(size: SIMD3(barThickness, side, barThickness), position: SIMD3(-half, 0, 0)),
            edge(size: SIMD3(barThickness, side, barThickness), position: SIMD3(half, 0, 0)),
        ]
        edges.forEach { anchor.addChild($0) }
    }

    /// Adds the reticle to `scene` on first use, (re)places it at
    /// `worldTransform`, and recolors it when `reached` changes. Cheap to
    /// call every frame — the position is normally fixed, only the color
    /// swap does any real work, and only when it actually changes.
    func update(worldTransform: simd_float4x4, reached: Bool, in scene: RealityKit.Scene) {
        if !isAddedToScene {
            scene.addAnchor(anchor)
            isAddedToScene = true
        }
        anchor.setTransformMatrix(worldTransform, relativeTo: nil)
        guard reached != isReached else { return }
        isReached = reached
        let material = Self.material(reached: reached)
        for edge in edges {
            edge.model?.materials = [material]
        }
    }

    func removeFromScene() {
        guard isAddedToScene else { return }
        anchor.removeFromParent()
        isAddedToScene = false
    }

    // Unlit, not SimpleMaterial: a lit material gets shaded/darkened by the
    // real scene's lighting, which can wash a thin marker out almost
    // completely under bright intraoral lighting. Unlit renders at flat,
    // fully-saturated color regardless of scene lighting.
    private static func material(reached: Bool) -> UnlitMaterial {
        UnlitMaterial(color: reached ? .systemGreen : .systemYellow)
    }
}
