import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count == 2 else { exit(64) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { exit(65) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]
let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
let orientationRaw = (properties?[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
let orientation = CGImagePropertyOrientation(rawValue: orientationRaw) ?? .up
let handler = VNImageRequestHandler(cgImage: image, orientation: orientation, options: [:])
do {
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
} catch { exit(66) }
