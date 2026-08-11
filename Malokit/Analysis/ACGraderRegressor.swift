import CoreML
import UIKit

// MARK: - Prediction result

/// Result of scoring a single frontal photo (path A: full photo, no
/// segmentation). When `isScorable` is false the score is not valid and
/// must not be shown.
struct ACPrediction: Sendable {
    let isScorable: Bool
    let grade: Int                 // 1...10 after calibration and rounding
    let continuousScore: Double    // calibrated score, before rounding
    let confidence: Double         // probability of the exact grade
    let confidencePM1: Double      // probability of missing by at most 1 grade
    let distribution: [Double]     // 10 values summing to 1.0 (index 0 = grade 1)
    let oodScore: Double
    let oodThreshold: Double
    let rejectionReason: String?

    var topThree: [(grade: Int, probability: Double)] {
        distribution.enumerated().sorted { $0.element > $1.element }
            .prefix(3).map { (grade: $0.offset + 1, probability: $0.element) }
    }
}

// MARK: - Model wrapper

/// Wrapper around `ACGrader.mlpackage`, the two-output ResNet-18 model that
/// scores the IOTN aesthetic component.
///
/// Pipeline: resize to 224x224 by stretching, never cropping, into a
/// `CVPixelBuffer` -> `MLModel.prediction` (not `VNCoreMLRequest`) ->
/// (grade, vector) -> out-of-distribution score against the training
/// centroid -> reject if out of scope -> calibrate the raw grade -> round to
/// 1...10 -> derive confidence from the calibrated distribution.
///
/// ImageNet normalisation is baked into the model; do not normalise again
/// here. Ported from TeethAC_iOS, where this exact pattern is proven in
/// production.
///
/// Deliberately not named `ACGrader`: Xcode auto-generates a class called
/// `ACGrader` from `ACGrader.mlpackage`, and a hand-written type with the
/// same name would collide with it.
final class ACGraderRegressor: @unchecked Sendable {

    static let inputSize = 224
    /// Matches the Core ML model's input feature name exactly.
    static let inputName = "image"

    private let model: MLModel
    private let gradeOutputName: String
    private let vectorOutputName: String
    private let centroid: [[Float]]
    private let oodThreshold: Double
    private let residualSigma: Double
    private let calibration: [String: Any]

    init() throws {
        guard let url = Bundle.main.url(forResource: "ACGrader", withExtension: "mlmodelc")
              ?? Bundle.main.url(forResource: "ACGrader", withExtension: "mlpackage") else {
            throw ACGraderRegressorError.modelNotFound
        }
        let config = MLModelConfiguration()
        config.computeUnits = .all
        let loadedModel = try MLModel(contentsOf: url, configuration: config)

        let outputs = loadedModel.modelDescription.outputDescriptionsByName
        guard outputs.count >= 2 else { throw ACGraderRegressorError.outdatedModel }
        let sortedNames = outputs.keys.sorted()
        self.gradeOutputName = outputs.keys.contains("grade") ? "grade" : sortedNames[0]
        self.vectorOutputName = outputs.keys.contains("vektor") ? "vektor" : sortedNames[1]

        guard let input = loadedModel.modelDescription.inputDescriptionsByName[Self.inputName],
              input.type == .image else { throw ACGraderRegressorError.outdatedModel }
        self.model = loadedModel

        guard let configURL = Bundle.main.url(forResource: "ACGrader_config", withExtension: "json"),
              let parsedConfig = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        else { throw ACGraderRegressorError.configNotFound }

        guard let centroidValues = parsedConfig["centroid"] as? [[NSNumber]],
              let oodThresholdValue = parsedConfig["ood_threshold"] as? NSNumber,
              let residualSigmaValue = parsedConfig["residual_sigma"] as? NSNumber,
              let calibrationValue = parsedConfig["calibration"] as? [String: Any]
        else { throw ACGraderRegressorError.incompleteConfig }

        self.centroid = centroidValues.map { $0.map { $0.floatValue } }
        self.oodThreshold = oodThresholdValue.doubleValue
        self.residualSigma = max(residualSigmaValue.doubleValue, 1e-6)
        self.calibration = calibrationValue
    }

    func predict(image: UIImage) throws -> ACPrediction {
        guard let buffer = Self.pixelBuffer(from: image, side: Self.inputSize) else {
            throw ACGraderRegressorError.resizeFailed
        }
        let input = try MLDictionaryFeatureProvider(
            dictionary: [Self.inputName: MLFeatureValue(pixelBuffer: buffer)])
        let output = try model.prediction(from: input)

        guard let gradeFeature = output.featureValue(for: gradeOutputName),
              let vectorFeature = output.featureValue(for: vectorOutputName)?.multiArrayValue
        else { throw ACGraderRegressorError.noOutput }

        let rawScore: Double
        if let array = gradeFeature.multiArrayValue, array.count > 0 { rawScore = array[0].doubleValue }
        else { rawScore = gradeFeature.doubleValue }

        // OOD: the vector is already unit length, so cosine similarity is a dot product.
        let count = vectorFeature.count
        var vector = [Float](repeating: 0, count: count)
        for i in 0..<count { vector[i] = vectorFeature[i].floatValue }
        var highestSimilarity: Float = -1
        for c in centroid {
            let m = min(c.count, count)
            var dot: Float = 0
            for i in 0..<m { dot += c[i] * vector[i] }
            if dot > highestSimilarity { highestSimilarity = dot }
        }
        let ood = 1.0 - Double(highestSimilarity)

        if ood > oodThreshold {
            return ACPrediction(
                isScorable: false, grade: 0, continuousScore: 0,
                confidence: 0, confidencePM1: 0, distribution: [],
                oodScore: ood, oodThreshold: oodThreshold,
                rejectionReason: "Photo is out of the model's scope. Make sure it's a frontal "
                                + "intraoral photo, retractor in place, teeth in occlusion.")
        }

        let calibrated = calibrateScore(rawScore)
        let grade = min(10, max(1, Int(calibrated.rounded())))
        let distribution = gradeDistribution(calibrated)
        let confidencePM1 = ((grade - 1)...(grade + 1)).filter { $0 >= 1 && $0 <= 10 }
            .reduce(0.0) { $0 + distribution[$1 - 1] }

        return ACPrediction(
            isScorable: true, grade: grade, continuousScore: calibrated,
            confidence: distribution[grade - 1], confidencePM1: confidencePM1,
            distribution: distribution, oodScore: ood, oodThreshold: oodThreshold,
            rejectionReason: nil)
    }

    private func calibrateScore(_ raw: Double) -> Double {
        guard let type = calibration["type"] as? String else { return raw }
        if type == "linear",
           let m0 = (calibration["m0"] as? NSNumber)?.doubleValue,
           let s0 = (calibration["s0"] as? NSNumber)?.doubleValue,
           let m1 = (calibration["m1"] as? NSNumber)?.doubleValue,
           let s1 = (calibration["s1"] as? NSNumber)?.doubleValue, s0 != 0 {
            return m1 + (raw - m0) * (s1 / s0)
        }
        if type == "isotonic",
           let xValues = calibration["x"] as? [NSNumber], let yValues = calibration["y"] as? [NSNumber],
           xValues.count == yValues.count, xValues.count >= 2 {
            let xs = xValues.map { $0.doubleValue }, ys = yValues.map { $0.doubleValue }
            if raw <= xs[0] { return ys[0] }
            if raw >= xs[xs.count - 1] { return ys[ys.count - 1] }
            var lo = 0, hi = xs.count - 1
            while hi - lo > 1 {
                let mid = (lo + hi) / 2
                if xs[mid] <= raw { lo = mid } else { hi = mid }
            }
            let width = xs[hi] - xs[lo]
            guard width > 0 else { return ys[lo] }
            return ys[lo] + (raw - xs[lo]) / width * (ys[hi] - ys[lo])
        }
        return raw
    }

    private func gradeDistribution(_ score: Double) -> [Double] {
        let weights = (1...10).map { grade -> Double in
            let z = (Double(grade) - score) / residualSigma
            return exp(-0.5 * z * z)
        }
        let total = weights.reduce(0, +)
        return total > 0 ? weights.map { $0 / total } : [Double](repeating: 0.1, count: 10)
    }

    /// Resizes by stretching to a square, matching the training pipeline
    /// exactly. Deliberately does not use `Preprocessor.squarePatch`, which
    /// centre-crops instead of stretching.
    static func pixelBuffer(from image: UIImage, side: Int) -> CVPixelBuffer? {
        let upright = Preprocessor.upright(image)
        guard let cg = upright.cgImage else { return nil }
        let attributes: CFDictionary = [
            kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true,
            kCVPixelBufferIOSurfacePropertiesKey: [:] as CFDictionary] as CFDictionary
        var pixelBuffer: CVPixelBuffer?
        guard CVPixelBufferCreate(kCFAllocatorDefault, side, side,
                                  kCVPixelFormatType_32BGRA, attributes, &pixelBuffer) == kCVReturnSuccess,
              let buffer = pixelBuffer else { return nil }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer), width: side, height: side,
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else { return nil }
        context.interpolationQuality = .high
        context.draw(cg, in: CGRect(x: 0, y: 0, width: side, height: side))   // stretch
        return buffer
    }

    enum ACGraderRegressorError: LocalizedError {
        case modelNotFound, outdatedModel, noOutput, resizeFailed
        case configNotFound, incompleteConfig

        var errorDescription: String? {
            switch self {
            case .modelNotFound: return "ACGrader.mlpackage is not in the app bundle. Add it to the Malokit target."
            case .outdatedModel: return "The bundled model is an older version (MultiArray input or a single output). Re-run notebook 10 section 12 and copy the new ACGrader.mlpackage."
            case .noOutput: return "The model did not return the expected outputs."
            case .resizeFailed: return "Could not prepare the 224x224 image."
            case .configNotFound: return "ACGrader_config.json is not in the app bundle."
            case .incompleteConfig: return "ACGrader_config.json is incomplete (centroid, ood_threshold, residual_sigma, calibration). Re-run notebook 10 section 12."
            }
        }
    }
}
