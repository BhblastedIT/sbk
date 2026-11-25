import AppKit
import Observation
import SwiftUI

enum Selezione: Hashable {
    case fonte(String)
    case stadio(String)
    case fase(String)
}


enum Sezione: String, CaseIterable, Identifiable, Hashable {









    case cose, panoramica, fonti, pipeline, run, spesa, regole, strumenti, posta, firme, pagine, inspiration, plaud

    var id: String { rawValue }

    var nome: String {
        switch self {
        case .cose: "Tasks"
        case .panoramica: "Overview"
        case .fonti: "Sources"
        case .pipeline: "Pipeline"
        case .run: "Run"
        case .spesa: "Cost and keys"
        case .regole: "Rules"
        case .strumenti: "Tools"
        case .posta: "Mail"
        case .firme: "To sign"
        case .pagine: "Pages"
        case .inspiration: "Inspiration"
        case .plaud: "Plaud"
        }
    }

    var simbolo: String {
        switch self {
        case .cose: "checklist"
        case .panoramica: "gauge.with.dots.needle.67percent"
        case .fonti: "tray.and.arrow.down.fill"
        case .pipeline: "point.3.filled.connected.trianglepath.dotted"
        case .run: "play.circle.fill"
        case .spesa: "creditcard.fill"
        case .regole: "book.closed.fill"
        case .strumenti: "wrench.and.screwdriver.fill"
        case .posta: "envelope.fill"
        case .firme: "signature"
        case .pagine: "books.vertical.fill"
        case .inspiration: "sparkles"
        case .plaud: "waveform"
        }
    }



    var aiuto: String {
        switch self {
        case .cose: "The tasks you have to do, from your list on ClickUp. The number says how many are in front of you right now (⌘T)."
        case .panoramica: "Whether you can trust the data and what needs fixing."
        case .fonti: "Where the data comes from and how fresh it is. The number says how many sources need a look."
        case .pipeline: "All the steps, phase by phase, with the last time of each. The number says how many failed."
        case .run: "What is running now, with the lanes and the log, and the earlier runs."
        case .spesa: "The estimate of the paid steps and the API keys, with the one that pays."
        case .regole: "How each source downloads and what each step does, with your rules and whether the code respects them."
        case .strumenti: "The alerts, the settings, the Mac's memory and the disk."
        case .posta: "The rules of your mailboxes, who stays in Primary and who goes to a label. From here you move a sender and carry the rules over to Gmail."
        case .firme: "The contracts waiting for your signature, even if you archived the email. They open from here."
        case .pagine: "The pages I prepared for you, with the account needed to open them online. In here they are read without access (⇧⌘P)."
        case .inspiration: "The things you save because they inspire you, reels, posts and sites, on a board. They open here, with the video when there is one (⌘0)."
        case .plaud: "The names of who speaks in your Plaud recordings, how solid they are and what is left to name."
        }
    }
}

enum Foglio: Identifiable {
    case fullRun
    case altroRun(VoceMenu)

    case completa(String)
    case ferma(Run)

    case riprendi(Ripresa)

    case stadio(Stadio)
    case comeSiFa([Fonte])

    case guida

    case copie

    case verifiche

    var id: String {
        switch self {
        case .fullRun: "full"
        case .altroRun(let v): "run-\(v.id)"
        case .completa(let tipo): "completa-\(tipo)"
        case .ferma(let r): "ferma-\(r.run_id)"
        case .riprendi(let r): "riprendi-\(r.cartella)"
        case .stadio(let s): "stadio-\(s.id)"
        case .comeSiFa(let f): "come-\(f.map(\.id).joined(separator: ","))"
        case .guida: "guida"
        case .copie: "copie"
        case .verifiche: "verifiche"
        }
    }
}



struct NotiziaTask: Equatable {
    let frase: String
    let id: String
}


@MainActor
@Observable
final class Store {

    var stato: Stato?
    var lettoAlle: Date?

    var daCache = false

    var errore: String?
    var dettaglioErrore: String?
    var leggendo = false
    var cartellaMancante = false



    var ricerca = ""
    var sezione: Sezione = Sezione(rawValue: UserDefaults.standard.string(forKey: "sezione") ?? "") ?? .panoramica {
        didSet { UserDefaults.standard.set(sezione.rawValue, forKey: "sezione") }
    }
    var selezione: Selezione?
    var ispettore = false
    var foglio: Foglio?

    var fasiChiuse: Set<String> = []
    var gruppiAperti: Set<String> = []

    var spesaScelta: Set<String> = []
    var avviso: String?

    var notizia: String?


    var notiziaTask: NotiziaTask?

    var apriAgenteInCorso = false
    var lanciando = false
    var fermoRichiesto: Set<String> = []



    var runScelto: String?
    var runSeguito: String?
    var avanzamento: Avanzamento?


    var passiFiniti: [String: Avanzamento] = [:]

    var rigaRun: String?

    var comandiRun: ComandiRun?
    var righeLog: [CodaFile.Riga] = []
    var percorsoLog: String?
    var seguiRegistro = true


    var aggiornando = false
    var logAggiornamento: String?



    var aggiornandoDa: Date?
    let scadenzaAggiornamento: TimeInterval = 300





    var aggiornamentoDisponibile: Bool {
        if let attesa = stato?.impronta?.contenuto, !attesa.isEmpty,
           let mio = Bundle.main.object(forInfoDictionaryKey: "SBContenutoApp") as? String, !mio.isEmpty {
            return mio != attesa
        }
        guard let attesa = stato?.impronta?.app, !attesa.isEmpty,
              let mia = Bundle.main.object(forInfoDictionaryKey: "SBCommitApp") as? String, !mia.isEmpty else { return false }
        return mia.trimmingCharacters(in: CharacterSet(charactersIn: "+")) != attesa.trimmingCharacters(in: CharacterSet(charactersIn: "+"))
    }


    func aggiornaApp() async {
        guard !aggiornando else { return }
        aggiornando = true
        aggiornandoDa = Date()
        let r = await motore.chiedi(["aggiorna"])
        if let esito = try? JSONDecoder().decode(Esito.self, from: r.dati), esito.ok == true {
            logAggiornamento = esito.log
        } else {
            aggiornando = false
            aggiornandoDa = nil
            avviso = "The update did not start. The engine did not respond."
        }
    }







    func autoAggiornaSeServe() async {
        if aggiornando, let da = aggiornandoDa, Date().timeIntervalSince(da) > scadenzaAggiornamento {

            aggiornando = false
            aggiornandoDa = nil
        }
        guard aggiornamentoDisponibile, !aggiornando, !modoIstantanea else { return }
        await aggiornaApp()
    }


    var verifiche: Verifiche?
    var erroreVerifiche: String?

    var ultimaVerifica: CasoVerifica?


    var regole: Regole?
    var erroreRegole: String?
    var vistaRegole: VistaRegole = .fonti

    var regoleAperte: Set<String> = []

    var regolaVaiA: String?
    var soloDaSistemare = false


    var strumenti: Strumenti?
    var erroreStrumenti: String?
    var drive: SchedaDriveDati?
    var erroreDrive: String?
    var soglie: [Soglia] = []


    var posta: Posta?
    var errorePosta: String?
    var postaCasella: String?
    var postaCerca = ""
    var postaInCorso = false

    var contoPosta: ContoPosta?
    var contoInLettura = false


    var cose: Cose? { didSet { coseIndice = cose?.indice ?? [:]; coseGiro &+= 1 } }

    @ObservationIgnored var coseGiro = 0

    var coseIndice: [String: VoceCosa] = [:]
    var erroreCose: String?
    var coseInLettura = false

    var coseDaRileggere = false
    var coseLetteAlle: Date?
    var coseCerca = "" { didSet { if oldValue != coseCerca { coseTenute = [] } } }

    var dettaglioCose = false
    var cosaAperta: String?

    var coseVista: String = UserDefaults.standard.string(forKey: "attivitaVista") ?? "urgenti" {
        didSet {
            UserDefaults.standard.set(coseVista, forKey: "attivitaVista")
            if oldValue != coseVista {

                if oldValue == "fatte" { coseFatteTutte = false }
                coseScelte = []
                coseFiltroAlVolo = [:]
                coseAppenaAggiunte = []
                coseTenute = []

                coseOrdine = Store.comparatori(schedaCose?.livelli ?? [])
                coseNuovaIn = [:]
            }
        }
    }

    var coseScelte: Set<String> = [] {
        didSet {
            guard oldValue != coseScelte else { return }
            if coseScelte.count == 1, let id = coseScelte.first, id != cosaAperta { cosaAperta = id; coseTitoloInModifica = false }
            if !coseScelte.isSubset(of: coseTenute) || coseScelte.isEmpty { coseTenute = [] }
        }
    }

    var coseOrdine: [OrdineCosa] = []

    var coseFiltroAlVolo: [String: [String]] = [:]

    var coseGruppiChiusi: [String: Set<String>] = [:]

    var coseTenute: Set<String> = []

    var coseFoto: FotoDisposizione?

    var coseAppenaAggiunte: [String] = []


    var coseChiuseInAttesa: Set<String> = []

    var coseChiuseGiro = 0

    var coseOccupate: Set<String> = []

    var coseEsito: EsitoRiga?

    var coseMese: String?

    var coseFuocoChiesto: FuocoCose?

    var coseCampoAttivo = false

    weak var coseUndo: UndoManager?

    var coseDataPer: [String]?

    var coseNuovaAreaPer: [String]?



    var coseConflitti: [ConflittoTesto] = []
    var coseConflitto: ConflittoTesto? {
        get { coseConflitti.first }
        set { if let n = newValue { coseConflitti.removeAll { $0.id == n.id && $0.campo == n.campo }; coseConflitti.insert(n, at: 0) }
              else if !coseConflitti.isEmpty { coseConflitti.removeFirst() } }
    }


    var coseLivelliVisti: [String: [OrdineVista]] = [:]

    var coseBozzeCommento: [String: String] = [:]

    var coseScrittiInCorso: [String: (id: String, campo: String, testo: String, era: String)] = [:]

    var coseEsitoImpostazioni: EsitoRiga?

    var schedaImpostazioni = Store.schedaAttivita
    static let schedaAttivita = "attivita"
    static let schedaInspiration = "inspiration"

    var coseOrdiniInVolo = 0


    var coseOrdiniDati = 0

    var coseFatteTutte = false

    var coseTempoPer: [String]?

    var coseDueRighe: Bool = UserDefaults.standard.bool(forKey: "attivitaDueRighe") {
        didSet { UserDefaults.standard.set(coseDueRighe, forKey: "attivitaDueRighe") }
    }

    var coseCassetto: Bool?

    var coseTitoloInModifica = false

    var voceAttivita: StatoVoce?
    var voceSegue = false
    var voceFinitePrima: Set<String> = []

    var voceChiuse: Set<String> = Set(UserDefaults.standard.stringArray(forKey: "attivitaVoceChiuse") ?? []) {
        didSet { UserDefaults.standard.set(Array(voceChiuse), forKey: "attivitaVoceChiuse") }
    }

    var voceFintaSecondi: Int?
    var voceFintaCaricata = false


    var voceNonMandati: [URL] = []

    var voceErroriDiFila = 0

    var coseNuovaIn: [String: String] = [:]

    var coseCodaGesti: Task<Void, Never>?


    var coseColonne: TableColumnCustomization<VoceCosa> = Store.colonneSalvate() {
        didSet { Store.salvaColonne(coseColonne) }
    }

    var coseColonneFoglio: TableColumnCustomization<VoceCosa> = Store.colonneSalvate(Store.chiaveColonneFoglio) {
        didSet { Store.salvaColonne(coseColonneFoglio, Store.chiaveColonneFoglio) }
    }


    var coseFoglioColonna = "task"
    var coseFoglioModifica: String?
    var coseFoglioBozza = ""

    var coseFoglioEra = ""

    var voceChiaviInVolo: [String: String] = [:]
    var coseFoglioRiquadro: String?


    var firme: Firme?
    var erroreFirme: String?
    var firmeInLettura = false

    var pagine: Pagine?
    var errorePagine: String?
    var pagineInLettura = false
    var paginaAperta: PaginaArtifact?
    var vistaPagine: VistaPagine = .data
    var cercaPagine = ""


    var paginaScelta: String?
    var nascondiProve = true
    var filtroPagine: String?
    var pagineNonRilette = false

    var anteprimeFatte = 0


    var inspiration: Inspiration?
    var erroreInspiration: String?
    var inspirationInLettura = false
    var inspirationNonRiletta = false
    var schedaInspiration: String?



    var filtroInspiration: FiltroSpunti = Store.filtroInspirationRicordato() {


        didSet { if oldValue != filtroInspiration, !modoIstantanea { Store.ricordaFiltroInspiration(filtroInspiration) } }
    }

    var ordineInspiration: String {
        get { filtroInspiration.ordine }
        set {
            if newValue == "progetto" {
                filtroInspiration.ordine = FiltroSpunti.ordinePartenza
                filtroInspiration.gruppo = "progetto"
            } else {
                filtroInspiration.ordine = newValue
            }
        }
    }

    var pannelloFiltriInspiration: Bool = UserDefaults.standard.bool(forKey: Store.chiavePannelloFiltri) {
        didSet { if !modoIstantanea { UserDefaults.standard.set(pannelloFiltriInspiration, forKey: Store.chiavePannelloFiltri) } }
    }


    var filtriSalvatiInspiration: [FiltroConNome] = []

    var chiediNomeFiltroInspiration = false
    var cercaInspiration = ""
    var spuntoAperto: String? {
        didSet {

            if spuntoAperto == nil, let prima = oldValue { ultimoSpuntoChiuso = prima }
        }
    }
    var ultimoSpuntoChiuso: String?
    var aParteAperta = false


    var faseInspiration: String? {
        get { filtroInspiration.passoScelto }
        set {
            let p = newValue.flatMap { $0.isEmpty || $0 == "tutti" ? nil : $0 }
            filtroInspiration.scelte[FiltroSpunti.passo] = p.map { [$0] }
        }
    }



    var vistaInspiration: String? = UserDefaults.standard.string(forKey: Store.chiaveVistaInspiration) {
        didSet { if !modoIstantanea { UserDefaults.standard.set(vistaInspiration, forKey: Store.chiaveVistaInspiration) } }
    }


    var erroreGesto: String?

    var riletturaInspiration: Rilettura?
    var riletturaInCorso = false

    var sogliaInScrittura: String?
    var erroreSoglia: String?


    var datiDomanda: String?
    var datiRisultati: [RisultatoDati] = []
    var datiErrore: String?
    var datiSecondi: Int?
    var cercandoDati = false


    var stima: Stima?
    var stimaInCorso = false
    var erroreStima: String?


    var finestraAperta = true

    var modoIstantanea = false

    var permessoAvvisi: Avvisi.Permesso = .nonDisponibile

    var mentreEriVia: [Run] = []

    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var coperta = false

    @ObservationIgnored private var pagineLetteAlle: Date?
    @ObservationIgnored private var registroVisto: Date?
    @ObservationIgnored private var osservatorePagine: Osservatore?
    @ObservationIgnored private var attesaPagine: DispatchWorkItem?
    @ObservationIgnored private var inspirationLettaAlle: Date?
    @ObservationIgnored private var fileInspirationVisto: Date?
    @ObservationIgnored private var osservatoreInspiration: Osservatore?
    @ObservationIgnored private var attesaInspiration: DispatchWorkItem?
    @ObservationIgnored private var fotografo: Anteprime?
    @ObservationIgnored private let fotoInMemoria = NSCache<NSString, NSImage>()

    @ObservationIgnored var cartellaAnteprime: URL?
    @ObservationIgnored private var daRileggere = false

    @ObservationIgnored private var daRileggereFresco = false
    @ObservationIgnored private var osservatore: Osservatore?
    @ObservationIgnored private var coda: CodaFile?
    @ObservationIgnored private var attesaRun: DispatchWorkItem?
    @ObservationIgnored private var viviPrima: Set<String> = []
    @ObservationIgnored private var primaLettura = true


    @ObservationIgnored private var passiVisti: [String: Set<String>] = [:]
    @ObservationIgnored private var fasiViste: [String: Set<String>] = [:]
    @ObservationIgnored private var metaAvvisata: Set<String> = []
    @ObservationIgnored private var terminaleVivo = false

    @ObservationIgnored private var stimaAutomaticaPer: String?

    /// The repo folder the app runs the engine from. installa.py records it at install time (the "radice" setting and
    /// the SBRadice key of the app's Info.plist); "Choose the folder…" changes it.
    var radice: String {
        get { UserDefaults.standard.string(forKey: "radice") ?? Self.radiceTrovata }
        set { UserDefaults.standard.set(newValue, forKey: "radice") }
    }

    private static let radiceTrovata = radiceDiPartenza()

    /// Where the repo is when nothing was saved yet: the folder installa.py wrote into the app bundle, then SB_RADICE,
    /// then the folders around the running binary and the working directory (`swift run` from tools/secondbrain/app),
    /// then a few usual clone places. The first one that holds the engine wins; with none, the first candidate, so the
    /// "Can't find SBK" page names a sensible path and offers to choose it.
    static func radiceDiPartenza() -> String {
        let casa = NSHomeDirectory()
        var candidate: [String] = []
        if let r = Bundle.main.object(forInfoDictionaryKey: "SBRadice") as? String, !r.isEmpty { candidate.append(r) }
        if let r = ProcessInfo.processInfo.environment["SB_RADICE"], !r.isEmpty { candidate.append(r) }
        for partenza in [Bundle.main.executablePath, FileManager.default.currentDirectoryPath].compactMap({ $0 }) {
            var u = URL(fileURLWithPath: partenza).standardizedFileURL
            for _ in 0..<8 {
                candidate.append(u.path)
                let su = u.deletingLastPathComponent()
                if su.path == u.path { break }
                u = su
            }
        }
        candidate += [casa + "/sbk", casa + "/Projects/sbk", casa + "/Developer/sbk", casa + "/Projects/SBK"]
        let fm = FileManager.default
        let usuali = Array(candidate.suffix(4))
        return candidate.first { fm.fileExists(atPath: $0 + "/tools/secondbrain/sb-motore.py") }
            ?? (Bundle.main.object(forInfoDictionaryKey: "SBRadice") as? String) ?? usuali[0]
    }

    var motore: Motore { Motore(radice: radice) }




    func avvia() {

        NSApp.dockTile.badgeLabel = nil
        guard timer == nil else { return }
        caricaCache()
        caricaCachePosta()
        caricaCacheFirme()
        caricaCacheCose()
        caricaCachePagine()
        caricaCacheInspiration()
        Task { await aggiorna() }

        Task { await caricaPagine(rileggi: true) }

        Task { await caricaCose() }


        if !modoIstantanea { Task { await caricaInspiration(motivo: "app startup") } }
        let t = Timer(timeInterval: 20, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.coperta else { return }
                await self.aggiorna()
                await self.rileggiCoseSeServe()
            }
        }
        t.tolerance = 2
        RunLoop.main.add(t, forMode: .common)
        timer = t

        NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.registrazioneAllaChiusura()

                self?.salvaScrittiAllaChiusura()
            }
        }
        NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: nil,
                                               queue: .main) { [weak self] nota in
            guard let finestra = nota.object as? NSWindow else { return }
            let visibile = finestra.occlusionState.contains(.visible)
            Task { @MainActor in
                guard let self else { return }
                let eraCoperta = self.coperta
                self.coperta = !visibile

                if eraCoperta && visibile { await self.aggiorna() }
            }
        }
    }

    func fermaTimer() {
        timer?.invalidate()
        timer = nil
    }



    func aggiorna(fresco: Bool = false) async {
        guard motore.esiste else {
            cartellaMancante = true
            return
        }
        cartellaMancante = false
        if leggendo {


            daRileggere = true
            daRileggereFresco = daRileggereFresco || fresco
            return
        }
        leggendo = true
        defer {
            leggendo = false
            if daRileggere {
                daRileggere = false
                let fresca = daRileggereFresco
                daRileggereFresco = false
                Task { await self.aggiorna(fresco: fresca) }
            }
        }
        let r = await motore.chiedi(fresco ? ["stato", "--fresco"] : ["stato"])
        do {
            let nuovo = try JSONDecoder().decode(Stato.self, from: r.dati)
            notaFiniti(nuovo)
            notaAvanzamenti(nuovo)
            stimaSeServe(nuovo)
            if let v = nuovo.vocabolario { Vocabolario.voci = v }
            stato = nuovo

            if let s = nuovo.stima, (stima?.quando ?? "") < s.quando { stima = s }
            lettoAlle = Date()
            daCache = false
            errore = nil
            dettaglioErrore = nil

            if !modoIstantanea, !Store.senzaCache { salvaCache(r.dati) }
            seguiSeServe()

            if sezione == .pagine { faiAnteprime() }
            await autoAggiornaSeServe()  // auto-update, both on its own and while in use
        } catch {
            errore = "I can't read the state."
            let coda = r.errori.split(separator: "\n").suffix(6).joined(separator: "\n")
            dettaglioErrore = r.scaduto ? "The engine did not respond within a minute." :
                (coda.isEmpty ? "\(error)" : coda)
        }
    }

    private var fileCacheBase: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("local.sbk.secondbrain", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base
    }
    private var fileCache: URL { fileCacheBase.appendingPathComponent("ultimo-stato.json") }
    private var fileCachePosta: URL { fileCacheBase.appendingPathComponent("ultima-posta.json") }
    private var fileCacheConto: URL { fileCacheBase.appendingPathComponent("ultimo-conto-posta.json") }
    private var fileCacheFirme: URL { fileCacheBase.appendingPathComponent("ultime-firme.json") }
    var fileCacheCose: URL { fileCacheBase.appendingPathComponent("ultime-cose.json") }


    static var senzaCache = false




    nonisolated(unsafe) private static var impronteCache: [String: Int] = [:]
    private static let lucchettoCache = NSLock()

    static func scriviCache(_ dati: Data, _ url: URL) {


        var h = Hasher()
        dati.withUnsafeBytes { h.combine(bytes: $0) }
        let impronta = h.finalize()
        lucchettoCache.lock()
        let uguale = impronteCache[url.path] == impronta
        lucchettoCache.unlock()
        if uguale, FileManager.default.fileExists(atPath: url.path) { return }
        guard (try? dati.write(to: url, options: .atomic)) != nil else { return }
        lucchettoCache.lock()
        impronteCache[url.path] = impronta
        lucchettoCache.unlock()
    }

    private var fileCachePagine: URL { fileCacheBase.appendingPathComponent("ultime-pagine.json") }
    private var fileCacheInspiration: URL { fileCacheBase.appendingPathComponent("ultima-inspiration.json") }



    private func caricaCache() {
        guard stato == nil, let dati = try? Data(contentsOf: fileCache),
              let vecchio = try? JSONDecoder().decode(Stato.self, from: dati) else { return }
        if let v = vecchio.vocabolario { Vocabolario.voci = v }
        stato = vecchio
        stima = vecchio.stima
        daCache = true
        lettoAlle = Quando.data(vecchio.generato)
        viviPrima = Set((vecchio.runs + (vecchio.scarichi_soli ?? [])).filter(\.vivo).map(\.run_id))
    }




    private func caricaCachePosta() {
        if posta == nil, let dati = try? Data(contentsOf: fileCachePosta),
           let vecchia = try? JSONDecoder().decode(Posta.self, from: dati) {
            posta = vecchia
        }
        if contoPosta == nil, let dati = try? Data(contentsOf: fileCacheConto),
           let vecchio = try? JSONDecoder().decode(ContoPosta.self, from: dati) {
            contoPosta = vecchio
        }
    }



    private func caricaCacheFirme() {
        if firme == nil, let dati = try? Data(contentsOf: fileCacheFirme),
           let vecchie = try? JSONDecoder().decode(Firme.self, from: dati) {
            firme = vecchie
        }
    }


    private func caricaCacheCose() {
        if cose == nil, let dati = try? Data(contentsOf: fileCacheCose),
           let vecchie = try? JSONDecoder().decode(Cose.self, from: dati), vecchie.ok {
            cose = vecchie
        }
    }


    private func caricaCachePagine() {
        if pagine == nil, let dati = try? Data(contentsOf: fileCachePagine),
           let vecchie = try? JSONDecoder().decode(Pagine.self, from: dati) {
            pagine = vecchie

            pagineLetteAlle = (try? FileManager.default.attributesOfItem(atPath: fileCachePagine.path))?[.modificationDate] as? Date
        }
    }

    private func salvaCache(_ dati: Data) {
        Store.scriviCache(dati, fileCache)
    }



    private func notaFiniti(_ nuovo: Stato) {
        let tutti = nuovo.runs + (nuovo.scarichi_soli ?? [])
        let vivi = Set(tutti.filter(\.vivo).map(\.run_id))
        if primaLettura {
            primaLettura = false
            let ultima = UserDefaults.standard.string(forKey: "ultimaApertura") ?? ""
            mentreEriVia = nuovo.runs.filter { !$0.vivo && ($0.fine ?? "") > ultima && !ultima.isEmpty }
            UserDefaults.standard.set(Quando.adesso(), forKey: "ultimaApertura")
        } else {
            for r in tutti where viviPrima.contains(r.run_id) && !vivi.contains(r.run_id) {
                fermoRichiesto.remove(r.run_id)
                runFinito(r)
            }
            UserDefaults.standard.set(Quando.adesso(), forKey: "ultimaApertura")
        }
        viviPrima = vivi
    }

    private func runFinito(_ r: Run) {
        Task {
            let consegnata = await Avvisi.fine(r)


            if !finestraAperta && runVivo == nil && scarichiVivi.isEmpty {
                if consegnata {
                    NSApp.terminate(nil)
                } else {
                    fermaTimer()
                }
            }
        }
    }






    private func notaAvanzamenti(_ nuovo: Stato) {
        if let r = nuovo.run_app, let av = r.avanzamento {
            notaAvanzamento(chiave: r.run_id, nome: r.nome ?? "Il run", av: av)
        }
        let vivo = nuovo.da_fuori.attivo
        if vivo, let g = nuovo.da_fuori.giro {
            notaAvanzamento(chiave: "terminale", nome: "The terminal full run", av: g)
        }
        if terminaleVivo && !vivo {
            passiVisti["terminale"] = nil
            fasiViste["terminale"] = nil
            metaAvvisata.remove("terminale")
            Task { await Avvisi.fineTerminale(nuovo.ultimo_full_run) }
        }
        terminaleVivo = vivo
    }

    func notaAvanzamento(chiave: String, nome: String, av: Avanzamento) {
        guard !modoIstantanea else { return }
        let dentro = av.dentro?.first?.passi ?? []
        let chiuso = { (p: PassoRun) in LetturaRun.chiusi.contains(p.stato) && p.stato != "interrotto" }
        var chiusi: [String: PassoRun] = [:]
        for p in av.passi where chiuso(p) {
            chiusi[p.id] = p
        }
        for p in dentro where chiuso(p) {
            chiusi["dentro:\(p.id)"] = p
        }


        var perFase: [String: [PassoRun]] = [:]
        for p in av.passi + dentro {
            if let f = p.fase { perFase[f, default: []].append(p) }
        }
        let fasiChiuse = Set(perFase.filter { _, passi in passi.allSatisfy(chiuso) }.keys)

        let frazione = av.previsione?.frazione_tempo ?? 0
        guard let visti = passiVisti[chiave] else {
            passiVisti[chiave] = Set(chiusi.keys)
            fasiViste[chiave] = fasiChiuse
            if frazione >= 0.5 { metaAvvisata.insert(chiave) }
            return
        }
        let nuovi = chiusi.keys.filter { !visti.contains($0) }.sorted().compactMap { chiusi[$0] }
        passiVisti[chiave] = visti.union(chiusi.keys)
        let falliti = nuovi.filter { $0.stato == "fallito" }
        if !falliti.isEmpty {
            Task { await Avvisi.nonRiusciti(falliti, nome: nome, av: av, chiave: chiave) }
        }
        let viste = fasiViste[chiave] ?? []
        fasiViste[chiave] = viste.union(fasiChiuse)


        let piuFasi = perFase.count > 1 || (!perFase.isEmpty && (av.passi + dentro).contains { $0.fase == nil })
        let ordine = stato?.fasi.map(\.id) ?? perFase.keys.sorted()
        for id in ordine where piuFasi && fasiChiuse.contains(id) && !viste.contains(id) && id != stato?.fasi.last?.id {
            let nomeFase = stato?.fasi.first { $0.id == id }?.nome ?? id
            let passi = perFase[id] ?? []
            Task { await Avvisi.fase(nomeFase, id: id, passi: passi, nome: nome, av: av, chiave: chiave) }
        }
        if frazione >= 0.5, !metaAvvisata.contains(chiave) {
            metaAvvisata.insert(chiave)
            Task { await Avvisi.meta(nome: nome, av: av, chiave: chiave) }
        }
    }





    private func stimaSeServe(_ nuovo: Stato) {
        guard !modoIstantanea, !stimaInCorso, !nuovo.da_fuori.attivo, nuovo.run_app == nil else { return }
        guard let pressione = nuovo.memoria?.pressione_pct, pressione < 50 else { return }
        let fineUltimo = ([nuovo.ultimo_full_run?.fine] + nuovo.runs.map(\.fine)).compactMap { $0 }.max() ?? ""
        guard Self.stimaVecchia(stima?.quando, fineUltimo: fineUltimo) else { return }
        let per = fineUltimo.isEmpty ? "no run" : fineUltimo
        guard stimaAutomaticaPer != per else { return }
        stimaAutomaticaPer = per
        Task { await preparaStima() }
    }


    private static func stimaVecchia(_ quando: String?, fineUltimo: String) -> Bool {
        let q = quando ?? ""
        return q.isEmpty || (!fineUltimo.isEmpty && q < fineUltimo)
    }



    var stimaDaRifare: Bool {
        let fineUltimo = ([stato?.ultimo_full_run?.fine] + (stato?.runs ?? []).map(\.fine)).compactMap { $0 }.max() ?? ""
        return Self.stimaVecchia(stima?.quando, fineUltimo: fineUltimo)
    }



    func caricaStrumenti() async {
        let r = await motore.chiedi(["strumenti"])
        if let nuovi = try? JSONDecoder().decode(Strumenti.self, from: r.dati), nuovi.ok {
            strumenti = nuovi
            erroreStrumenti = nil
        } else if strumenti == nil {
            erroreStrumenti = r.scaduto ? "The engine did not respond within a minute." : "The tools can't be read. The engine did not respond as it should."
        }
    }



    func caricaPosta() async {
        let r = await motore.chiedi(["posta"])
        if let nuova = try? JSONDecoder().decode(Posta.self, from: r.dati), nuova.ok {
            posta = nuova
            errorePosta = nil
            if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCachePosta) }
        } else if posta == nil {
            errorePosta = r.scaduto ? "The engine did not respond within a minute." : "The mail can't be read. The engine did not respond as it should."
        } else {

            avviso = "The mail was not re-read. What you see is how it was before the last change."
        }
    }

    func spostaMittente(_ m: MittentePosta, verso categoria: String, perche: String) async {
        postaInCorso = true
        let r = await motore.chiedi(["posta-sposta", m.casella, m.mittente, categoria, "--perche", perche])
        let esito = try? JSONDecoder().decode(EsitoPosta.self, from: r.dati)
        if let esito, esito.ok { notizia = esito.frase } else { avviso = esito?.frase ?? "The move did not succeed." }
        await caricaPosta()
        postaInCorso = false
    }


    func applicaPosta() async {
        postaInCorso = true
        let r = await motore.chiedi(["posta-applica"], scadenza: 600)
        let esito = try? JSONDecoder().decode(EsitoPosta.self, from: r.dati)
        if let esito, esito.ok { notizia = esito.frase } else { avviso = esito?.frase ?? "The rules did not reach Gmail. The engine did not respond as it should." }
        await caricaPosta()
        postaInCorso = false
    }


    func caricaContoPosta(rileggi: Bool = false) async {
        contoInLettura = true
        let r = await motore.chiedi(["posta-conto"] + (rileggi ? ["--rileggi"] : []), scadenza: 180)
        if let nuovo = try? JSONDecoder().decode(ContoPosta.self, from: r.dati), nuovo.ok {
            contoPosta = nuovo
            if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCacheConto) }
        } else {
            avviso = posta?.t("conto_non_letto") ?? "The inbox was not read."
        }
        contoInLettura = false
    }

    func confermaNuovo(_ n: NuovoMittente, verso categoria: String, perche: String) async {
        postaInCorso = true
        let r = await motore.chiedi(["posta-nuovo", n.casella, n.mittente, categoria, "--perche", perche])
        let esito = try? JSONDecoder().decode(EsitoPosta.self, from: r.dati)
        if let esito, esito.ok { notizia = esito.frase } else { avviso = esito?.frase ?? "The move did not succeed." }
        await caricaPosta()
        await caricaContoPosta()
        postaInCorso = false
    }



    func caricaFirme(rileggi: Bool = false) async {
        firmeInLettura = true
        let r = await motore.chiedi(["firme"] + (rileggi ? ["--rileggi"] : []), scadenza: 180)
        if let nuove = try? JSONDecoder().decode(Firme.self, from: r.dati), nuove.ok {
            firme = nuove
            erroreFirme = nil
            if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCacheFirme) }
        } else if firme == nil {
            erroreFirme = r.scaduto ? "DocuSign and the mail did not respond within three minutes." : "The contracts can't be read. The engine did not respond as it should."
        } else {
            avviso = "The contracts were not re-read. What you see is how it was before."
        }
        firmeInLettura = false
    }

    func escludiFirma(_ c: ContrattoFirma, perche: String) async {
        let r = await motore.chiedi(["firme-escludi", c.id, c.titolo, "--perche", perche])
        let esito = try? JSONDecoder().decode(EsitoPosta.self, from: r.dati)
        if let esito, esito.ok { notizia = esito.frase } else { avviso = esito?.frase ?? "The contract did not leave the list." }
        await caricaFirme()
    }

    func riammettiFirma(_ id: String) async {
        let r = await motore.chiedi(["firme-riammetti", id])
        let esito = try? JSONDecoder().decode(EsitoPosta.self, from: r.dati)
        if let esito, esito.ok { notizia = esito.frase } else { avviso = esito?.frase ?? "The contract did not return to the list." }
        await caricaFirme()
    }






    func caricaPagine(rileggi: Bool = false) async {
        pagineInLettura = true
        let r = await motore.chiedi(["pagine"] + (rileggi ? ["--rileggi"] : []), scadenza: 60)
        if let nuove = try? JSONDecoder().decode(Pagine.self, from: r.dati), nuove.ok {
            pagine = nuove
            errorePagine = nil
            pagineNonRilette = false
            pagineLetteAlle = Date()
            registroVisto = Self.dataFile(nuove.registro)
            if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCachePagine) }

            if let aperta = paginaAperta { paginaAperta = nuove.pagine.first { $0.id == aperta.id } ?? aperta }
            guardaRegistro(nuove)
        } else if pagine == nil {
            errorePagine = "The pages can't be read. The engine did not respond as it should."
        } else {

            pagineNonRilette = true
        }
        pagineInLettura = false
    }



    var oraPagine: String? { pagineLetteAlle.map { Quando.ora24($0) } }




    private func caricaCacheInspiration() {
        if inspiration == nil, let dati = try? Data(contentsOf: fileCacheInspiration),
           let vecchia = try? JSONDecoder().decode(Inspiration.self, from: dati) {
            inspiration = vecchia
            inspirationLettaAlle = (try? FileManager.default.attributesOfItem(atPath: fileCacheInspiration.path))?[.modificationDate] as? Date
        }
    }



    func caricaInspiration(motivo: String = "a richiesta") async {
        inspirationInLettura = true
        let via = Date()
        let r = await motore.chiedi(["inspiration"], scadenza: 60)
        if modoIstantanea {
            do { _ = try JSONDecoder().decode(Inspiration.self, from: r.dati) } catch {
                FileHandle.standardError.write("decodifica inspiration: \(error)\n".data(using: .utf8)!)
            }

            Store.misuraBacheca(r.dati)
        }
        if let nuova = try? JSONDecoder().decode(Inspiration.self, from: r.dati), nuova.ok {
            inspiration = nuova


            if let v = vistaInspiration, nuova.testa?.righeTesta?.contains(where: { $0.vista == v }) != true {
                vistaInspiration = nil
            }


            potaFiltroInspiration()
            erroreInspiration = nil
            inspirationNonRiletta = false
            inspirationLettaAlle = Date()
            fileInspirationVisto = Self.dataFile(nuova.file)

            if !modoIstantanea, !Store.senzaCache { Store.scriviCache(r.dati, fileCacheInspiration) }
            guardaInspiration(nuova)
            registraLetturaInspiration(motivo, via, esito: "ok, \(r.dati.count) byte")
        } else if inspiration == nil {
            erroreInspiration = "The ideas can't be read. The engine did not respond as it should."
            registraLetturaInspiration(motivo, via, esito: r.scaduto ? "engine timed out" : "response not read")
        } else {
            inspirationNonRiletta = true
            registraLetturaInspiration(motivo, via, esito: r.scaduto ? "engine timed out" : "response not read")
        }
        inspirationInLettura = false
    }




    private func registraLetturaInspiration(_ motivo: String, _ via: Date, esito: String) {
        guard !modoIstantanea, let cartella = inspiration?.cartella else { return }
        let ms = Int(Date().timeIntervalSince(via) * 1000)
        let riga = "\(Registratore.iso(Date())) bacheca riletta (\(motivo)), \(ms) ms, \(esito)\n"
        Registratore.appendi(riga, a: URL(fileURLWithPath: cartella).deletingLastPathComponent().appendingPathComponent("registro-app.log"))
    }



    func apriInspiration() async {
        let fresca = inspirationLettaAlle.map { inspiration != nil && Date().timeIntervalSince($0) < 300 } ?? false
        if !fresca { await caricaInspiration(motivo: "opening the section") }

        await leggiFiltriSalvatiInspiration()
    }

    var oraInspiration: String? { inspirationLettaAlle.map { Quando.ora24($0) } }



    func apriSpunto(_ id: String) {
        ricerca = ""
        sezione = .inspiration
        spuntoAperto = id
    }




    func apriImpostazioniInspiration() {
        schedaImpostazioni = Store.schedaInspiration
        guard !modoIstantanea else { return }
        NotificationCenter.default.post(name: .apriImpostazioniAttivita, object: nil)
    }





    func azioneInspiration(_ argomenti: [String]) async -> String? {
        let r = await motore.chiedi(["inspiration"] + argomenti, scadenza: 150)
        let esito = try? JSONDecoder().decode(EsitoAzione.self, from: r.dati)


        await caricaInspiration(motivo: "after the gesture \(argomenti.first ?? "")")
        guard let esito else {


            if let frase = nonSoSeAndata { return frase }

            let titolo = parolaInspiration("errore_titolo", "It didn't work")
            return r.scaduto
                ? "\(titolo). \(parolaInspiration("motore_scaduto", "The engine did not respond in time. Try again"))"
                : "\(titolo). The engine did not respond as it should."
        }
        if esito.ok {
            if let frase = esito.messaggio?.trimmingCharacters(in: .whitespacesAndNewlines), !frase.isEmpty {
                notizia = frase


                notiziaTask = esito.taskInAttivita.map { NotiziaTask(frase: frase, id: $0) }
            }
            return nil
        }
        return esito.messaggio ?? parolaInspiration("errore_titolo", "It didn't work")
    }

    private func parolaInspiration(_ chiave: String, _ altrimenti: String) -> String {
        inspiration?.testi[chiave] ?? altrimenti
    }



    private var nonSoSeAndata: String? {
        inspiration?.testi["non_so_se_andata"].flatMap { $0.isEmpty ? nil : $0 }
    }



    func notiziaDaIstantanea() {
        let env = ProcessInfo.processInfo.environment
        guard modoIstantanea, let frase = env["SB_NOTIZIA"], !frase.isEmpty else { return }
        notizia = frase
        notiziaTask = env["SB_NOTIZIA_TASK"].flatMap { $0.isEmpty ? nil : NotiziaTask(frase: frase, id: $0) }
    }





    func rileggiInspiration() async {
        guard !riletturaInCorso else { return }
        riletturaInCorso = true
        let r = await motore.chiedi(["inspiration", "rileggi"], scadenza: 180)
        let esito = try? JSONDecoder().decode(Rilettura.self, from: r.dati)
        await caricaInspiration(motivo: "after Re-read now")
        if let esito {
            riletturaInspiration = esito
        } else if let frase = nonSoSeAndata {

            riletturaInspiration = Rilettura(ok: false, messaggio: frase, frase: nil, dettaglio: nil)
        } else {
            let titolo = parolaInspiration("errore_titolo", "It didn't work")
            let perche = r.scaduto
                ? parolaInspiration("motore_scaduto", "The engine did not respond in time. Try again")
                : "The engine did not respond as it should."
            riletturaInspiration = Rilettura(ok: false, messaggio: "\(titolo). \(perche)", frase: nil, dettaglio: nil)
        }
        riletturaInCorso = false
    }




    func mandaRegistrazione(_ r: Registrazione) async -> String? {

        if r.perAttivita { return await mandaDettato(r) }
        let errore = await azioneInspiration(r.argomenti)
        Registratore.condiviso.inviata(errore)
        if let errore { erroreGesto = errore }
        return errore
    }



    func fermaEMandaRegistrazione(_ motivo: String) {
        let reg = Registratore.condiviso
        guard reg.stato == .registra else { return }

        guard reg.voce != Registrazione.attivita else { return }
        reg.registra("\(motivo) con il microfono acceso: fermo e mando")
        guard let r = reg.ferma() else { return }
        Task { @MainActor in _ = await self.mandaRegistrazione(r) }
    }



    private func registrazioneAllaChiusura() {
        let reg = Registratore.condiviso
        guard reg.stato == .registra else { return }
        reg.registra("app chiusa con il microfono acceso: fermo e mando")
        guard let r = reg.ferma() else { return }

        let risposta = motore.chiediSubito(r.perAttivita ? ["cose"] + r.argomentiAttivita : ["inspiration"] + r.argomenti,
                                           scadenza: 8)
        if r.perAttivita {


            let esito = try? JSONDecoder().decode(EsitoVoce.self, from: risposta.dati)
            if esito?.ok == true { Store.segnaDettatoMandato(r.file) }
            reg.inviata(esito?.ok == true ? nil : (esito?.errore ?? (risposta.scaduto ? "the engine did not respond in time" : "the engine did not respond")))
            return
        }
        let esito = try? JSONDecoder().decode(EsitoAzione.self, from: risposta.dati)
        reg.inviata(esito?.ok == true ? nil : (esito?.messaggio ?? (risposta.scaduto ? "the engine did not respond in time" : "the engine did not respond")))
    }





    func seguiInspiration() async {
        var giri = 0
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, sezione == .inspiration, !modoIstantanea, let i = inspiration else { continue }
            giri += 1
            let vive = i.voci.contains { v in
                guard let L = v.lavorazione else { return false }
                return L.sessione.aperta || (L.lavoro.avviato && L.lavoro.ritorno == nil)
                    || L.domande.contains { $0.in_trascrizione } || L.perche.correzione_in_trascrizione
                    || L.comprensione?.aperta == true || L.rilettura?.aperta == true
            }
            if vive {
                await caricaInspiration(motivo: "the 15-second cycle")
            } else if giri % 40 == 0, i.ritmo?.acceso == true, (i.da_capire_visti ?? 0) > 0 {
                await caricaInspiration(motivo: "the ten-minute check")
            }
        }
    }

    private func guardaInspiration(_ i: Inspiration) {
        guard !modoIstantanea, osservatoreInspiration == nil, let cartella = i.cartella else { return }
        osservatoreInspiration = Osservatore(percorsi: [cartella]) { [weak self] in self?.cambiataInspiration() }
    }

    private func cambiataInspiration() {
        attesaInspiration?.cancel()
        let lavoro = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                guard let self, Self.dataFile(self.inspiration?.file) != self.fileInspirationVisto else { return }
                await self.caricaInspiration(motivo: "the export changed")
            }
        }
        attesaInspiration = lavoro
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: lavoro)
    }


    func apriScelta(_ id: String?) {
        paginaAperta = id.flatMap { id in pagine?.pagine.first { $0.id == id } }
    }


    func apriVersione(_ id: String) {
        if let v = pagine?.pagine.first(where: { $0.id == id }) { paginaAperta = v }
    }





    var haFasce: Bool {
        aggiornando || avviso != nil || notizia != nil
    }


    func anteprima(_ p: PaginaArtifact) -> NSImage? {
        _ = anteprimeFatte
        guard let c = p.copia else { return nil }
        let copia = URL(fileURLWithPath: c)
        let file = Anteprime.file(per: copia, in: cartellaAnteprime)
        let fm = FileManager.default
        let dataFoto = (try? fm.attributesOfItem(atPath: file.path))?[.modificationDate] as? Date
        let dataCopia = (try? fm.attributesOfItem(atPath: c))?[.modificationDate] as? Date
        if let dataFoto, dataCopia.map({ dataFoto >= $0 }) ?? true {
            let chiave = "\(file.path)|\(dataFoto.timeIntervalSince1970)" as NSString
            if let img = fotoInMemoria.object(forKey: chiave) { return img }
            if let img = NSImage(contentsOf: file) {
                fotoInMemoria.setObject(img, forKey: chiave)
                return img
            }
        }
        if !modoIstantanea || cartellaAnteprime != nil {
            (fotografo ?? nuovoFotografo()).chiedi(copia)
            DispatchQueue.main.async { [weak self] in self?.faiAnteprime() }
        }
        return nil
    }

    private func nuovoFotografo() -> Anteprime {
        let a = Anteprime()
        a.cartella = cartellaAnteprime
        a.dopo = { [weak self] _, riuscita in
            guard let self else { return }
            if riuscita { self.anteprimeFatte += 1 }
            self.faiAnteprime()
        }
        fotografo = a
        return a
    }



    func faiAnteprime(forza: Bool = false) {
        let pressione = stato?.memoria?.pressione_pct ?? 100
        let tranquillo = runVivo == nil && stato?.da_fuori.attivo != true && pressione < 50
        fotografo?.prossima(permesso: forza || (sezione == .pagine && !coperta && tranquillo))
    }



    func apriPagine() async {
        if let letto = pagineLetteAlle, pagine != nil, Date().timeIntervalSince(letto) < 300 { return }
        await caricaPagine()
    }



    private func guardaRegistro(_ p: Pagine) {
        guard !modoIstantanea, osservatorePagine == nil, let cartella = p.cartella else { return }
        osservatorePagine = Osservatore(percorsi: [cartella]) { [weak self] in self?.cambiataLaCartellaPagine() }
    }

    private func cambiataLaCartellaPagine() {
        attesaPagine?.cancel()
        let lavoro = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                guard let self else { return }

                guard Self.dataFile(self.pagine?.registro) != self.registroVisto else { return }
                await self.caricaPagine()
            }
        }
        attesaPagine = lavoro
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: lavoro)
    }

    private static func dataFile(_ percorso: String?) -> Date? {
        guard let percorso else { return nil }
        return (try? FileManager.default.attributesOfItem(atPath: percorso))?[.modificationDate] as? Date
    }

    func caricaDrive() async {
        let r = await motore.chiedi(["drive"])
        if let nuova = try? JSONDecoder().decode(SchedaDriveDati.self, from: r.dati), nuova.ok {
            drive = nuova
            soglie = soglie.filter { $0.sezione != "drive" } + nuova.soglie
            erroreDrive = nil
        } else if drive == nil {
            erroreDrive = r.scaduto ? "The engine did not respond within a minute." : "The Drive card can't be read."
        }
    }

    func aggiornaPermesso() async {
        guard !modoIstantanea else { return }
        permessoAvvisi = await Avvisi.permesso()
    }


    func permettiAvvisi() async {
        await Avvisi.chiediPermesso()
        await aggiornaPermesso()
    }

    func caricaSoglie() async {
        let r = await motore.chiedi(["impostazioni"])
        if let esito = try? JSONDecoder().decode(EsitoSoglie.self, from: r.dati), esito.ok, let s = esito.soglie {
            soglie = s
        }
    }


    func imposta(_ s: Soglia, _ valore: ValoreSoglia) async {
        guard !modoIstantanea, sogliaInScrittura == nil else { return }
        sogliaInScrittura = s.id
        defer { sogliaInScrittura = nil }
        let r = await motore.chiedi(["imposta", s.sezione, s.chiave, valore.testo])
        let esito = try? JSONDecoder().decode(EsitoSoglie.self, from: r.dati)
        if let nuove = esito?.soglie { soglie = nuove }
        if esito?.ok == true {
            erroreSoglia = nil
            if s.sezione == "drive" { await caricaDrive() }
        } else {
            erroreSoglia = esito?.errore ?? "The threshold was not written. The engine did not respond."
        }
    }



    var runVivo: Run? { stato?.run_app }



    private func seguiSeServe() {
        guard let r = runVivo else {
            if runSeguito != nil {
                osservatore?.ferma()
                osservatore = nil
                runSeguito = nil
                avanzamento = nil
            }
            return
        }
        avanzamento = r.avanzamento
        rigaRun = r.riga
        comandiRun = r.comandi
        guard runSeguito != r.run_id else { return }
        runSeguito = r.run_id
        var percorsi = [r.log]
        if let c = r.cartella {
            percorsi += [c, c + "/esiti.tsv", c + "/log"]
        }
        osservatore = Osservatore(percorsi: percorsi) { [weak self] in self?.cambiatoIlRun() }
        apriLog(percorso: r.log)
    }

    private func cambiatoIlRun() {
        if let coda, coda.leggi() { righeLog = coda.righe }
        guard attesaRun == nil else { return }
        let lavoro = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                self.attesaRun = nil
                await self.aggiornaRun()
            }
        }
        attesaRun = lavoro
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5, execute: lavoro)
    }

    func caricaPassi(_ id: String) async {
        guard passiFiniti[id] == nil else { return }
        let r = await motore.chiedi(["run", id])
        guard let esito = try? JSONDecoder().decode(Esito.self, from: r.dati), esito.ok == true,
              let av = esito.avanzamento else { return }
        passiFiniti[id] = av
    }

    private func aggiornaRun() async {
        guard let id = runSeguito else { return }
        let r = await motore.chiedi(["run", id])
        guard let esito = try? JSONDecoder().decode(Esito.self, from: r.dati), esito.ok == true else { return }
        avanzamento = esito.avanzamento
        rigaRun = esito.riga
        comandiRun = esito.comandi ?? comandiRun
        if let av = esito.avanzamento {
            notaAvanzamento(chiave: id, nome: esito.run?.nome ?? stato?.run_app?.nome ?? "Il run", av: av)
        }
        if esito.run?.vivo == false {

            await aggiorna()
        }
    }



    func apriLog(percorso: String) {
        percorsoLog = percorso
        let c = CodaFile(percorso: percorso)
        c.leggi()
        coda = c
        righeLog = c.righe
        if runSeguito == nil {
            osservatore?.ferma()
            osservatore = Osservatore(percorsi: [percorso]) { [weak self] in
                guard let self, let coda = self.coda, coda.leggi() else { return }
                self.righeLog = coda.righe
            }
        }
    }


    func registroDi(_ r: Run, passo: String? = nil) -> String {
        if let passo, let c = r.cartella, FileManager.default.fileExists(atPath: c + "/log/\(passo).log") {
            return c + "/log/\(passo).log"
        }
        return r.log
    }



    var occupato: Bool { lanciando || !(stato?.azioni.possibile ?? false) || daCache }


    func lancia(tipo: String, arg: String = "", consentiSpesa: Bool = false, spesa: [String]? = nil) async {
        guard !lanciando else { return }
        lanciando = true
        defer { lanciando = false }
        avviso = nil
        await Avvisi.chiediPermesso()
        var args = ["lancia", tipo]
        if !arg.isEmpty { args.append(arg) }
        if consentiSpesa { args.append("--consenti-spesa") }
        if let spesa { args += ["--spesa", spesa.joined(separator: ",")] }
        let r = await motore.chiedi(args)
        guard let esito = try? JSONDecoder().decode(Esito.self, from: r.dati) else {
            avviso = "The run did not start. The engine did not respond."
            return
        }
        if esito.ok == true {

            await aggiorna()
        } else {
            avviso = "The run did not start. " + (esito.errore ?? "")
        }
    }

    func ferma(_ run: Run) async {
        let r = await motore.chiedi(["ferma", run.run_id])
        if let esito = try? JSONDecoder().decode(Esito.self, from: r.dati) {
            if esito.ok == true {
                fermoRichiesto.insert(run.run_id)
            } else {
                avviso = esito.errore
            }
        }
        await aggiorna()
    }




    func pulisciLock() async {
        struct Esito: Decodable { let ok: Bool?; let tolti: Int?; let perche: String? }
        let r = await motore.chiedi(["pulisci-lock"])
        guard let e = try? JSONDecoder().decode(Esito.self, from: r.dati) else {
            avviso = "The locks were not removed. The engine did not respond."
            return
        }
        if e.ok == true {
            let n = e.tolti ?? 0
            notizia = n == 0 ? "There were no leftover locks to remove." : (n == 1 ? "Removed one leftover lock." : "Removed \(n) leftover locks.")
        } else {
            avviso = e.perche ?? "The locks were not removed."
        }
        await aggiorna()
    }


    func apriConsensoDocuSign() async {
        struct Esito: Decodable { let ok: Bool?; let url: String?; let perche: String? }
        let r = await motore.chiedi(["consenso-docusign"])
        if let e = try? JSONDecoder().decode(Esito.self, from: r.dati), e.ok == true,
           let s = e.url, let url = URL(string: s), url.scheme == "https" {
            NSWorkspace.shared.open(url)
        } else {
            avviso = "The DocuSign consent page does not open. " + ((try? JSONDecoder().decode(Esito.self, from: r.dati))?.perche ?? "")
        }
    }


    func apriApp(_ nome: String) {
        guard !nome.isEmpty, nome.allSatisfy({ $0.isLetter || $0.isNumber || $0 == " " }) else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        p.arguments = ["-a", nome]
        do { try p.run() } catch { avviso = "\(nome) does not open from here. Open it from Launchpad." }
    }



    static func dettaglio(_ d: Diagnosi) -> String {
        var righe = ["SBK · \(d.stadio ?? d.passo ?? d.sorgente ?? "") · \(d.id)", "\(d.causa) \(d.rimedio)"]
        if let riga = d.riga, !riga.isEmpty { righe.append("Line: \(riga)") }
        if let log = d.log { righe.append("Log: \(log)" + (d.rc.map { " (exit \($0))" } ?? "")) }
        if let nota = d.nota, !nota.isEmpty { righe.append("Note: \(nota)") }
        return righe.joined(separator: "\n")
    }







    func apriAgente(testo: String) async {
        guard !apriAgenteInCorso, !modoIstantanea else { return }
        apriAgenteInCorso = true
        defer { apriAgenteInCorso = false }
        struct Esito: Decodable {
            let ok: Bool?
            let frase: String?
            let perche: String?
            let appunti: Bool?
            let testo: String?
        }
        let r = await motore.chiedi(["agente", testo])
        guard let e = try? JSONDecoder().decode(Esito.self, from: r.dati) else {

            avviso = "I don't know if the agent started. Check the terminal before trying again."
            return
        }
        if e.ok == true {
            avviso = nil
            notizia = e.frase ?? "I opened the agent on the terminal with the detail, it starts on its own."
            return
        }
        if e.appunti == true, let t = e.testo, !t.isEmpty {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(t, forType: .string)
        }
        avviso = e.perche ?? "I don't know if the agent started. Check the terminal before trying again."
    }

    func apriAgente(_ d: Diagnosi) async {
        await apriAgente(testo: Store.dettaglio(d))
    }




    var scarichiVivi: [Run] { stato?.scarichi_soli?.filter(\.vivo) ?? [] }



    func fermo(_ azione: Azione) -> String? {
        switch azione.tipo {
        case "da_sola":
            if lanciando { return "Starting." }
            guard let d = stato?.da_sola?[azione.arg ?? ""] else { return "Checking what's running, one moment." }
            return d.possibile ? nil : d.perche
        case "l0", "modo", "full", "full_completa", "stadio":
            guard occupato else { return nil }
            return daCache ? "Checking what's running, one moment." : (stato?.azioni.perche ?? "A run is already going.")
        case "pulisci_lock":
            return runVivo != nil || stato?.da_fuori.attivo == true ? "A run is going, its locks are live and not touched." : nil
        case "copia_per_claude":

            return apriAgenteInCorso ? "Opening the agent on the terminal." : nil
        case "riprendi":
            guard let r = stato?.ripresa else { return "There is no full run to resume." }
            if !r.possibile { return r.perche }
            return occupato ? (daCache ? "Checking what's running, one moment." : (stato?.azioni.perche ?? "A run is already going.")) : nil
        default:
            return nil
        }
    }

    func scaricaDaSola(_ sid: String) async {
        guard !lanciando else { return }
        lanciando = true
        defer { lanciando = false }
        avviso = nil
        await Avvisi.chiediPermesso()
        let r = await motore.chiedi(["scarica-fonte", sid])
        guard let esito = try? JSONDecoder().decode(Esito.self, from: r.dati) else {
            avviso = "The download did not start. The engine did not respond."
            return
        }
        if esito.ok != true { avviso = "The download did not start. " + (esito.errore ?? "") }
        await aggiorna()
    }


    func trascriviMemo() async {
        guard !lanciando else { return }
        lanciando = true
        defer { lanciando = false }
        avviso = nil
        await Avvisi.chiediPermesso()
        let r = await motore.chiedi(["trascrivi-memo"])
        guard let esito = try? JSONDecoder().decode(Esito.self, from: r.dati) else {
            avviso = "The transcription did not start. The engine did not respond."
            return
        }
        if esito.ok != true { avviso = "The transcription did not start. " + (esito.errore ?? "") }
        await aggiorna()
    }

    func fermaScarico(_ s: Run) async {
        let r = await motore.chiedi(["ferma-fonte", s.run_id])
        if let esito = try? JSONDecoder().decode(Esito.self, from: r.dati) {
            if esito.ok == true { fermoRichiesto.insert(s.run_id) } else { avviso = esito.errore }
        }
        await aggiorna()
    }


    func righeScarico(_ s: Run, n: Int = 40) async -> [String] {
        struct Righe: Decodable { let righe: [String]? }
        let r = await motore.chiedi(["log", s.run_id, "--righe", "\(n)"])
        return (try? JSONDecoder().decode(Righe.self, from: r.dati))?.righe ?? []
    }




    func pausa(_ run: Run) async {
        let r = await motore.chiedi(["pausa", run.run_id])
        if let esito = try? JSONDecoder().decode(Esito.self, from: r.dati), esito.ok != true {
            avviso = esito.errore
        }
        await aggiornaRun()
        await aggiorna()
    }

    func continua(_ run: Run) async {
        let r = await motore.chiedi(["continua", run.run_id])
        if let esito = try? JSONDecoder().decode(Esito.self, from: r.dati), esito.ok != true {
            avviso = esito.errore
        }
        await aggiornaRun()
        await aggiorna()
    }


    func rifaiStadio(_ s: Stadio) async {
        await lancia(tipo: "stadio", arg: s.id, consentiSpesa: s.pagato, spesa: s.pagato ? [s.id] : nil)
    }


    func riprendi(_ ripresa: Ripresa) async {
        await lancia(tipo: "riprendi", arg: ripresa.cartella, consentiSpesa: ripresa.spende)
    }




    func caricaVerifiche() async {
        let r = await motore.chiedi(["verifiche"])
        if let nuove = try? JSONDecoder().decode(Verifiche.self, from: r.dati), nuove.ok {
            verifiche = nuove
            erroreVerifiche = nil
        } else if verifiche == nil {
            erroreVerifiche = r.scaduto ? "The engine did not respond within a minute." : "The contacts to verify can't be read."
        }
    }


    func rispondi(_ caso: CasoVerifica, esito: String, email: String? = nil) async {
        let emails = email.map { [$0] } ?? caso.candidati.map(\.email)
        let r = await motore.chiedi(["verifica", caso.fonte, caso.chiave, esito] + emails)
        guard r.codice == 0 else {
            avviso = "The answer was not saved. The engine did not respond as it should."
            return
        }
        ultimaVerifica = caso
        if var v = verifiche {
            v.casi.removeAll { $0.id == caso.id }
            v.totale = max(0, v.totale - 1)
            verifiche = v

            if v.casi.count < 20, v.totale > v.casi.count { await caricaVerifiche() }
        }
        notizia = "Marked. It takes effect from the next contact-merge cycle."
    }

    func annullaUltimaVerifica() async {
        let r = await motore.chiedi(["verifica-annulla"])
        guard r.codice == 0 else {
            avviso = "I could not undo the last answer."
            return
        }
        ultimaVerifica = nil
        await caricaVerifiche()
        notizia = "Last answer undone, the contact is back in the list."
    }



    func caricaRegole() async {
        let r = await motore.chiedi(["regole"])
        if let nuove = try? JSONDecoder().decode(Regole.self, from: r.dati), nuove.ok == true {
            regole = nuove
            erroreRegole = nil
        } else if regole == nil {
            erroreRegole = r.scaduto ? "The engine did not respond within a minute." : "The rules can't be read. The engine did not respond as it should."
        }
    }



    func cercaNeiDati(_ domanda: String) async {
        let q = domanda.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !cercandoDati else { return }
        cercandoDati = true
        defer { cercandoDati = false }
        datiErrore = nil
        let r = await motore.chiedi(["cerca", q], scadenza: 300)
        let esito = try? JSONDecoder().decode(EsitoCerca.self, from: r.dati)
        datiDomanda = q
        datiRisultati = esito?.risultati ?? []
        datiSecondi = esito?.secondi
        if esito?.ok != true {
            datiErrore = esito?.errore ?? (r.scaduto ? "The search did not respond in time." : "The search failed.")
        }
    }


    func apriRegola(_ chiave: String, vista: VistaRegole) {
        ricerca = ""
        vistaRegole = vista
        soloDaSistemare = false
        regoleAperte.insert(chiave)
        sezione = .regole
        regolaVaiA = nil

        DispatchQueue.main.async { self.regolaVaiA = chiave }
    }

    func pulisci(_ run: Run) async {
        _ = await motore.chiedi(["pulisci", run.run_id])
        await aggiorna()
    }


    func preparaStima() async {
        erroreStima = nil
        let ultima = await motore.chiedi(["stima", "--ultima"])
        if let e = try? JSONDecoder().decode(EsitoStima.self, from: ultima.dati) { stima = e.stima }
        guard !(stato?.da_fuori.attivo ?? false), runVivo == nil else {
            erroreStima = "The pipeline is already running, the estimate recalculates when it finishes."
            return
        }
        stimaInCorso = true
        defer { stimaInCorso = false }
        let r = await motore.chiedi(["stima"], scadenza: 30 * 60)
        if let e = try? JSONDecoder().decode(EsitoStima.self, from: r.dati) {
            if e.ok == true, let s = e.stima {
                stima = s
            } else {
                erroreStima = e.errore ?? "The estimate did not arrive."
            }
        } else {
            erroreStima = r.scaduto ? "The count exceeded 30 minutes." : "The estimate did not arrive."
        }
    }


    func apri(_ voce: VoceMenu) {
        if voce.tipo == "full" {
            foglio = .fullRun
        } else if voce.spesa {
            apriSpesa(voce.tipo == "modo" ? voce.arg : voce.tipo)
        } else {
            foglio = .altroRun(voce)
        }
    }




    func apriSpesa(_ tipo: String = "full_completa") {
        spesaScelta = []
        foglio = .completa(tipo)
    }


    var chiavePaga: String? { stato?.chiavi?.first(where: { $0.paga == true })?.nome }

    func esegui(_ azione: Azione, oggetto: Oggetto? = nil) {
        switch azione.tipo {
        case "l0":



            if azione.lungo == true {
                foglio = .altroRun(VoceMenu(id: "l0-\(azione.arg ?? "")", tipo: "l0", arg: azione.arg ?? "",
                                            nome: azione.nome ?? azione.etichetta, frase: azione.frase ?? "",
                                            step: azione.step ?? "", spesa: false))
            } else {
                Task { await lancia(tipo: "l0", arg: azione.arg ?? "") }
            }
        case "da_sola":

            Task { await scaricaDaSola(azione.arg ?? "") }
        case "trascrivi_memo":
            Task { await trascriviMemo() }
        case "modo":
            if let voce = stato?.azioni.menu.first(where: { $0.arg == azione.arg && $0.tipo == "modo" }) {
                apri(voce)
            }
        case "full":
            foglio = .fullRun
        case "full_completa", "stima":
            apriSpesa()
        case "come_si_fa":
            let fonti = stato?.fonti ?? []
            if azione.arg == "a_mano" {

                let indietro = fonti.filter { $0.gruppo == "a_mano" && $0.salute != "ok" }
                foglio = .comeSiFa(indietro.isEmpty ? fonti.filter { $0.gruppo == "a_mano" } : indietro)
            } else if let f = fonti.first(where: { $0.id == azione.arg }) {
                foglio = .comeSiFa([f])
            }
        case "apri_run":
            sezione = .run
        case "copie":
            foglio = .copie
        case "verifiche":
            foglio = .verifiche
        case "strumenti":
            sezione = .strumenti
        case "riprendi":
            if let r = stato?.ripresa { foglio = .riprendi(r) }
        case "stadio":
            if let s = stato?.stadi.first(where: { $0.id == azione.arg }) { foglio = .stadio(s) }
        case "pulisci_lock":
            Task { await pulisciLock() }
        case "consenso_docusign":
            Task { await apriConsensoDocuSign() }
        case "apri_app":
            apriApp(azione.arg ?? "")
        case "apri_pagina":

            if let s = azione.arg, let url = URL(string: s), url.scheme == "https" { NSWorkspace.shared.open(url) }
        case "copia_per_claude":

            if let oggetto, oggetto.tipo == "fonte", let d = stato?.fonti.first(where: { $0.id == oggetto.id })?.diagnosi {
                Task { await apriAgente(d) }
            }
        default:
            if let oggetto { scegli(oggetto) }
        }
    }

    func scegli(_ oggetto: Oggetto) {
        switch oggetto.tipo {
        case "fonte":
            selezione = .fonte(oggetto.id)
        case "stadio":
            selezione = .stadio(oggetto.id)
            if let fase = stato?.fasi.first(where: { $0.stadi.contains(oggetto.id) }) { fasiChiuse.remove(fase.id) }
        case "fase":
            selezione = .fase(oggetto.id)
            fasiChiuse.remove(oggetto.id)
        case "gruppo":
            gruppiAperti.insert(oggetto.id)
            if let f = stato?.fonti.first(where: { $0.gruppo == oggetto.id && $0.salute != "ok" }) {
                selezione = .fonte(f.id)
            }
        case "run":
            sezione = .run
            return
        case "copie":
            foglio = .copie
            return
        case "strumenti":
            sezione = .strumenti
            return
        default:
            return
        }
        ispettore = true
    }

    func scegliCartella() {
        let pannello = NSOpenPanel()
        pannello.canChooseDirectories = true
        pannello.canChooseFiles = false
        pannello.allowsMultipleSelection = false
        pannello.message = "Choose the SBK folder"
        if pannello.runModal() == .OK, let url = pannello.url {
            radice = url.path
            Task { await aggiorna(fresco: true) }
        }
    }
}
