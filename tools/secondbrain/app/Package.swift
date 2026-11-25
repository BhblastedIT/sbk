// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SBK",
    platforms: [.macOS("26.0")],
    targets: [
        .executableTarget(name: "SBK", path: "Sources/SecondBrain")
    ]
)
