import Foundation
import os









struct Motore {
    let radice: String

    struct Risposta {
        let dati: Data
        let errori: String
        let codice: Int32
        let scaduto: Bool
    }

    private static let coda = DispatchQueue(label: "local.sbk.secondbrain.motore", qos: .userInitiated,
                                            attributes: .concurrent)


    private static let fatte = OSAllocatedUnfairLock(initialState: [String]())
    static var chiamate: [String] { fatte.withLock { $0 } }

    var esiste: Bool {
        FileManager.default.fileExists(atPath: radice + "/tools/secondbrain/sb-app.py")
    }

    func chiedi(_ argomenti: [String], scadenza: TimeInterval = 60) async -> Risposta {
        await withCheckedContinuation { cont in
            Motore.coda.async {
                cont.resume(returning: esegui(argomenti, scadenza: scadenza))
            }
        }
    }



    func chiediSubito(_ argomenti: [String], scadenza: TimeInterval = 8) -> Risposta {
        esegui(argomenti, scadenza: scadenza)
    }

    private func esegui(_ argomenti: [String], scadenza: TimeInterval) -> Risposta {
        Motore.fatte.withLock { $0.append(argomenti.prefix(2).joined(separator: " ")) }
        let p = Process()
        let venv = radice + "/.venv/bin/python"

        let script = FileManager.default.fileExists(atPath: radice + "/tools/secondbrain/sb-motore.py")
            ? "tools/secondbrain/sb-motore.py" : "tools/secondbrain/sb-app.py"
        if FileManager.default.isExecutableFile(atPath: venv) {
            p.executableURL = URL(fileURLWithPath: venv)
            p.arguments = [script] + argomenti
        } else {
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["uv", "run", "python", script] + argomenti
        }
        p.currentDirectoryURL = URL(fileURLWithPath: radice)
        var env = ProcessInfo.processInfo.environment
        let casa = NSHomeDirectory()

        env["PATH"] = "\(casa)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["LANG"] = env["LANG"] ?? "en_US.UTF-8"
        p.environment = env
        let out = Pipe()
        let err = Pipe()
        p.standardOutput = out
        p.standardError = err
        p.standardInput = FileHandle.nullDevice
        do {
            try p.run()
        } catch {
            return Risposta(dati: Data(), errori: "the engine does not start: \(error.localizedDescription)", codice: -1,
                            scaduto: false)
        }
        var dati = Data()
        var errori = Data()
        let gruppo = DispatchGroup()
        gruppo.enter()
        DispatchQueue.global(qos: .userInitiated).async {
            dati = out.fileHandleForReading.readDataToEndOfFile()
            gruppo.leave()
        }
        gruppo.enter()
        DispatchQueue.global(qos: .utility).async {
            errori = err.fileHandleForReading.readDataToEndOfFile()
            gruppo.leave()
        }
        let scaduto = gruppo.wait(timeout: .now() + scadenza) == .timedOut
        if scaduto {
            p.terminate()
            _ = gruppo.wait(timeout: .now() + 5)
        }
        p.waitUntilExit()
        return Risposta(dati: dati, errori: String(data: errori, encoding: .utf8) ?? "", codice: p.terminationStatus,
                        scaduto: scaduto)
    }
}



final class Osservatore {
    private var sorgenti: [DispatchSourceFileSystemObject] = []
    private let quando: () -> Void

    init(percorsi: [String], quando: @escaping () -> Void) {
        self.quando = quando
        for percorso in percorsi {
            let fd = open(percorso, O_EVTONLY)
            guard fd >= 0 else { continue }
            let s = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd,
                                                              eventMask: [.write, .extend, .rename, .delete],
                                                              queue: .main)
            s.setEventHandler { [weak self] in self?.quando() }
            s.setCancelHandler { close(fd) }
            s.resume()
            sorgenti.append(s)
        }
    }

    deinit { ferma() }

    func ferma() {
        sorgenti.forEach { $0.cancel() }
        sorgenti.removeAll()
    }
}



final class CodaFile {
    struct Riga: Identifiable, Hashable {
        let id: Int
        let testo: String
    }

    private(set) var righe: [Riga] = []
    private var letti: UInt64 = 0
    private var resto = Data()
    private var numero = 0
    let percorso: String
    private let tetto = 3000

    init(percorso: String) {
        self.percorso = percorso
    }


    @discardableResult
    func leggi() -> Bool {
        guard let fh = FileHandle(forReadingAtPath: percorso) else { return false }
        defer { try? fh.close() }
        let fine = (try? fh.seekToEnd()) ?? 0
        if fine < letti {

            letti = 0
            resto = Data()
            righe = []
        }
        if letti == 0 && fine > 256 * 1024 {
            letti = fine - 256 * 1024
        }
        try? fh.seek(toOffset: letti)
        let nuovo = (try? fh.readToEnd()) ?? Data()
        guard !nuovo.isEmpty else { return false }
        letti += UInt64(nuovo.count)
        resto.append(nuovo)
        guard let ultimoACapo = resto.lastIndex(of: 0x0A) else { return false }
        let intere = resto[resto.startIndex...ultimoACapo]
        resto = Data(resto[resto.index(after: ultimoACapo)...])
        let testo = String(decoding: intere, as: UTF8.self)
        var nuove: [Riga] = []
        for linea in testo.split(separator: "\n", omittingEmptySubsequences: false).dropLast() {
            numero += 1
            nuove.append(Riga(id: numero, testo: Pulizia.riga(String(linea))))
        }
        righe.append(contentsOf: nuove)
        if righe.count > tetto { righe.removeFirst(righe.count - tetto) }
        return !nuove.isEmpty
    }
}




enum Pulizia {
    private static let regole: [(NSRegularExpression, String)] = [
        (#"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"#, "<jwt>"),
        (#"eyJ[A-Za-z0-9_\-\.]{6,}"#, "<jwt>"),
        (#"(?i)(bearer\s+)[^\s)"']{6,}"#, "$1<x>"),
        (#"xox[abposr]-[A-Za-z0-9\-]+"#, "<slack-token>"),
        (#"(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"#, "<gh-token>"),
        (#"sk-[A-Za-z0-9_\-]{10,}"#, "<sk-key>"),
        (#"(?i)(token|key|secret|password|cookie|authorization|api[_-]?key)(\s*[=:]\s*)(["']?)[^\s"',;}]{8,}"#, "$1$2$3<x>"),
        (#"\b[A-Za-z0-9_\-]{40,}\b"#, "<long>"),
    ].compactMap { modello, sost in
        (try? NSRegularExpression(pattern: modello)).map { ($0, sost) }
    }

    static func riga(_ s: String) -> String {
        var out = s
        for (rx, sost) in regole {
            out = rx.stringByReplacingMatches(in: out, range: NSRange(out.startIndex..., in: out), withTemplate: sost)
        }
        return out
    }
}
