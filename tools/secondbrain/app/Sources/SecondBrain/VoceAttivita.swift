import AppKit
import SwiftUI










extension Registrazione {
    static let attivita = "attivita"
    var perAttivita: Bool { voce == Registrazione.attivita }

    var argomentiAttivita: [String] {


        let unaVolta = ["--una-volta", "audio-" + file.lastPathComponent]
        if chiave.hasPrefix("commento-") { return ["voce", file.path, "--durata", "\(secondi)", "--commento", String(chiave.dropFirst(9))] + unaVolta }
        return ["voce", file.path, "--durata", "\(secondi)"] + ContestoVoce.argomenti + unaVolta
    }
}



struct StatoVoce: Codable, Hashable {
    let ok: Bool
    let errore: String?
    let in_corso: Int?
    let rileggi_fra_s: Double?
    let testi: [String: String]?
    let richieste: [RichiestaVoce]?

    let contesto: Bool?

    func t(_ chiave: String) -> String { testi?[chiave] ?? TestiMancanti.manca(chiave) }
}

struct RichiestaVoce: Codable, Hashable, Identifiable {
    let id: String
    let creata: String?
    let quando: String?
    let via: String?
    let audio: String?
    let stato: String
    let stato_nome: String?
    let finita: Bool?
    let annullata: Bool?
    let testo: String?
    let detto: String?
    let dubbi: [String]?
    let motivo: String?
    let capito: String?
    let risposta: String?
    let domanda: String?
    let gesti: [GestoVoce]?
    let frase_gesti: String?
    let annulla: [String]?
    let conferma: [String]?
    let riprova: [String]?
    let rispondi: [String]?


    let dopo: String?
    let filo: String?
    let da_secondi: Int?
    let gia_fatto: String?

    let conferma_cambi: [CambioProposto]?
    let annullata_prima: AnnullataPrima?

    let apri: AperturaVoce?
    let commento: String?
}

struct GestoVoce: Codable, Hashable {
    let id_task: String?

    let id_vista: String?
    let titolo: String?
    let tipo: String?
    let cosa: String?
}

struct EsitoVoce: Codable {
    let ok: Bool
    let errore: String?
    let messaggio: String?
    let id: String?
}



extension Store {


    var cartellaDettati: String {
        let base = ProcessInfo.processInfo.environment["SB_ATTIVITA_DIR"] ?? (NSHomeDirectory() + "/.sbk-data/attivita")
        return base + "/dettati"
    }


    var dettatoAttivo: Bool {
        let r = Registratore.condiviso
        if voceFintaSecondi != nil { return true }
        if let d = r.daParte, d.registrazione.perAttivita, r.stato == .annullata || r.stato == .corta { return true }
        return r.voce == Registrazione.attivita && [.registra, .chiedo, .invio].contains(r.stato)
    }


    var microfonoAltrove: Bool {
        let r = Registratore.condiviso
        return r.occupato && r.voce != Registrazione.attivita
    }

    @discardableResult
    func caricaVoce() async -> Bool {

        guard !voceFintaCaricata, !modoIstantanea else { return true }
        cercaDettatiNonMandati()
        let r = await motore.chiedi(["cose", "voce-stato"], scadenza: 15)
        guard let s = try? JSONDecoder().decode(StatoVoce.self, from: r.dati), s.ok else {
            voceErroriDiFila += 1
            return false
        }
        voceErroriDiFila = 0

        let finiteOra = Set((s.richieste ?? []).filter { $0.finita == true && !($0.gesti ?? []).isEmpty }.map(\.id))
        let nuove = finiteOra.subtracting(voceFinitePrima)
        let primaVolta = voceAttivita == nil
        voceFinitePrima = finiteOra
        voceAttivita = s
        if !nuove.isEmpty && !primaVolta { await caricaCose() }
        return true
    }



    func seguiVoce() {
        guard !voceSegue, !modoIstantanea else { return }
        voceSegue = true
        Task { @MainActor in
            defer { voceSegue = false }
            await caricaVoce()


            while (voceAttivita?.in_corso ?? 0) > 0 || voceErroriDiFila > 0, voceErroriDiFila < 3 {
                let passo = max(2, voceAttivita?.rileggi_fra_s ?? 5)
                try? await Task.sleep(nanoseconds: UInt64(passo * 1_000_000_000))
                await caricaVoce()
            }
        }
    }


    func detta() {
        let reg = Registratore.condiviso
        if reg.voce == Registrazione.attivita && reg.stato == .registra {
            fermaEMandaDettato()
            return
        }
        guard !reg.occupato, !modoIstantanea else { return }
        Task { @MainActor in
            await reg.comincia(voce: Registrazione.attivita, chiave: Registrazione.attivita, cosa: t("titolo"), esito: "",
                               cartella: cartellaDettati, cartellaRegistro: cartellaDettati, testi: { self.t($0) })
        }
    }

    func fermaEMandaDettato() {
        guard let r = Registratore.condiviso.ferma() else { return }
        Task { @MainActor in _ = await mandaDettato(r) }
    }


    func mandaDettato(_ r: Registrazione) async -> String? {

        if bloccaGesto() {
            cercaDettatiNonMandati()
            Registratore.condiviso.inviata(coseEsito?.testo)
            return coseEsito?.testo
        }
        let e = try? JSONDecoder().decode(EsitoVoce.self, from: await motore.chiedi(["cose"] + r.argomentiAttivita, scadenza: 20).dati)
        let errore = e?.ok == true ? nil : (e?.errore ?? t("errore_motore"))


        if errore == nil { Store.segnaDettatoMandato(r.file) } else { cercaDettatiNonMandati() }
        Registratore.condiviso.inviata(errore)
        coseEsito = EsitoRiga(testo: errore ?? (e?.messaggio ?? ""), errore: errore != nil)
        seguiVoce()
        return errore
    }


    func mandaTestoVoce(_ testo: String) async -> Bool {
        guard !modoIstantanea, !bloccaGesto() else { return false }
        let e = try? JSONDecoder().decode(EsitoVoce.self, from: await motore.chiedi(["cose", "voce-testo", testo, "--una-volta", chiaveVoce(testo)], scadenza: 20).dati)
        if e?.ok == true { voceChiaviInVolo[testo] = nil }
        coseEsito = EsitoRiga(testo: e?.ok == true ? (e?.messaggio ?? "") : (e?.errore ?? t("errore_motore")), errore: e?.ok != true)
        seguiVoce()
        return e?.ok == true
    }



    @discardableResult
    func azioneVoce(_ argomenti: [String]) async -> Bool {
        guard !modoIstantanea, !argomenti.isEmpty, !bloccaGesto() else { return false }
        let e = try? JSONDecoder().decode(EsitoVoce.self, from: await motore.chiedi(["cose"] + argomenti, scadenza: 30).dati)
        coseEsito = EsitoRiga(testo: e?.ok == true ? (e?.messaggio ?? "") : (e?.errore ?? t("errore_motore")), errore: e?.ok != true)
        if argomenti.first == "voce-annulla" { await caricaCose() }
        seguiVoce()
        return e?.ok == true
    }



    var richiesteAVista: [RichiestaVoce] {
        func peso(_ r: RichiestaVoce) -> Int {
            if ["ti_chiede", "da_verificare"].contains(r.stato) { return 0 }
            return r.finita == true ? 2 : 1
        }
        return (voceAttivita?.richieste ?? [])
            .filter { r in !voceChiuse.contains(r.id) && (r.finita != true || richiestaRecente(r)) }
            .enumerated().sorted { (peso($0.element), $0.offset) < (peso($1.element), $1.offset) }.map(\.element)
    }



    func richiestaRecente(_ r: RichiestaVoce) -> Bool {
        guard let c = r.creata, !c.isEmpty else { return false }
        if c.hasPrefix(oggiNelFuso()) { return true }
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: settimanaVista?.fuso ?? "UTC") ?? .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        guard let d = f.date(from: String(c.prefix(19))) else { return false }
        return Date().timeIntervalSince(d) < 18 * 3600
    }


    var voceSegno: String? {
        if Registratore.condiviso.voce == Registrazione.attivita && Registratore.condiviso.stato == .registra { return "registra" }
        let vive = richiesteAVista
        if vive.contains(where: { ["ti_chiede", "da_verificare"].contains($0.stato) }) { return "chiede" }
        if (voceAttivita?.in_corso ?? 0) > 0 { return "lavora" }
        return nil
    }
}






extension Store {


    static func segnaDettatoMandato(_ file: URL) {
        let fm = FileManager.default
        let dir = file.deletingLastPathComponent().appendingPathComponent("mandati")
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)


        var base = file.deletingPathExtension().lastPathComponent
        if fm.fileExists(atPath: dir.appendingPathComponent(file.lastPathComponent).path) {
            base += "-" + String(Int(Date().timeIntervalSince1970 * 1000))
        }
        try? fm.moveItem(at: file, to: dir.appendingPathComponent(base).appendingPathExtension(file.pathExtension))
        let biglietto = file.deletingPathExtension().appendingPathExtension("json")
        if fm.fileExists(atPath: biglietto.path) {
            try? fm.moveItem(at: biglietto, to: dir.appendingPathComponent(base).appendingPathExtension("json"))
        }
    }



    func cercaDettatiNonMandati() {
        let reg = Registratore.condiviso
        if reg.voce == Registrazione.attivita && [.registra, .chiedo, .invio].contains(reg.stato) { return }
        let dir = URL(fileURLWithPath: cartellaDettati).appendingPathComponent("audio")
        let chiavi: [URLResourceKey] = [.contentModificationDateKey, .isRegularFileKey]
        let file = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: chiavi)) ?? []
        let adesso = Date()
        voceNonMandati = file.filter { u in
            guard u.pathExtension.lowercased() == "m4a",
                  let v = try? u.resourceValues(forKeys: Set(chiavi)), v.isRegularFile == true else { return false }
            return adesso.timeIntervalSince(v.contentModificationDate ?? adesso) > 5
        }
        .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }



    static func argomentiDettato(_ file: URL) -> [String] {
        var argomenti = ["cose", "voce", file.path]
        if let dati = try? Data(contentsOf: Registratore.biglietto(file)),
           let b = try? JSONSerialization.jsonObject(with: dati) as? [String: String],
           let k = b["chiave"], k.hasPrefix("commento-"), k.count > 9 { argomenti += ["--commento", String(k.dropFirst(9))] }

        return argomenti + ["--una-volta", "audio-" + file.lastPathComponent]
    }

    func mandaDettatoRimasto(_ file: URL) async {
        guard !modoIstantanea, !bloccaGesto() else { return }
        let argomenti = Store.argomentiDettato(file)
        let e = try? JSONDecoder().decode(EsitoVoce.self, from: await motore.chiedi(argomenti, scadenza: 20).dati)
        if e?.ok == true { Store.segnaDettatoMandato(file) }
        coseEsito = EsitoRiga(testo: e?.ok == true ? (e?.messaggio ?? "") : (e?.errore ?? t("errore_motore")), errore: e?.ok != true)
        cercaDettatiNonMandati()
        seguiVoce()
    }
}


struct SchedaDettatoRimasto: View {
    let store: Store
    let file: URL

    var body: some View {
        let ora: String = {
            let d = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? Date()
            let f = DateFormatter()
            f.dateFormat = "HH:mm"
            return f.string(from: d)
        }()
        HStack(spacing: 8) {
            Image(systemName: "waveform.badge.exclamationmark").foregroundStyle(Salute.attenzione.colore)
            Text(store.t("dettato_non_mandato").replacingOccurrences(of: "{ora}", with: ora))
                .font(.system(size: 12)).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button { NSWorkspace.shared.open(file) } label: { Image(systemName: "play.circle") }
                .buttonStyle(.borderless).help(store.t("aiuto_ascolta"))
            Button(store.t("manda_dettato")) { Task { await store.mandaDettatoRimasto(file) } }
                .controlSize(.small).help(store.t("aiuto_manda_dettato"))
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Salute.attenzione.colore.opacity(0.10), in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
    }
}
