












import EventKit
import Foundation

let NOME_LISTA = "SBK"
// The repo folder: SB_RADICE (the LaunchAgent written by costruisci.py sets it), then the folder the SBK app uses
// (its "radice" setting, recorded by installa.py), then the usual clone places. The first one with the engine wins.
let RADICE: String = {
    var candidate: [String] = []
    if let r = ProcessInfo.processInfo.environment["SB_RADICE"], !r.isEmpty { candidate.append(r) }
    if let r = UserDefaults(suiteName: "local.sbk.secondbrain")?.string(forKey: "radice"), !r.isEmpty { candidate.append(r) }
    let casa = NSHomeDirectory()
    candidate += [casa + "/sbk", casa + "/Projects/sbk", casa + "/Developer/sbk", casa + "/Projects/SBK"]
    return candidate.first { FileManager.default.fileExists(atPath: $0 + "/tools/secondbrain/sb_promemoria.py") } ?? candidate[0]
}()
let PYTHON = RADICE + "/.venv/bin/python"
let SCRIPT = RADICE + "/tools/secondbrain/sb_promemoria.py"


let REGISTRO = NSHomeDirectory() + "/.sbk-data/logs/promemoria.log"

func ora() -> String {
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    return f.string(from: Date())
}

func registra(_ s: String) {
    let riga = Data("\(ora()) \(s)\n".utf8)
    if let h = FileHandle(forWritingAtPath: REGISTRO) {
        h.seekToEndOfFile()
        h.write(riga)
        try? h.close()
    } else {
        FileManager.default.createFile(atPath: REGISTRO, contents: riga)
    }
}

func errore(_ s: String) -> Never {
    registra("ERRORE: \(s)")
    exit(1)
}

let store = EKEventStore()

func accesso() {
    switch EKEventStore.authorizationStatus(for: .reminder) {
    case .fullAccess:
        return
    case .notDetermined:
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        var motivo = ""
        store.requestFullAccessToReminders { concesso, err in
            ok = concesso
            motivo = err.map { "\($0)" } ?? ""
            sem.signal()
        }
        sem.wait()
        if !ok { errore("Reminders access not granted \(motivo)") }
    default:
        errore("Reminders access denied: System Settings → Privacy & Security → Reminders → SBK Promemoria")
    }
}

func lista(crea: Bool) -> EKCalendar? {
    if let c = store.calendars(for: .reminder).first(where: { $0.title == NOME_LISTA }) { return c }
    if !crea { return nil }
    let c = EKCalendar(for: .reminder, eventStore: store)
    c.title = NOME_LISTA

    let sorgente = store.sources.first(where: { $0.sourceType == .calDAV && $0.title.lowercased().contains("icloud") })
        ?? store.defaultCalendarForNewReminders()?.source
    guard let s = sorgente else { errore("no account for Reminders on this Mac") }
    c.source = s
    do { try store.saveCalendar(c, commit: true) } catch { errore("list «\(NOME_LISTA)» not created: \(error)") }
    return c
}

func leggi(_ c: EKCalendar) -> [EKReminder] {
    let sem = DispatchSemaphore(value: 0)
    var tutti: [EKReminder] = []
    store.fetchReminders(matching: store.predicateForReminders(in: [c])) { r in
        tutti = r ?? []
        sem.signal()
    }
    sem.wait()
    return tutti
}

func giorno(_ dc: DateComponents?) -> Any {
    guard let dc = dc, let y = dc.year, let m = dc.month, let d = dc.day else { return NSNull() }
    return String(format: "%04d-%02d-%02d", y, m, d)
}

func comeJSON(_ r: EKReminder) -> [String: Any] {
    [
        "id": r.calendarItemIdentifier,
        "est": r.calendarItemExternalIdentifier ?? NSNull(),
        "url": r.url?.absoluteString ?? NSNull(),
        "titolo": r.title ?? "",
        "note": r.notes ?? "",
        "priorita": r.priority,
        "scadenza": giorno(r.dueDateComponents),
        "fatto": r.isCompleted,
    ]
}

func python(_ verbo: String, _ dati: Any) -> [String: Any] {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: PYTHON)
    p.arguments = ["-I", SCRIPT, verbo]
    var env = ProcessInfo.processInfo.environment
    env["SB_ATTIVITA_DA"] = "promemoria"
    p.environment = env
    let entrata = Pipe()
    let uscita = Pipe()
    p.standardInput = entrata
    p.standardOutput = uscita
    p.standardError = FileHandle.standardError
    do { try p.run() } catch { errore("python won't start: \(error)") }
    let corpo = (try? JSONSerialization.data(withJSONObject: dati)) ?? Data("[]".utf8)
    entrata.fileHandleForWriting.write(corpo)
    try? entrata.fileHandleForWriting.close()
    let risposta = uscita.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    if p.terminationStatus != 0 { errore("sb_promemoria.py \(verbo) exited with \(p.terminationStatus)") }
    guard let d = try? JSONSerialization.jsonObject(with: risposta) as? [String: Any] else {
        errore("sb_promemoria.py \(verbo) did not respond in JSON")
    }
    return d
}

func dataDa(_ s: String) -> DateComponents? {
    let p = s.split(separator: "-").compactMap { Int($0) }
    guard p.count == 3 else { return nil }
    var dc = DateComponents()
    dc.calendar = Calendar.current
    dc.timeZone = TimeZone.current
    dc.year = p[0]
    dc.month = p[1]
    dc.day = p[2]
    return dc
}

func esegui(_ ops: [[String: Any]], in c: EKCalendar) -> [[String: Any]] {
    var fatti: [(EKReminder?, [String: Any])] = []
    for op in ops {
        let chiave = op["chiave"] as? String ?? ""
        if op["op"] as? String == "togli" {
            if let id = op["id"] as? String, let r = store.calendarItem(withIdentifier: id) as? EKReminder {
                do { try store.remove(r, commit: false) } catch {
                    fatti.append((nil, ["op": "togli", "chiave": chiave, "esito": "\(error)"]))
                    continue
                }
            }
            fatti.append((nil, ["op": "togli", "chiave": chiave, "esito": "ok"]))
            continue
        }
        var r: EKReminder
        if let id = op["id"] as? String, let x = store.calendarItem(withIdentifier: id) as? EKReminder {
            r = x
        } else {
            r = EKReminder(eventStore: store)
            r.calendar = c
        }
        r.title = op["titolo"] as? String ?? ""
        r.notes = op["note"] as? String
        r.priority = op["priorita"] as? Int ?? 0
        r.dueDateComponents = (op["scadenza"] as? String).flatMap(dataDa)
        r.isCompleted = op["fatto"] as? Bool ?? false
        r.url = (op["url"] as? String).flatMap { URL(string: $0) }
        do {
            try store.save(r, commit: false)
        } catch {
            fatti.append((nil, ["op": "metti", "chiave": chiave, "esito": "\(error)"]))
            continue
        }
        var esito: [String: Any] = ["op": "metti", "chiave": chiave, "esito": "ok"]
        for k in ["titolo", "note", "priorita", "scadenza", "fatto"] { esito[k] = op[k] ?? NSNull() }
        fatti.append((r, esito))
    }
    do { try store.commit() } catch { errore("Promemoria non salvati: \(error)") }
    return fatti.map { r, e in
        var e = e
        if let r = r {
            e["id"] = r.calendarItemIdentifier
            e["est"] = r.calendarItemExternalIdentifier ?? NSNull()
        }
        return e
    }
}

let verbo = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "allinea"
accesso()
switch verbo {
case "leggi":
    let attuali = lista(crea: false).map { leggi($0).map(comeJSON) } ?? []
    let d = try! JSONSerialization.data(withJSONObject: attuali, options: [.prettyPrinted])
    FileHandle.standardOutput.write(d)
case "fonte":

    if let c = lista(crea: false) {
        let tipo = c.source.sourceType == .calDAV ? "calDAV" : c.source.sourceType == .local ? "local" : "\(c.source.sourceType.rawValue)"
        registra("list «\(NOME_LISTA)» in account «\(c.source.title)» (\(tipo)), \(leggi(c).count) reminders")
    } else {
        registra("list «\(NOME_LISTA)» doesn't exist")
    }
case "prova":
    let attuali = lista(crea: false).map { leggi($0).map(comeJSON) } ?? []
    let piano = python("prova", attuali)
    let d = try! JSONSerialization.data(withJSONObject: piano, options: [.prettyPrinted])
    FileHandle.standardOutput.write(d)
case "allinea":
    guard let c = lista(crea: true) else { errore("list not found") }
    let attuali = leggi(c).map(comeJSON)
    let piano = python("piano", attuali)
    let ops = piano["ops"] as? [[String: Any]] ?? []
    let gesti = piano["gesti"] as? [[String: Any]] ?? []
    if ops.isEmpty && gesti.isEmpty { exit(0) }
    let risultati = esegui(ops, in: c)
    let reg = python("registra", risultati)
    let male = risultati.filter { ($0["esito"] as? String) != "ok" }.count
    registra("reminders: \(attuali.count) read, \(gesti.count) gestures from phone, \(ops.count) operations, \(male) failed, matched \(reg["abbinate"] ?? "?")")
default:
    errore("unknown command «\(verbo)»: allinea, leggi or prova")
}
