import SceneKit
import SwiftUI
import UIKit

/// A stand in mesh so the 3D screen is usable before reconstruction exists.
///
/// Scene units are millimetres, which is the same unit the measuring tool
/// reports, so swapping in a real mesh later needs no rescaling as long as
/// the reconstruction also exports in millimetres.
enum PlaceholderArch {

    struct Options {
        var showUpper = true
        var showLower = true
    }

    static func scene(_ options: Options = Options()) -> SCNScene {
        let scene = SCNScene()
        scene.background.contents = UIColor(Theme.surface)

        if options.showUpper {
            scene.rootNode.addChildNode(arch(isUpper: true))
        }
        if options.showLower {
            scene.rootNode.addChildNode(arch(isUpper: false))
        }

        let light = SCNNode()
        light.light = SCNLight()
        light.light?.type = .omni
        light.light?.intensity = 900
        light.position = SCNVector3(0, 60, 60)
        scene.rootNode.addChildNode(light)

        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.intensity = 380
        scene.rootNode.addChildNode(ambient)

        return scene
    }

    /// 14 teeth laid out on a half ellipse, roughly adult arch dimensions:
    /// about 52 mm wide and 40 mm deep.
    private static func arch(isUpper: Bool) -> SCNNode {
        let node = SCNNode()
        node.name = isUpper ? "upperArch" : "lowerArch"

        let count = 14
        let halfWidth: Float = 26
        let depth: Float = 20
        let y: Float = isUpper ? 6 : -6

        for index in 0..<count {
            let t = Float(index) / Float(count - 1)
            let angle = Float.pi * t
            let x = -cos(angle) * halfWidth
            let z = -sin(angle) * depth

            // Molars are wider and taller than incisors.
            let central = abs(t - 0.5) < 0.18
            let width: CGFloat = central ? 5.5 : 8.0
            let height: CGFloat = central ? 9.5 : 7.5
            let thickness: CGFloat = central ? 5.0 : 8.5

            let box = SCNBox(
                width: width, height: height, length: thickness,
                chamferRadius: central ? 1.0 : 2.2
            )
            box.firstMaterial?.diffuse.contents = UIColor(white: 0.94, alpha: 1)
            box.firstMaterial?.roughness.contents = 0.35
            box.firstMaterial?.lightingModel = .physicallyBased

            let tooth = SCNNode(geometry: box)
            tooth.position = SCNVector3(x, y, z)
            tooth.eulerAngles = SCNVector3(0, -angle + .pi / 2, 0)
            tooth.name = "tooth"
            node.addChildNode(tooth)
        }

        // Gingiva ring, purely so the arch reads as an arch and not as a row
        // of floating blocks.
        let gum = SCNTorus(ringRadius: CGFloat(halfWidth), pipeRadius: 2.5)
        gum.firstMaterial?.diffuse.contents = UIColor(red: 0.86, green: 0.55, blue: 0.55, alpha: 1)
        let gumNode = SCNNode(geometry: gum)
        gumNode.position = SCNVector3(0, y - Float(6), -depth / 2)
        gumNode.scale = SCNVector3(1, 1, depth / halfWidth)
        gumNode.opacity = 0.85
        node.addChildNode(gumNode)

        return node
    }
}
