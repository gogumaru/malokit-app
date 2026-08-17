//
//  WorldLiDARCaptureController.swift
//  TeethLidar
//
//  Owns the primary scanner's ARKit session and accumulates real scene-depth
//  samples in ARKit world coordinates.
//

import ARKit
import AVFoundation
import Combine
import CoreImage
import CoreVideo
import Foundation
import ImageIO
import UIKit
import simd

/// Tracks the lifecycle of a verified post-snap Figure-8 capture.
enum SweepState: Equatable {
    case idle
    case accumulating
    case complete
}

final class WorldLiDARCaptureController: NSObject, ObservableObject {
    @Published private(set) var isConfigured = false
    @Published private(set) var isTorchOn = true
    @Published private(set) var statusMessage: String? = "Checking LiDAR support…"
    @Published private(set) var worldPoints: [SIMD3<Float>] = []
    @Published private(set) var latestCamera: ARCamera?
    @Published private(set) var pointCount = 0
    @Published private(set) var isCapturing = false
    @Published private(set) var liveQuality: QualityReading?
    @Published var captureError: String?

    // MARK: - Sweep State (Verified Figure-8 Keyframes)
    @Published private(set) var sweepState: SweepState = .idle
    /// 0.0 → 1.0 progress through the six ordered Figure-8 transitions.
    @Published private(set) var sweepProgress: Float = 0
    /// Number of selected K0–K6 keyframes retained during this sweep.
    @Published private(set) var sweepFrameCount: Int = 0
    @Published private(set) var sweepNextRequirement = "Start at the centre"
    @Published private(set) var sweepAcceptedKeyframes: [String] = []
    @Published private(set) var sweepGuidance: Figure8SweepGuidance?
    /// A fixed AR landmark at the teeth's real measured position when the
    /// sweep began (see `beginSweep`) — set once per sweep, not per frame.
    /// Being a real, static world anchor, RealityKit renders its parallax
    /// at full framerate on its own; no per-frame publishing is needed.
    @Published private(set) var sweepTeethAnchorWorldTransform: simd_float4x4?
    /// Whether the phone is currently inside the active lobe target's
    /// radius, refreshed every ARKit frame (not throttled by
    /// `sweepCandidateInterval`) for a responsive tint change.
    @Published private(set) var sweepTargetReached = false
    /// The phone's current screen-space offset, refreshed every ARKit frame
    /// (unlike `sweepGuidance.screenPositionMetres`, which only updates on
    /// the throttled candidate path) so the movement ring's cursor dot
    /// moves smoothly instead of stepping at ~5Hz.
    @Published private(set) var sweepLiveScreenPositionMetres: SIMD2<Float> = .zero

    private var sweepSession: Figure8CaptureSession?
    private var sweepReferenceSnapshot: WorldLiDARFrameSnapshot?
    private var sweepReferenceArtifact: Figure8KeyframeArtifact?
    private var sweepCapturedPhoto: CapturedPhoto?
    private var sweepCompletion: ((Result<CapturedPhoto, Error>) -> Void)?
    private var sweepCrop: RGBCropMetadata?
    private var sweepImageOrientation: CGImagePropertyOrientation?
    private var lastSweepCandidateTimestamp: TimeInterval = 0
    private let sweepCandidateInterval: TimeInterval = 0.20

    private weak var session: ARSession?
    private var configuration: ARWorldTrackingConfiguration?

    private let processingQueue = DispatchQueue(
        label: "TeethLidar.WorldLiDAR.processing",
        qos: .userInitiated
    )
    private var accumulator = WorldLiDARVoxelAccumulator(
        voxelSize: 0.002,
        maximumCount: 50_000
    )
    private var recentFrames: [WorldLiDARFrameSnapshot] = []
    private var scanGeneration: UInt = 0
    private var lastPointCloudUpdateTimestamp: TimeInterval = 0
    private let pointCloudUpdateInterval: TimeInterval = 0.5
    private let captureQueue = DispatchQueue(
        label: "TeethLidar.WorldLiDAR.capture",
        qos: .userInitiated
    )
    private let ciContext = CIContext()
    private var lastQualityTimestamp: TimeInterval = 0

    func attach(session: ARSession) {
        self.session = session
        session.delegate = self
        session.delegateQueue = .main
    }

    func start() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !isConfigured else { return }
        guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else {
            statusMessage = "This device does not support ARKit LiDAR scene depth."
            return
        }

        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndRunSession()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if granted {
                        self.configureAndRunSession()
                    } else {
                        self.statusMessage = LiDARCaptureError.cameraPermissionDenied.localizedDescription
                    }
                }
            }
        default:
            statusMessage = LiDARCaptureError.cameraPermissionDenied.localizedDescription
        }
    }

    func stop() {
        dispatchPrecondition(condition: .onQueue(.main))
        session?.pause()
        setTorch(on: false, reportFailure: false)
        scanGeneration &+= 1
        clearPublishedCloud()
        isConfigured = false
        processingQueue.async { [weak self] in
            self?.accumulator.reset()
            self?.recentFrames.removeAll(keepingCapacity: false)
            self?.lastPointCloudUpdateTimestamp = 0
        }
    }

    func toggleTorch() {
        dispatchPrecondition(condition: .onQueue(.main))
        let requestedState = !isTorchOn
        setTorch(on: requestedState, reportFailure: true)
    }

    func capture(
        type: IntraoralPhotoType,
        previewSize: CGSize,
        completion: @escaping (Result<CapturedPhoto, Error>) -> Void
    ) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard isConfigured, let session else {
            completion(.failure(LiDARCaptureError.lidarUnavailable))
            return
        }
        guard !isCapturing else { return }
        guard let currentFrame = session.currentFrame,
              case .normal = currentFrame.camera.trackingState else {
            completion(.failure(LiDARCaptureError.photoCaptureFailed(
                "AR tracking is not ready. Hold the phone still and try again."
            )))
            return
        }
        let hasRecentDepth = processingQueue.sync { !recentFrames.isEmpty }
        guard hasRecentDepth else {
            completion(.failure(LiDARCaptureError.depthMissing))
            return
        }
        guard let configuration else {
            completion(.failure(LiDARCaptureError.photoCaptureFailed(
                "ARKit high-resolution photo settings are unavailable."
            )))
            return
        }
        let highResolutionPhotoSettings = configuration.videoFormat.defaultPhotoSettings
        let imageOrientation = currentCaptureImageOrientation()

        isCapturing = true
        session.captureHighResolutionFrame(using: highResolutionPhotoSettings) {
            [weak self] frame, error in
            guard let self else { return }
            self.captureQueue.async {
                if let error {
                    self.finishCapture(
                        .failure(LiDARCaptureError.photoCaptureFailed(
                            error.localizedDescription
                        )),
                        completion: completion
                    )
                    return
                }
                guard let frame else {
                    self.finishCapture(
                        .failure(LiDARCaptureError.photoCaptureFailed(
                            "No AR frame was returned."
                        )),
                        completion: completion
                    )
                    return
                }

                do {
                    try self.startSweepCapture(
                        frame: frame,
                        type: type,
                        previewSize: previewSize,
                        imageOrientation: imageOrientation,
                        completion: completion
                    )
                } catch {
                    self.finishCapture(.failure(error), completion: completion)
                }
            }
        }
    }

    private func configureAndRunSession() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard let session else {
            statusMessage = "The AR camera session is not attached."
            return
        }

        let configuration = ARWorldTrackingConfiguration()
        configuration.frameSemantics = [.sceneDepth]
        if let format = ARWorldTrackingConfiguration
            .recommendedVideoFormatForHighResolutionFrameCapturing {
            configuration.videoFormat = format
        }
        self.configuration = configuration
        scanGeneration &+= 1
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        isConfigured = true
        statusMessage = nil
        setTorch(on: isTorchOn, reportFailure: false)
    }

    private func setTorch(on: Bool, reportFailure: Bool) {
        guard let device = ARWorldTrackingConfiguration
            .configurableCaptureDeviceForPrimaryCamera,
              device.hasTorch,
              device.isTorchAvailable else {
            isTorchOn = false
            if reportFailure {
                statusMessage = "The torch is unavailable while ARKit is tracking."
            }
            return
        }

        do {
            try device.lockForConfiguration()
            device.torchMode = on ? .on : .off
            device.unlockForConfiguration()
            isTorchOn = on
        } catch {
            isTorchOn = false
            if reportFailure {
                statusMessage = "Torch unavailable: \(error.localizedDescription)"
            }
        }
    }

    private func clearPublishedCloud() {
        worldPoints = []
        latestCamera = nil
        pointCount = 0
    }

    private func resetProcessingState() {
        processingQueue.async { [weak self] in
            self?.accumulator.reset()
            self?.recentFrames.removeAll(keepingCapacity: false)
            self?.lastPointCloudUpdateTimestamp = 0
        }
    }

    private func startSweepCapture(
        frame: ARFrame,
        type: IntraoralPhotoType,
        previewSize: CGSize,
        imageOrientation: CGImagePropertyOrientation,
        completion: @escaping (Result<CapturedPhoto, Error>) -> Void
    ) throws {
        let source = CIImage(cvPixelBuffer: frame.capturedImage).oriented(imageOrientation)
        guard let cgImage = ciContext.createCGImage(source, from: source.extent) else {
            throw CaptureCropError.imageBufferUnavailable
        }
        let upright = UIImage(cgImage: cgImage)
        let crop = try CaptureCropGeometry.landscapeThreeByTwo(
            originalWidth: cgImage.width,
            originalHeight: cgImage.height,
            previewWidth: previewSize.width,
            previewHeight: previewSize.height
        )
        let croppedImage = try upright.cropped(using: crop)

        let depthSnapshot: WorldLiDARFrameSnapshot?
        if frame.sceneDepth != nil {
            depthSnapshot = Self.snapshot(from: frame)
        } else {
            let candidates = processingQueue.sync { recentFrames }
            depthSnapshot = WorldLiDARFrameMatcher.closest(
                to: frame.timestamp,
                frames: candidates,
                maximumDelta: 0.100
            )
        }
        guard let depthSnapshot else {
            throw LiDARCaptureError.depthNotSynchronized
        }

        if type.isMirrorView {
            let encoded = try encodedKeyframe(
                image: croppedImage,
                snapshot: depthSnapshot,
                rgbTimestamp: frame.timestamp,
                crop: crop,
                id: .k0,
                state: .idle,
                isDirectView: false,
                referenceTransform: depthSnapshot.cameraTransform,
                orientation: imageOrientation,
                trackingState: "normal"
            )
            let diagnosticCapture = CapturedPhoto(
                image: croppedImage,
                timestamp: Date(),
                type: type,
                depthData: nil,
                lidarCapture: LiDARCaptureData(
                    depthFloat32: encoded.depthFloat32,
                    confidenceUInt8: encoded.confidenceUInt8,
                    metadata: encoded.metadata
                )
            )
            finishCapture(.success(diagnosticCapture), completion: completion)
            return
        }

        let k0 = try encodedKeyframe(
            image: croppedImage,
            snapshot: depthSnapshot,
            rgbTimestamp: frame.timestamp,
            crop: crop,
            id: .k0,
            state: .idle,
            isDirectView: true,
            referenceTransform: depthSnapshot.cameraTransform,
            orientation: imageOrientation,
            trackingState: "normal"
        )
        let initialCapture = CapturedPhoto(
            image: croppedImage,
            timestamp: Date(),
            type: type,
            depthData: nil,
            lidarCapture: LiDARCaptureData(
                depthFloat32: k0.depthFloat32,
                confidenceUInt8: k0.confidenceUInt8,
                metadata: k0.metadata
            )
        )

        DispatchQueue.main.async { [weak self] in
            self?.beginSweep(
                capturedPhoto: initialCapture,
                referenceSnapshot: depthSnapshot,
                referenceArtifact: k0,
                crop: crop,
                imageOrientation: imageOrientation,
                completion: completion
            )
        }
    }

    private func finishCapture(
        _ result: Result<CapturedPhoto, Error>,
        completion: @escaping (Result<CapturedPhoto, Error>) -> Void
    ) {
        DispatchQueue.main.async { [weak self] in
            self?.isCapturing = false
            completion(result)
        }
    }

    // MARK: - Sweep Lifecycle

    /// Begin the Figure-8 LiDAR accumulation phase.
    /// Called internally after the RGB photo has been snapped.
    private func beginSweep(
        capturedPhoto: CapturedPhoto,
        referenceSnapshot: WorldLiDARFrameSnapshot,
        referenceArtifact: Figure8KeyframeArtifact,
        crop: RGBCropMetadata,
        imageOrientation: CGImagePropertyOrientation,
        completion: @escaping (Result<CapturedPhoto, Error>) -> Void
    ) {
        sweepCapturedPhoto = capturedPhoto
        sweepReferenceSnapshot = referenceSnapshot
        sweepReferenceArtifact = referenceArtifact
        sweepCrop = crop
        sweepImageOrientation = imageOrientation
        lastSweepCandidateTimestamp = 0
        sweepCompletion = completion
        sweepSession = Figure8CaptureSession(configuration: .developmentDefault)
        _ = sweepSession?.begin(
            k0: referenceArtifact,
            referenceTransform: referenceSnapshot.cameraTransform
        )
        sweepState = .accumulating
        sweepProgress = 0
        sweepFrameCount = 1
        sweepAcceptedKeyframes = [Figure8KeyframeID.k0.wireName]
        let initialTarget = screenTarget(for: sweepSession?.coverage.nextTarget)
        let targetRadius = sweepSession?.coverage.targetRadiusMetres
        sweepNextRequirement = initialTarget?.instruction ?? instruction(for: .leftUpper)
        sweepGuidance = Figure8SweepGuidance(
            mode: nil,
            normalizedPosition: .zero,
            screenPositionMetres: .zero,
            target: initialTarget,
            targetRadiusMetres: targetRadius,
            targetReached: false,
            instruction: initialTarget?.instruction ?? sweepNextRequirement
        )
        // A fixed AR landmark at the teeth's real measured position when the
        // sweep starts — computed once here, not per frame, since it must
        // stay put in world space as the phone moves (real depth, not a
        // guessed distance).
        if let teethPoint = WorldLiDARPointProjector.centerWorldPoint(snapshot: referenceSnapshot) {
            var transform = referenceSnapshot.cameraTransform
            transform.columns.3 = SIMD4<Float>(teethPoint.x, teethPoint.y, teethPoint.z, 1)
            sweepTeethAnchorWorldTransform = transform
        } else {
            sweepTeethAnchorWorldTransform = nil
        }
    }

    /// Cancel an in-progress sweep and discard accumulated data.
    func cancelSweep() {
        dispatchPrecondition(condition: .onQueue(.main))
        let completion = sweepCompletion
        resetSweepState()
        isCapturing = false
        completion?(.failure(LiDARCaptureError.photoCaptureFailed("Sweep was cancelled.")))
    }

    /// Deliver a complete verified keyframe bundle without fusing its depth maps.
    private func finishSweep(with bundle: Figure8CaptureBundle) {
        guard let capturedPhoto = sweepCapturedPhoto,
              let referenceArtifact = bundle.keyframes[.k0],
              let completion = sweepCompletion else {
            resetSweepState()
            return
        }

        sweepState = .complete
        let finalCapture = CapturedPhoto(
            image: capturedPhoto.image,
            timestamp: capturedPhoto.timestamp,
            type: capturedPhoto.type,
            depthData: capturedPhoto.depthData,
            lidarCapture: LiDARCaptureData(
                depthFloat32: referenceArtifact.depthFloat32,
                confidenceUInt8: referenceArtifact.confidenceUInt8,
                metadata: referenceArtifact.metadata
            ),
            figure8Capture: bundle
        )
        resetSweepState()
        isCapturing = false
        completion(.success(finalCapture))
    }

    private func resetSweepState() {
        sweepState = .idle
        sweepProgress = 0
        sweepFrameCount = 0
        sweepReferenceSnapshot = nil
        sweepReferenceArtifact = nil
        sweepCapturedPhoto = nil
        sweepCompletion = nil
        sweepCrop = nil
        sweepImageOrientation = nil
        lastSweepCandidateTimestamp = 0
        sweepSession = nil
        sweepAcceptedKeyframes = []
        sweepNextRequirement = "Start at the centre"
        sweepGuidance = nil
        sweepTeethAnchorWorldTransform = nil
        sweepTargetReached = false
        sweepLiveScreenPositionMetres = .zero
    }

    private func processVerifiedSweepFrame(
        _ frame: ARFrame,
        snapshot: WorldLiDARFrameSnapshot
    ) {
        guard var figure8Session = sweepSession,
              let referenceArtifact = sweepReferenceArtifact,
              let referenceSnapshot = sweepReferenceSnapshot,
              let crop = sweepCrop,
              let orientation = sweepImageOrientation else {
            return
        }

        let trackingIsNormal: Bool
        let trackingState: String
        switch frame.camera.trackingState {
        case .normal:
            trackingIsNormal = true
            trackingState = "normal"
        case .limited:
            trackingIsNormal = false
            trackingState = "limited"
        case .notAvailable:
            trackingIsNormal = false
            trackingState = "not_available"
        }

        let sample = Figure8FrameSample(
            cameraTransform: snapshot.cameraTransform,
            trackingIsNormal: trackingIsNormal,
            teethAnchorWorldTransform: sweepTeethAnchorWorldTransform
        )

        let previousState = figure8Session.coverage.state
        var anticipatedCoverage = figure8Session.coverage
        let anticipated = anticipatedCoverage.accept(sample: sample)
        guard anticipated.accepted,
              let keyframeID = keyframeID(for: anticipated.state) else {
            let acceptance = figure8Session.accept(
                sample: sample,
                candidate: referenceArtifact
            )
            sweepSession = figure8Session
            updateSweepStatus(from: figure8Session, acceptance: acceptance, sample: sample)
            return
        }

        do {
            guard let cropped = croppedImage(
                from: frame,
                referenceCrop: crop,
                orientation: orientation
            ) else {
                rejectSweep(reason: "Could not read the RGB frame for guided capture. Please retake it.")
                return
            }
            let candidate = try encodedKeyframe(
                image: cropped.image,
                snapshot: snapshot,
                rgbTimestamp: frame.timestamp,
                crop: cropped.crop,
                id: keyframeID,
                state: anticipated.state,
                isDirectView: true,
                referenceTransform: referenceSnapshot.cameraTransform,
                orientation: orientation,
                trackingState: trackingState
            )
            let acceptance = figure8Session.accept(
                sample: sample,
                candidate: candidate
            )
            sweepSession = figure8Session
            updateSweepStatus(
                from: figure8Session,
                acceptance: acceptance,
                sample: sample,
                targetReached: acceptance.accepted && anticipated.state != previousState
            )
            if let bundle = figure8Session.completedBundle {
                finishSweep(with: bundle)
            }
        } catch {
            rejectSweep(reason: "Could not encode a guided capture position: \(error.localizedDescription)")
        }
    }

    private func croppedImage(
        from frame: ARFrame,
        referenceCrop: RGBCropMetadata,
        orientation: CGImagePropertyOrientation
    ) -> (image: UIImage, crop: RGBCropMetadata)? {
        let source = CIImage(cvPixelBuffer: frame.capturedImage).oriented(orientation)
        guard let cgImage = ciContext.createCGImage(source, from: source.extent) else { return nil }
        let image = UIImage(cgImage: cgImage)
        guard let crop = try? CaptureCropGeometry.reproject(
            referenceCrop,
            ontoSourceWidth: cgImage.width,
            height: cgImage.height
        ), let cropped = try? image.cropped(using: crop) else {
            return nil
        }
        return (cropped, crop)
    }

    private func keyframeID(for state: Figure8State) -> Figure8KeyframeID? {
        Figure8KeyframeID.allCases.first { $0.expectedCoverageState == state }
    }

    /// Refreshes the phone's live screen position and whether it's inside
    /// the current lobe target's radius, every ARKit frame, so the ring's
    /// cursor dot moves smoothly and the crosshair/bar tint reacts
    /// immediately. Deliberately does not touch `sweepGuidance` /
    /// `sweepNextRequirement` — those stay owned by the throttled
    /// `updateSweepStatus` path below so momentary text like "Position
    /// recorded" isn't immediately overwritten by a per-frame call.
    private func updateLiveReticleGuidance(
        from figure8Session: Figure8CaptureSession,
        sample: Figure8FrameSample
    ) {
        let poseGuidance = figure8Session.coverage.guidance(for: sample)
        sweepLiveScreenPositionMetres = Figure8ScreenCoordinates.map(
            poseGuidance.positionMetres,
            for: figure8ScreenOrientation
        )
        guard let target = poseGuidance.target, poseGuidance.poseIssue == nil else {
            sweepTargetReached = false
            return
        }
        sweepTargetReached = simd_length(poseGuidance.positionMetres - target.positionMetres)
            <= figure8Session.coverage.targetRadiusMetres
    }

    private func updateSweepStatus(
        from figure8Session: Figure8CaptureSession,
        acceptance: Figure8Acceptance,
        sample: Figure8FrameSample,
        targetReached: Bool = false
    ) {
        sweepAcceptedKeyframes = Figure8KeyframeID.allCases.compactMap { id in
            figure8Session.selector.selected[id] == nil ? nil : id.wireName
        }
        sweepFrameCount = sweepAcceptedKeyframes.count
        sweepProgress = Float(max(0, sweepFrameCount - 1)) / 6
        let poseGuidance = figure8Session.coverage.guidance(for: sample)
        let mode = figure8Session.guidanceMode
        let orientation = figure8ScreenOrientation
        let target = screenTarget(for: poseGuidance.target)
        let instruction = targetReached
            ? "Position recorded"
            : mode?.message
            ?? target?.instruction
            ?? acceptance.rejectionReason
            ?? instruction(for: figure8Session.coverage.state)
        let screenPosition = Figure8ScreenCoordinates.map(
            poseGuidance.positionMetres,
            for: orientation
        )
        sweepGuidance = Figure8SweepGuidance(
            mode: mode,
            normalizedPosition: Figure8ScreenCoordinates.map(
                poseGuidance.normalizedPosition,
                for: orientation
            ),
            screenPositionMetres: screenPosition,
            target: target,
            targetRadiusMetres: target.map { _ in figure8Session.coverage.targetRadiusMetres },
            targetReached: targetReached,
            instruction: instruction
        )
        sweepNextRequirement = instruction
    }

    private var figure8ScreenOrientation: Figure8ScreenOrientation {
        let interfaceOrientation = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.effectiveGeometry.interfaceOrientation }
            .first ?? .portrait
        switch interfaceOrientation {
        case .portrait:
            return .portrait
        case .portraitUpsideDown:
            return .portraitUpsideDown
        case .landscapeLeft:
            return .landscapeLeft
        case .landscapeRight:
            return .landscapeRight
        default:
            return .portrait
        }
    }

    private func screenTarget(for target: Figure8MovementTarget?) -> Figure8MovementTarget? {
        target.map {
            Figure8ScreenCoordinates.target(from: $0, orientation: figure8ScreenOrientation)
        }
    }

    private func instruction(for state: Figure8State) -> String {
        switch state {
        case .idle: return "Move phone left and up"
        case .leftUpper: return "Move phone left and down"
        case .leftLower: return "Move phone to centre"
        case .centreCrossing: return "Move phone right and up"
        case .rightUpper: return "Move phone right and down"
        case .rightLower: return "Return phone to centre"
        case .returnCentre, .complete: return "Capture positions complete"
        case .rejected: return "Restart guided capture"
        }
    }

    private func rejectSweep(reason: String) {
        guard let completion = sweepCompletion else { return }
        resetSweepState()
        isCapturing = false
        completion(.failure(LiDARCaptureError.photoCaptureFailed(reason)))
    }

    private func encodedKeyframe(
        image: UIImage,
        snapshot: WorldLiDARFrameSnapshot,
        rgbTimestamp: TimeInterval,
        crop: RGBCropMetadata,
        id: Figure8KeyframeID,
        state: Figure8State,
        isDirectView: Bool,
        referenceTransform: simd_float4x4,
        orientation: CGImagePropertyOrientation,
        trackingState: String
    ) throws -> Figure8KeyframeArtifact {
        guard let rgbPNG = image.pngData() else {
            throw LiDARCaptureError.photoCaptureFailed("Could not encode the cropped RGB reference frame.")
        }
        let encoded = try ARDepthBundleEncoder.encode(
            snapshot: snapshot,
            rgbTimestamp: rgbTimestamp,
            ssmDepthEligible: isDirectView,
            exclusionReason: isDirectView
                ? nil
                : "Mirror view: LiDAR measures the physical mirror surface, not reflected teeth.",
            rgbCrop: crop
        )
        var metadata = encoded.metadata
        metadata.cameraToReferenceTransform = Self.flatten(
            referenceTransform.inverse * snapshot.cameraTransform
        )
        metadata.figure8KeyframeID = id.wireName
        metadata.figure8State = state.rawValue
        metadata.isDirectView = isDirectView
        metadata.orientation = "CGImagePropertyOrientation.\(orientation.rawValue)"
        metadata.trackingState = trackingState
        return Figure8KeyframeArtifact(
            id: id,
            rgbPNG: rgbPNG,
            depthFloat32: encoded.depthFloat32,
            metadata: metadata,
            confidenceUInt8: encoded.confidenceUInt8,
            depthCoverage: Self.depthCoverage(in: snapshot),
            blurScore: Float(QualityChecker.evaluate(image: image)?.sharpness ?? 0),
            poseSeparation: simd_length(
                SIMD3<Float>(
                    snapshot.cameraTransform.columns.3.x - referenceTransform.columns.3.x,
                    snapshot.cameraTransform.columns.3.y - referenceTransform.columns.3.y,
                    snapshot.cameraTransform.columns.3.z - referenceTransform.columns.3.z
                )
            ),
            isDirectView: isDirectView
        )
    }

    private static func depthCoverage(in snapshot: WorldLiDARFrameSnapshot) -> Float {
        let pixelCount = snapshot.width * snapshot.height
        guard pixelCount > 0, snapshot.depthValues.count >= pixelCount else { return 0 }
        let valid = (0..<pixelCount).filter { index in
            let confidence = snapshot.confidenceValues.flatMap {
                index < $0.count ? $0[index] : nil
            } ?? 2
            let depth = snapshot.depthValues[index]
            return confidence >= 1 && depth.isFinite && depth >= 0.05 && depth <= 2.0
        }.count
        return Float(valid) / Float(pixelCount)
    }

    private static func flatten(_ matrix: simd_float4x4) -> [Float] {
        (0..<4).flatMap { column in
            (0..<4).map { row in matrix[column][row] }
        }
    }

    private func currentCaptureImageOrientation() -> CGImagePropertyOrientation {
        let interfaceOrientation = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.effectiveGeometry.interfaceOrientation }
            .first ?? .portrait
        switch interfaceOrientation {
        case .portrait:
            return .right
        case .portraitUpsideDown:
            return .left
        case .landscapeLeft:
            return .up
        case .landscapeRight:
            return .down
        default:
            return .right
        }
    }

    fileprivate static func snapshot(from frame: ARFrame) -> WorldLiDARFrameSnapshot? {
        guard let sceneDepth = frame.sceneDepth,
              let depthValues = copyFloat32Pixels(from: sceneDepth.depthMap) else {
            return nil
        }

        let depthWidth = CVPixelBufferGetWidth(sceneDepth.depthMap)
        let depthHeight = CVPixelBufferGetHeight(sceneDepth.depthMap)
        let confidenceValues = sceneDepth.confidenceMap.flatMap {
            copyUInt8Pixels(from: $0)
        }
        return WorldLiDARFrameSnapshot(
            depthValues: depthValues,
            confidenceValues: confidenceValues,
            width: depthWidth,
            height: depthHeight,
            cameraImageWidth: Int(frame.camera.imageResolution.width),
            cameraImageHeight: Int(frame.camera.imageResolution.height),
            intrinsics: frame.camera.intrinsics,
            cameraTransform: frame.camera.transform,
            timestamp: frame.timestamp
        )
    }

    private static func copyFloat32Pixels(from pixelBuffer: CVPixelBuffer) -> [Float]? {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        var result = [Float](repeating: 0, count: width * height)
        result.withUnsafeMutableBufferPointer { destination in
            guard let destinationBase = destination.baseAddress else { return }
            for row in 0..<height {
                let source = base
                    .advanced(by: row * bytesPerRow)
                    .assumingMemoryBound(to: Float.self)
                destinationBase
                    .advanced(by: row * width)
                    .update(from: source, count: width)
            }
        }
        return result
    }

    private static func copyUInt8Pixels(from pixelBuffer: CVPixelBuffer) -> [UInt8]? {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        var result = [UInt8](repeating: 0, count: width * height)
        result.withUnsafeMutableBufferPointer { destination in
            guard let destinationBase = destination.baseAddress else { return }
            for row in 0..<height {
                let source = base
                    .advanced(by: row * bytesPerRow)
                    .assumingMemoryBound(to: UInt8.self)
                destinationBase
                    .advanced(by: row * width)
                    .update(from: source, count: width)
            }
        }
        return result
    }
}

extension WorldLiDARCaptureController: ARSessionDelegate {
    // Wrapped in `DispatchQueue.main.async` because ARKit invokes these
    // delegate methods on the main queue as part of its own per-frame render
    // cycle, which can land inside an in-flight SwiftUI view-update
    // transaction. Publishing `@Published` changes synchronously in that
    // window triggers "Publishing changes from within view updates is not
    // allowed" (undefined behavior per Apple's docs); deferring to the next
    // run-loop turn avoids it.
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        DispatchQueue.main.async { [weak self] in
            self?.handleDidUpdate(session: session, frame: frame)
        }
    }

    private func handleDidUpdate(session: ARSession, frame: ARFrame) {
        latestCamera = frame.camera
        let generation = scanGeneration

        if frame.timestamp - lastQualityTimestamp >= 0.25 {
            lastQualityTimestamp = frame.timestamp
            liveQuality = QualityChecker.evaluate(pixelBuffer: frame.capturedImage)
        }

        // --- Verified Figure-8 keyframe selection (runs on main for UI updates) ---
        if sweepState == .accumulating,
           frame.timestamp - lastSweepCandidateTimestamp >= sweepCandidateInterval,
           let snapshot = Self.snapshot(from: frame) {
            lastSweepCandidateTimestamp = frame.timestamp
            processVerifiedSweepFrame(frame, snapshot: snapshot)
        }

        // Cheap, unthrottled reticle guidance: runs every ARKit frame so the
        // AR-anchored 3D target moves smoothly, independent of the coarser
        // `sweepCandidateInterval` gate above (which protects the expensive
        // keyframe-candidate encoding path, not this pure-simd computation).
        if sweepState == .accumulating, let sweepSession {
            let trackingIsNormal: Bool
            switch frame.camera.trackingState {
            case .normal: trackingIsNormal = true
            case .limited, .notAvailable: trackingIsNormal = false
            }
            updateLiveReticleGuidance(
                from: sweepSession,
                sample: Figure8FrameSample(
                    cameraTransform: frame.camera.transform,
                    trackingIsNormal: trackingIsNormal,
                    teethAnchorWorldTransform: sweepTeethAnchorWorldTransform
                )
            )
        }

        processingQueue.async { [weak self] in
            guard let self,
                  let snapshot = Self.snapshot(from: frame) else {
                return
            }

            self.recentFrames.append(snapshot)
            if self.recentFrames.count > 6 {
                self.recentFrames.removeFirst(self.recentFrames.count - 6)
            }

            // Rebuilding and republishing the point cloud on every ARKit frame
            // (~30-60Hz) made the overlay flicker and dominate the preview;
            // capture's depth-matching (recentFrames, above) still needs
            // every frame, but the visible cloud only needs to refresh a
            // couple times a second.
            guard frame.timestamp - self.lastPointCloudUpdateTimestamp >= self.pointCloudUpdateInterval else {
                return
            }
            self.lastPointCloudUpdateTimestamp = frame.timestamp

            self.accumulator.insert(
                WorldLiDARPointProjector.project(snapshot: snapshot, sampleStride: 2)
            )
            let positions = self.accumulator.points.map(\.position)

            DispatchQueue.main.async { [weak self] in
                guard let self,
                      self.isConfigured,
                      self.scanGeneration == generation else {
                    return
                }
                self.worldPoints = positions
                self.pointCount = positions.count
            }
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        DispatchQueue.main.async { [weak self] in
            self?.latestCamera = camera
            switch camera.trackingState {
            case .normal:
                self?.statusMessage = nil
            case .notAvailable:
                self?.statusMessage = "Camera tracking is unavailable. Hold the phone still and try again."
            case .limited(let reason):
                self?.statusMessage = "LiDAR tracking is limited: \(reason.userFacingDescription)"
            }
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.scanGeneration &+= 1
            self.resetProcessingState()
            self.clearPublishedCloud()
            self.isConfigured = false
            self.isCapturing = false
            self.statusMessage = "LiDAR tracking failed: \(error.localizedDescription)"
        }
    }

    func sessionWasInterrupted(_ session: ARSession) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.scanGeneration &+= 1
            self.resetProcessingState()
            self.clearPublishedCloud()
            self.isConfigured = false
            self.isCapturing = false
            self.statusMessage = "The LiDAR camera was interrupted."
        }
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        DispatchQueue.main.async { [weak self] in
            guard let self, let configuration = self.configuration else { return }
            self.scanGeneration &+= 1
            session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
            self.isConfigured = true
            self.statusMessage = nil
        }
    }
}

private extension ARCamera.TrackingState.Reason {
    var userFacingDescription: String {
        switch self {
        case .initializing:
            return "initializing"
        case .excessiveMotion:
            return "move more slowly"
        case .insufficientFeatures:
            return "not enough visual detail"
        case .relocalizing:
            return "relocalizing"
        @unknown default:
            return "unknown reason"
        }
    }
}
