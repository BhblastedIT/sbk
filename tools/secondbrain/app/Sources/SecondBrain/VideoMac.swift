import AppKit
import AVFoundation
import AVKit










final class VistaLettore: AVPlayerView {
    override func scrollWheel(with event: NSEvent) {
        if let s = enclosingScrollView {
            s.scrollWheel(with: event)
        } else {
            nextResponder?.scrollWheel(with: event)
        }
    }
}

enum VideoMac {
    @MainActor
    static func vista(_ lettore: AVPlayer) -> NSView {
        let v = VistaLettore()
        v.controlsStyle = .inline
        v.videoGravity = .resizeAspect
        v.player = lettore
        return v
    }

    @MainActor
    static func aggiorna(_ vista: NSView, _ lettore: AVPlayer) {
        guard let v = vista as? AVPlayerView, v.player !== lettore else { return }
        v.player = lettore
    }
}
