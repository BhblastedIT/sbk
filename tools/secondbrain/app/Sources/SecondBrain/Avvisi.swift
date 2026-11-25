import AppKit
import UserNotifications








@MainActor
enum Avvisi {
    static var disponibili: Bool {
        Bundle.main.bundleIdentifier != nil && Bundle.main.bundleURL.pathExtension == "app"
    }


    static let chiaveFine = "avvisoFine"

    static let chiaveFasi = "avvisoFasi"
    static let chiaveMeta = "avvisoMeta"

    static let chiaveLavori = "avvisoLavori"

    static let chiaveLavoriAvvisati = "lavoriAvvisati"

    static func acceso(_ chiave: String) -> Bool {
        UserDefaults.standard.object(forKey: chiave) as? Bool ?? true
    }

    private static let delegato = Delegato()



    enum Permesso { case dato, daChiedere, negato, nonDisponibile }

    static func permesso() async -> Permesso {
        guard disponibili else { return .nonDisponibile }
        switch await UNUserNotificationCenter.current().notificationSettings().authorizationStatus {
        case .authorized, .provisional: return .dato
        case .notDetermined: return .daChiedere
        default: return .negato
        }
    }



    static func chiediPermesso() async {
        guard disponibili else { return }
        let centro = UNUserNotificationCenter.current()
        centro.delegate = delegato
        let impostazioni = await centro.notificationSettings()
        if impostazioni.authorizationStatus == .notDetermined {
            _ = try? await centro.requestAuthorization(options: [.alert, .sound])
        }
    }



    @discardableResult
    static func fine(_ r: Run) async -> Bool {
        guard acceso(chiaveFine) else { return true }
        var corpo = r.frase.map { $0.prefix(1).uppercased() + $0.dropFirst() + "." } ?? (r.motivo ?? "")


        if let racconto = r.racconto, !racconto.isEmpty { corpo = racconto }
        let fullRun = (r.comando ?? "").contains("sb-full.py")
        if fullRun && ["fermato", "interrotto", "fallito"].contains(r.esito ?? "") {
            corpo += " In SBK «Resume where you left off» completes what is missing."
        }
        return await manda(id: "fine-\(r.run_id)", titolo: titolo(r), corpo: corpo, gruppo: "run", segnaSeNo: true)
    }


    static func fineTerminale(_ g: Giro?) async {
        guard acceso(chiaveFine) else { return }
        let nonChiusi = (g?.non_chiusi ?? "").trimmingCharacters(in: .whitespaces)
        let titolo = g?.fermato == true ? "The terminal full run is stopped" :
            (nonChiusi.isEmpty || nonChiusi == "nessuno" ? "The terminal full run is finished" :
                "The terminal full run is finished, with unclosed steps")
        let corpo = nonChiusi.isEmpty || nonChiusi == "nessuno" ? "All steps have closed." :
            "Not closed \(nonChiusi). In SBK «Resume where you left off» completes what is missing."
        await manda(id: "fine-terminale-\(g?.inizio ?? Quando.adesso())", titolo: titolo, corpo: corpo, gruppo: "run",
                    segnaSeNo: true)
    }


    static func fase(_ nomeFase: String, id: String, passi: [PassoRun], nome: String, av: Avanzamento,
                     chiave: String) async {
        guard acceso(chiaveFasi), !passi.isEmpty else { return }
        let falliti = passi.filter { $0.stato == "fallito" }
        var corpo = "\(passi.count - falliti.count) \(id == "scarico" ? "sources" : "steps") of \(passi.count) ok"
        if !falliti.isEmpty {
            corpo += (falliti.count == 1 ? ", it failed " : ", they failed ") + inFila(falliti.map(\.nome))
        }
        let manca = quantoManca(av)
        corpo += manca.isEmpty ? ". \(nome) goes on." : ". \(nome), " + manca.prefix(1).lowercased() + manca.dropFirst()
        await manda(id: "fase-\(chiave)-\(id)", titolo: "Phase \(nomeFase) closed", corpo: corpo, gruppo: "run-\(chiave)",
                    segnaSeNo: false)
    }


    static func nonRiusciti(_ falliti: [PassoRun], nome: String, av: Avanzamento, chiave: String) async {
        guard acceso(chiaveFasi), !falliti.isEmpty else { return }
        let l = LetturaRun(av: av)
        let conto = "\(l.fatti) of \(av.passi.count)" + (av.dentro?.first.map { d in
            ", in the re-read \(d.passi.filter { LetturaRun.chiusi.contains($0.stato) }.count) of \(d.passi.count)"
        } ?? "")
        let titolo: String
        var corpo: String
        if falliti.count == 1, let p = falliti.first {
            titolo = "«\(p.nome)» failed"
            corpo = [p.diagnosi?.causa, "The run goes on."].compactMap { $0 }.joined(separator: " ")
        } else {
            titolo = "\(falliti.count) steps failed"
            corpo = inFila(falliti.map(\.nome)) + ". The run goes on."
        }
        corpo = [corpo, "\(nome), \(conto).", quantoManca(av)].filter { !$0.isEmpty }.joined(separator: " ")
        let ultimo = falliti.map(\.id).joined(separator: "+")
        await manda(id: "fallito-\(chiave)-\(ultimo)", titolo: titolo, corpo: corpo, gruppo: "run-\(chiave)",
                    segnaSeNo: false)
    }



    static func lavori(_ voci: [VoceLavoro]) async {
        guard acceso(chiaveLavori) else { return }
        let gia = Set(UserDefaults.standard.stringArray(forKey: chiaveLavoriAvvisati) ?? [])
        var tenute = gia.intersection(voci.map(\.chiave_avviso))
        for v in voci where !gia.contains(v.chiave_avviso) {
            let titolo = v.avviso?.titolo ?? v.titolo
            let corpo = v.avviso?.testo ?? v.dettaglio
            if await manda(id: "lavoro-\(v.chiave_avviso)", titolo: titolo, corpo: corpo, gruppo: "lavori",
                           segnaSeNo: true) {
                tenute.insert(v.chiave_avviso)
            }
        }
        UserDefaults.standard.set(Array(tenute), forKey: chiaveLavoriAvvisati)
    }


    private static func inFila(_ nomi: [String]) -> String {
        guard nomi.count > 1 else { return nomi.first ?? "" }
        return nomi.dropLast().joined(separator: ", ") + " and " + (nomi.last ?? "")
    }


    static func meta(nome: String, av: Avanzamento, chiave: String) async {
        guard acceso(chiaveMeta) else { return }
        let l = LetturaRun(av: av)
        let corpo = ["\(l.fatti) of \(av.passi.count) steps closed.", quantoManca(av)].filter { !$0.isEmpty }
            .joined(separator: " ")
        await manda(id: "meta-\(chiave)", titolo: "\(nome) is halfway", corpo: corpo, gruppo: "run-\(chiave)", segnaSeNo: false)
    }


    static func quantoManca(_ av: Avanzamento) -> String {
        guard let p = av.previsione, let restano = p.restano_s, restano > 0 else { return "" }
        let ora = Quando.ora(p.fine_prevista)
        return "About \(Quando.durata(restano)) left" + (ora.isEmpty ? "." : ", expected finish at \(ora).")
    }

    @discardableResult
    private static func manda(id: String, titolo: String, corpo: String, gruppo: String, segnaSeNo: Bool) async -> Bool {
        guard disponibili else { return false }
        let centro = UNUserNotificationCenter.current()
        centro.delegate = delegato
        var impostazioni = await centro.notificationSettings()


        if impostazioni.authorizationStatus == .notDetermined {
            _ = try? await centro.requestAuthorization(options: [.alert, .sound])
            impostazioni = await centro.notificationSettings()
        }
        guard impostazioni.authorizationStatus == .authorized || impostazioni.authorizationStatus == .provisional else {
            if segnaSeNo {
                NSApp.dockTile.badgeLabel = "1"
                NSApp.requestUserAttention(.informationalRequest)
            }
            return false
        }
        let c = UNMutableNotificationContent()
        c.title = titolo
        c.body = corpo
        c.threadIdentifier = gruppo
        do {
            try await centro.add(UNNotificationRequest(identifier: id, content: c, trigger: nil))
            return true
        } catch {
            if segnaSeNo { NSApp.dockTile.badgeLabel = "1" }
            return false
        }
    }

    static func titolo(_ r: Run) -> String {
        let nome = r.nome ?? "The run"

        if let t = Vocabolario.voci["run"]?[r.esito ?? "sconosciuto"]?.titolo { return "\(nome) \(t)" }
        switch r.esito {
        case "ok": return "\(nome) finished"
        case "incompleto": return "\(nome) finished, incomplete"
        case "fermato": return "\(nome) stopped"
        case "interrotto": return "\(nome) interrupted"
        case "non_partito": return "\(nome) did not start"
        default: return "\(nome) did not finish"
        }
    }


    private final class Delegato: NSObject, UNUserNotificationCenterDelegate {
        func userNotificationCenter(
            _ center: UNUserNotificationCenter,
            willPresent notification: UNNotification
        ) async -> UNNotificationPresentationOptions {
            [.banner, .sound]
        }
    }
}
