import CoreML
import UIKit

// MARK: - Validation result

/// Result of checking one captured/imported photo against the slot it was
/// meant to fill. `isValid` is the single source of truth for whether the
/// photo may be attached to the case; everything else is context for the
/// rejection message or for a review-screen badge.
struct ViewValidation: Sendable {
    let isValid: Bool
    /// The view the model thinks this photo actually is. `nil` when the
    /// photo was rejected by the OOD gate (not recognisable as any of the
    /// five views at all).
    let detectedView: ToothView?
    /// Softmax probability of `detectedView`. Only meaningful when
    /// `detectedView` is non-nil.
    let confidence: Double
    let oodScore: Double
    let oodThreshold: Double
    let matchesExpected: Bool
    /// Shown to the user in place of a silent rejection.
    let rejectionReason: String?
}

// MARK: - Model wrapper

/// Wrapper around `ViewValidator.mlpackage`, the two-output ResNet-18 model
/// that classifies which of the five intraoral views a photo is, plus an
/// out-of-distribution gate for photos that are not any of the five at all.
///
/// Pipeline: resize to 224x224 by stretching (same convention as
/// `ACGraderRegressor`) into a `CVPixelBuffer` -> `MLModel.prediction` ->
/// (scores, vector) -> OOD gate against the training centroid -> reject if
/// out of scope -> softmax the scores -> reject if the predicted view does
/// not match the slot the photo was captured for, or if confidence in that
/// match is too low.
///
/// ImageNet normalisation is baked into the model; do not normalise again
/// here. Mirrors `ACGraderRegressor` deliberately, down to the OOD
/// cosine-similarity math, so the two stay easy to compare.
final class ViewValidatorRegressor: @unchecked Sendable {

    static let inputSize = 224
    /// Matches the Core ML model's input feature name exactly.
    static let inputName = "image"
    /// Minimum softmax confidence for a matching prediction to be accepted.
    /// A photo whose predicted view is correct but weakly so still gets
    /// rejected, since a border-line frame is exactly the kind of shot that
    /// silently degrades DHC/AC downstream.
    static let minConfidence = 0.5

    /// Class order the Core ML model's `scores` output uses. MUST match
    /// `VIEW_CLASSES_5` in the export notebook exactly, index for index.
    static let classOrder: [ToothView] = [.front, .right, .left, .maxillary, .mandibular]

    private let model: MLModel
    private let scoresOutputName: String
    private let vectorOutputName: String
    private let centroid: [[Float]]
    private let oodThreshold: Double

    init() throws {
        guard let url = Bundle.main.url(forResource: "ViewValidator", withExtension: "mlmodelc")
              ?? Bundle.main.url(forResource: "ViewValidator", withExtension: "mlpackage") else {
            throw ViewValidatorError.modelNotFound
        }
        let config = MLModelConfiguration()
        config.computeUnits = .all
        let loadedModel = try MLModel(contentsOf: url, configuration: config)

        let outputs = loadedModel.modelDescription.outputDescriptionsByName
        guard outputs.count >= 2 else { throw ViewValidatorError.outdatedModel }
        let sortedNames = outputs.keys.sorted()
        self.scoresOutputName = outputs.keys.contains("scores") ? "scores" : sortedNames[0]
        self.vectorOutputName = outputs.keys.contains("vektor") ? "vektor" : sortedNames[1]

        guard let input = loadedModel.modelDescription.inputDescriptionsByName[Self.inputName],
              input.type == .image else { throw ViewValidatorError.outdatedModel }
        self.model = loadedModel

        guard let configURL = Bundle.main.url(forResource: "ViewValidator_config", withExtension: "json"),
              let parsedConfig = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        else { throw ViewValidatorError.configNotFound }

        guard let centroidValues = parsedConfig["centroid"] as? [[NSNumber]],
              let oodThresholdValue = parsedConfig["ood_threshold"] as? NSNumber,
              let viewClasses = parsedConfig["view_classes"] as? [String],
              viewClasses.count == Self.classOrder.count
        else { throw ViewValidatorError.incompleteConfig }

        self.centroid = centroidValues.map { $0.map { $0.floatValue } }
        self.oodThreshold = oodThresholdValue.doubleValue
    }

    /// - Parameters:
    ///   - image: the captured or imported photo, any orientation.
    ///   - expected: the slot this photo is meant to fill.
    func validate(image: UIImage, expected: ToothView) throws -> ViewValidation {
        guard let buffer = ACGraderRegressor.pixelBuffer(from: image, side: Self.inputSize) else {
            throw ViewValidatorError.resizeFailed
        }
        let input = try MLDictionaryFeatureProvider(
            dictionary: [Self.inputName: MLFeatureValue(pixelBuffer: buffer)])
        let output = try model.prediction(from: input)

        guard let scoresFeature = output.featureValue(for: scoresOutputName)?.multiArrayValue,
              let vectorFeature = output.featureValue(for: vectorOutputName)?.multiArrayValue
        else { throw ViewValidatorError.noOutput }

        // OOD: the vector is already unit length, so cosine similarity is a dot product.
        let vectorCount = vectorFeature.count
        var vector = [Float](repeating: 0, count: vectorCount)
        for i in 0..<vectorCount { vector[i] = vectorFeature[i].floatValue }
        var highestSimilarity: Float = -1
        for c in centroid {
            let m = min(c.count, vectorCount)
            var dot: Float = 0
            for i in 0..<m { dot += c[i] * vector[i] }
            if dot > highestSimilarity { highestSimilarity = dot }
        }
        let ood = 1.0 - Double(highestSimilarity)

        if ood > oodThreshold {
            return ViewValidation(
                isValid: false, detectedView: nil, confidence: 0,
                oodScore: ood, oodThreshold: oodThreshold, matchesExpected: false,
                rejectionReason: "This doesn't look like an intraoral photo. Make sure it's one "
                                + "of the five views: front, right buccal, left buccal, upper or "
                                + "lower occlusal.")
        }

        // Softmax over the 5-class scores.
        let scoreCount = scoresFeature.count
        var raw = [Double](repeating: 0, count: scoreCount)
        for i in 0..<scoreCount { raw[i] = scoresFeature[i].doubleValue }
        let maxRaw = raw.max() ?? 0
        let expValues = raw.map { exp($0 - maxRaw) }
        let sumExp = expValues.reduce(0, +)
        let probabilities = sumExp > 0
            ? expValues.map { $0 / sumExp }
            : raw.map { _ in 1.0 / Double(max(raw.count, 1)) }

        guard let bestIndex = probabilities.indices.max(by: { probabilities[$0] < probabilities[$1] }),
              bestIndex < Self.classOrder.count
        else { throw ViewValidatorError.noOutput }

        let detected = Self.classOrder[bestIndex]
        let confidence = probabilities[bestIndex]
        let matches = detected == expected

        if !matches {
            return ViewValidation(
                isValid: false, detectedView: detected, confidence: confidence,
                oodScore: ood, oodThreshold: oodThreshold, matchesExpected: false,
                rejectionReason: "This looks like \(detected.title), not \(expected.title). "
                                + "Retake with the \(expected.title.lowercased()) framing.")
        }

        if confidence < Self.minConfidence {
            return ViewValidation(
                isValid: false, detectedView: detected, confidence: confidence,
                oodScore: ood, oodThreshold: oodThreshold, matchesExpected: true,
                rejectionReason: "This looks like \(expected.title) but the shot is unclear "
                                + "(\(Int(confidence * 100))% confidence). Retake with better "
                                + "framing or lighting.")
        }

        return ViewValidation(
            isValid: true, detectedView: detected, confidence: confidence,
            oodScore: ood, oodThreshold: oodThreshold, matchesExpected: true,
            rejectionReason: nil)
    }

    enum ViewValidatorError: LocalizedError {
        case modelNotFound, outdatedModel, noOutput, resizeFailed
        case configNotFound, incompleteConfig

        var errorDescription: String? {
            switch self {
            case .modelNotFound: return "ViewValidator.mlpackage is not in the app bundle. Add it to the Malokit target."
            case .outdatedModel: return "The bundled model is an older version (MultiArray input or a single output). Re-run notebook 20 and copy the new ViewValidator.mlpackage."
            case .noOutput: return "The model did not return the expected outputs."
            case .resizeFailed: return "Could not prepare the 224x224 image."
            case .configNotFound: return "ViewValidator_config.json is not in the app bundle."
            case .incompleteConfig: return "ViewValidator_config.json is incomplete (centroid, ood_threshold, view_classes). Re-run notebook 20."
            }
        }
    }
}
