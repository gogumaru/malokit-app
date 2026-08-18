import AVFoundation
import Observation
import UIKit

@Observable
final class CameraService: NSObject {

    enum Status: Equatable {
        case idle
        case denied
        case running
        case failed(String)
    }

    var status: Status = .idle
    var liveQuality: QualityReading?
    var isCapturing = false
    var flashOn = true

    @ObservationIgnored let session = AVCaptureSession()

    @ObservationIgnored private let sessionQueue = DispatchQueue(label: "malokit.camera.session")
    @ObservationIgnored private let sampleQueue = DispatchQueue(label: "malokit.camera.samples")
    @ObservationIgnored private let photoOutput = AVCapturePhotoOutput()
    @ObservationIgnored private let videoOutput = AVCaptureVideoDataOutput()
    @ObservationIgnored private var isConfigured = false
    @ObservationIgnored private var lastSampleTime = CFAbsoluteTimeGetCurrent()
    @ObservationIgnored private var onCapture: ((UIImage) -> Void)?

    // MARK: - Lifecycle

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndRun()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    if granted {
                        self?.configureAndRun()
                    } else {
                        self?.status = .denied
                    }
                }
            }
        default:
            status = .denied
        }
    }

    func stop() {
        sessionQueue.async { [session] in
            if session.isRunning { session.stopRunning() }
        }
        liveQuality = nil
    }

    private func configureAndRun() {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            if !self.isConfigured {
                do {
                    try self.configure()
                    self.isConfigured = true
                } catch {
                    DispatchQueue.main.async { self.status = .failed(error.localizedDescription) }
                    return
                }
            }
            if !self.session.isRunning { self.session.startRunning() }
            DispatchQueue.main.async { self.status = .running }
        }
    }

    private func configure() throws {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        session.sessionPreset = .photo

        guard
            let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
            let input = try? AVCaptureDeviceInput(device: device),
            session.canAddInput(input)
        else { throw CameraError.noCamera }
        session.addInput(input)

        // Intraoral work is close range, so bias focus and exposure to the
        // centre of the guide frame rather than the whole scene.
        try? device.lockForConfiguration()
        if device.isFocusPointOfInterestSupported {
            device.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
        }
        if device.isFocusModeSupported(.continuousAutoFocus) {
            device.focusMode = .continuousAutoFocus
        }
        if device.isExposureModeSupported(.continuousAutoExposure) {
            device.exposureMode = .continuousAutoExposure
        }
        device.unlockForConfiguration()

        guard session.canAddOutput(photoOutput) else { throw CameraError.noOutput }
        session.addOutput(photoOutput)
        photoOutput.maxPhotoQualityPrioritization = .quality

        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String:
                Int(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
        ]
        videoOutput.setSampleBufferDelegate(self, queue: sampleQueue)
        if session.canAddOutput(videoOutput) { session.addOutput(videoOutput) }
    }

    // MARK: - Capture

    func capturePhoto(completion: @escaping (UIImage) -> Void) {
        guard status == .running, !isCapturing else { return }
        isCapturing = true
        onCapture = completion

        let settings = AVCapturePhotoSettings()
        settings.photoQualityPrioritization = .quality
        if photoOutput.supportedFlashModes.contains(.on) {
            settings.flashMode = flashOn ? .on : .off
        }
        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    enum CameraError: LocalizedError {
        case noCamera, noOutput
        var errorDescription: String? {
            switch self {
            case .noCamera: "No back camera is available on this device."
            case .noOutput: "The camera could not be prepared for stills."
            }
        }
    }
}

// MARK: - Photo delegate

extension CameraService: AVCapturePhotoCaptureDelegate {
    func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        defer { DispatchQueue.main.async { self.isCapturing = false } }
        guard
            error == nil,
            let data = photo.fileDataRepresentation(),
            let image = UIImage(data: data)
        else { return }

        let upright = Preprocessor.upright(image)
        DispatchQueue.main.async { [weak self] in
            self?.onCapture?(upright)
            self?.onCapture = nil
        }
    }
}

// MARK: - Live quality sampling

extension CameraService: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        let now = CFAbsoluteTimeGetCurrent()
        guard now - lastSampleTime > 0.25 else { return }
        lastSampleTime = now

        guard let reading = QualityChecker.evaluate(sampleBuffer: sampleBuffer) else { return }
        DispatchQueue.main.async { [weak self] in
            self?.liveQuality = reading
        }
    }
}
