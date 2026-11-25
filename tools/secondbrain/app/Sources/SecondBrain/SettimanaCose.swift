import AppKit
import SwiftUI
import UniformTypeIdentifiers












extension KeyedDecodingContainer {
    fileprivate func f<T: Decodable>(_ chiave: Key) -> T? { (try? decodeIfPresent(T.self, forKey: chiave)) ?? nil }
}


struct ChiaveLibera: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
    init(_ s: String) { stringValue = s }
}

struct SettimanaCal: Decodable, Hashable {
    let id: String
    let scala: String
    let titolo: String?
    let prima: String?
    let dopo: String?
    let oggi: String?

    let fuso: String?
    let fuso_nome: String?
    let apri_al_minuto: Int?
    let ore_lavoro: OreLavoro?
    let giorni: [GiornoSett]
    let barre: [FasciaSett]
    let righe_tutto_il_giorno: Int?
    let calendari: [CalendarioSett]
    let rifiutati_nascosti: Int?
    let mostra_rifiutati: Bool?
    let aggiornati: AggiornatiSett?
    let da_ripianificare: [String]

    let indice: String?

    let testi: [String: String]?

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: ChiaveLibera.self)
        id = try c.decode(String.self, forKey: .init("id"))
        scala = c.f(.init("scala")) ?? "settimana"
        titolo = c.f(.init("titolo"))
        prima = c.f(.init("prima"))
        dopo = c.f(.init("dopo"))
        oggi = c.f(.init("oggi"))
        fuso = c.f(.init("fuso"))
        fuso_nome = c.f(.init("fuso_nome"))
        apri_al_minuto = c.f(.init("apri_al_minuto"))
        ore_lavoro = c.f(.init("ore_lavoro"))
        giorni = (c.f(.init("giorni")) as [Facoltativo<GiornoSett>]?)?.compactMap(\.valore) ?? []
        barre = (c.f(.init("barre")) as [Facoltativo<FasciaSett>]?)?.compactMap(\.valore) ?? []
        righe_tutto_il_giorno = c.f(.init("righe_tutto_il_giorno"))
        calendari = (c.f(.init("calendari")) as [Facoltativo<CalendarioSett>]?)?.compactMap(\.valore) ?? []
        rifiutati_nascosti = c.f(.init("rifiutati_nascosti"))
        mostra_rifiutati = c.f(.init("mostra_rifiutati"))
        aggiornati = c.f(.init("aggiornati"))
        da_ripianificare = c.f(.init("da_ripianificare")) ?? []
        indice = c.f(.init("indice"))
        testi = c.f(.init("testi"))
    }
}


struct Facoltativo<T: Decodable>: Decodable {
    let valore: T?
    init(from d: Decoder) throws { valore = try? T(from: d) }
}

struct OreLavoro: Decodable, Hashable {
    let dalle: Int?
    let alle: Int?
    let giorni: [Int]?
}

struct GiornoSett: Decodable, Hashable, Identifiable {
    let giorno: String
    let nome: String
    let numero: Int
    let oggi: Bool
    let passato: Bool

    let festivo: Bool
    let quando: String

    let scadenze: [String]

    let pianificate: [String]
    let tutto_il_giorno: [FasciaSett]

    let righe: Int
    let blocchi: [BloccoSett]
    let minuti_task: Int
    let minuti_giornata: Int
    var id: String { giorno }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: ChiaveLibera.self)
        giorno = try c.decode(String.self, forKey: .init("giorno"))
        nome = c.f(.init("nome")) ?? ""
        numero = c.f(.init("numero")) ?? Int(giorno.suffix(2)) ?? 0
        oggi = c.f(.init("oggi")) ?? false
        passato = c.f(.init("passato")) ?? false
        festivo = c.f(.init("festivo")) ?? false
        quando = c.f(.init("quando")) ?? giorno
        scadenze = c.f(.init("scadenze")) ?? []
        pianificate = c.f(.init("pianificate")) ?? []
        tutto_il_giorno = (c.f(.init("tutto_il_giorno")) as [Facoltativo<FasciaSett>]?)?.compactMap(\.valore) ?? []
        righe = c.f(.init("righe")) ?? 0
        blocchi = (c.f(.init("blocchi")) as [Facoltativo<BloccoSett>]?)?.compactMap(\.valore) ?? []
        minuti_task = c.f(.init("minuti_task")) ?? 0
        minuti_giornata = c.f(.init("minuti_giornata")) ?? 0
    }
}


struct DettagliEvento: Hashable {
    var risposta: String?
    var aiuto: String?

    var colore: String?
    var link: String?
    var video: String?

    var tipo_evento: String?
    var incerto: Bool?
    var libero: Bool?
    var luogo: Bool?
    var serie: String?

    init() {}
    init(_ c: KeyedDecodingContainer<ChiaveLibera>) {
        risposta = c.f(.init("risposta"))
        aiuto = c.f(.init("aiuto"))
        colore = c.f(.init("colore"))
        link = c.f(.init("link"))
        video = c.f(.init("video"))
        tipo_evento = c.f(.init("tipo_evento"))
        incerto = c.f(.init("incerto"))
        libero = c.f(.init("libero"))
        luogo = c.f(.init("luogo"))
        serie = c.f(.init("serie"))
    }
}



struct FasciaSett: Decodable, Hashable {
    let id: String
    let titolo: String
    let cal: String?
    let riga: Int
    let dal: Int?
    let al: Int?
    let continua_prima: Bool
    let continua_dopo: Bool

    let ora: String?
    let ev: DettagliEvento

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: ChiaveLibera.self)
        id = try c.decode(String.self, forKey: .init("id"))
        titolo = c.f(.init("titolo")) ?? ""
        cal = c.f(.init("cal"))
        riga = c.f(.init("riga")) ?? 0
        dal = c.f(.init("dal"))
        al = c.f(.init("al"))
        continua_prima = c.f(.init("continua_prima")) ?? false
        continua_dopo = c.f(.init("continua_dopo")) ?? false
        ora = c.f(.init("ora"))
        ev = DettagliEvento(c)
    }
}

struct BloccoSett: Decodable, Hashable {

    let tipo: String
    let id: String
    var titolo: String?
    var cal: String?

    var da: Int
    var a: Int
    var fine_vera: Int?
    var colonna: Int
    var colonne: Int
    var ampiezza: Int
    var continua_prima: Bool
    var continua_dopo: Bool

    var ora: String?
    var ora_fine: String?
    var durata_detta: Bool?
    var sovrapposta: Bool?
    var oltre_scadenza: Bool?
    var ev: DettagliEvento

    var chiave: String { "\(tipo)-\(id)-\(da)" }
    var task: Bool { tipo == "task" }
    var aiuto: String? { ev.aiuto }
    var risposta: String? { ev.risposta }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: ChiaveLibera.self)
        tipo = c.f(.init("tipo")) ?? "evento"
        id = try c.decode(String.self, forKey: .init("id"))
        titolo = c.f(.init("titolo"))
        cal = c.f(.init("cal"))
        da = try c.decode(Int.self, forKey: .init("da"))
        a = c.f(.init("a")) ?? (da + 15)
        fine_vera = c.f(.init("fine_vera"))
        colonna = c.f(.init("colonna")) ?? 0
        colonne = max(1, c.f(.init("colonne")) ?? 1)
        ampiezza = max(1, c.f(.init("ampiezza")) ?? 1)
        continua_prima = c.f(.init("continua_prima")) ?? false
        continua_dopo = c.f(.init("continua_dopo")) ?? false
        ora = c.f(.init("ora"))
        ora_fine = c.f(.init("ora_fine"))
        durata_detta = c.f(.init("durata_detta"))
        sovrapposta = c.f(.init("sovrapposta"))
        oltre_scadenza = c.f(.init("oltre_scadenza"))
        ev = DettagliEvento(c)
    }


    func spostato(da nuovoDa: Int, a nuovoA: Int) -> BloccoSett {
        var b = self
        b.da = nuovoDa
        b.a = nuovoA
        b.fine_vera = nuovoA
        b.colonna = 0
        b.colonne = 1
        b.ampiezza = 1
        b.ora = Store.oraBreve(nuovoDa)
        b.ora_fine = Store.oraBreve(nuovoA)
        b.sovrapposta = false
        return b
    }
}

struct CalendarioSett: Decodable, Hashable, Identifiable {
    let id: String
    let nome: String

    let casella: String?
    let colore: String?
    let testo: String?
    let primario: Bool?
    let visibile: Bool?
    let n: Int?

    let da_google: Bool?
}

struct ErroreCalendario: Decodable, Hashable {
    let casella: String?
    let nome: String?
    let frase: String
    let motivo: String?
}

struct CasellaCalendario: Decodable, Hashable {
    let casella: String?
    let nome: String?
    let ultima: String?
    let esito: String?
    let frase: String?
    let motivo: String?
}

struct AggiornatiSett: Decodable, Hashable {
    let frase: String?
    let vecchi: Bool?
    let in_corso: Bool?
    let indice_in_corso: Bool?
    let scarico_altrui: Bool?
    let ultima: String?
    let soglia_minuti: Int?
    let errori: [ErroreCalendario]?
    let caselle: [CasellaCalendario]?
}


private struct PaginaSettimana: Decodable {
    let settimana: Facoltativo<SettimanaCal>?
    let settimana_errore: String?
    let testi_calendario: [String: String]?
    let schede: [Facoltativo<ScalaVista>]?
}


private struct ScalaVista: Decodable {
    let id: String
    let scala: String?
}


struct StatoCalendari: Decodable {
    let ok: Bool
    let in_corso: Bool?
    let indice_in_corso: Bool?
    let gia: Bool?
    let errore: String?
    let messaggio: String?
    let ultimo_tasto: UltimoTasto?

    struct UltimoTasto: Decodable {
        let esito: String?
        let finito: String?
        let frase: String?
    }
}


struct BucoSett: Decodable, Hashable {
    let inizio: String
    let fine: String?

    let pianifica: String?
    let frase: String
}

struct RispostaBuchi: Decodable {
    let ok: Bool?
    let buchi: [BucoSett]?
    let messaggio: String?
    let errore: String?
}



enum FintiSettimana {
    private static let pagina: PaginaSettimana? = {
        guard let f = ProcessInfo.processInfo.environment["SB_SETTIMANA_FINTA"],
              let dati = try? Data(contentsOf: URL(fileURLWithPath: f)) else { return nil }
        return try? JSONDecoder().decode(PaginaSettimana.self, from: dati)
    }()
    static var settimana: SettimanaCal? { pagina?.settimana?.valore }
    static var testi: [String: String]? { pagina?.testi_calendario }
    static let scala: String? = ProcessInfo.processInfo.environment["SB_SCALA"]
}





struct PosizioneInVolo: Equatable {
    let giorno: String
    let da: Int
    let a: Int

    var quando = Date()
}

@MainActor
@Observable
final class StatoSettimana {
    static let condiviso = StatoSettimana()


    var dati: SettimanaCal?

    var testi: [String: String] = [:]

    var errore: String?

    var scale: [String: String] = [:]

    var giorno: String?

    var scalaScelta: String?
    var inVolo: [String: PosizioneInVolo] = [:]

    var aggiorna = false

    var aspettaIndice = false

    @ObservationIgnored var aggiornateAllApertura: Set<String> = []

    @ObservationIgnored var cornici: [String: CGRect] = [:]
}



extension Store {

    var settimanaVista: SettimanaCal? {
        if modoIstantanea, let f = FintiSettimana.settimana { return f }
        return StatoSettimana.condiviso.dati
    }


    var scalaCalendario: String {
        let st = StatoSettimana.condiviso
        if let s = st.scalaScelta { return s }
        if modoIstantanea, let s = FintiSettimana.scala { return s }
        return st.scale[coseVista] ?? "mese"
    }


    var giornoSettimana: String { StatoSettimana.condiviso.giorno ?? oggiNelFuso() }




    var argomentiSettimana: [String] {

        guard !modoIstantanea || FintiSettimana.settimana == nil, !vistaSpeciale, let s = schedaCose, s.modo == "calendario"
        else { return [] }
        let scala = scalaCalendario
        guard scala == "giorno" || scala == "settimana" else { return [] }
        return ["--settimana", giornoSettimana] + (scala == "giorno" ? ["--giorno"] : []) + ["--vista", s.id]
    }



    func assorbiSettimana(_ dati: Data, partita: Date = .distantFuture, chiesta: Bool = false) {
        guard let p = try? JSONDecoder().decode(PaginaSettimana.self, from: dati) else { return }
        let st = StatoSettimana.condiviso
        if let t = p.testi_calendario { st.testi = t }
        if let schede = p.schede {
            var scale: [String: String] = [:]
            for s in schede.compactMap(\.valore) { scale[s.id] = s.scala ?? "mese" }
            if scale != st.scale { st.scale = scale }
        }
        if let s = p.settimana?.valore {
            st.dati = s
            st.errore = nil

            st.inVolo = st.inVolo.filter { $0.value.quando > partita }
            if st.scalaScelta == s.scala || st.scale[coseVista] == st.scalaScelta { st.scalaScelta = nil }
        } else if let e = p.settimana_errore {
            st.errore = e
            st.inVolo = [:]
        } else if chiesta {


            st.errore = settimanaNonArrivata
            st.inVolo = [:]
        }
    }



    var settimanaNonArrivata: String {
        cose?.testi?["settimana_non_arrivata"] ?? "The week hasn't arrived."
    }


    var settimanaGiusta: Bool {
        guard let s = settimanaVista else { return false }
        return s.scala == scalaCalendario && s.giorni.contains { $0.giorno == giornoSettimana }
    }


    func oggiNelFuso() -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: settimanaVista?.fuso ?? "UTC") ?? .current
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }


    func ts(_ chiave: String) -> String {
        if let s = settimanaVista?.testi?[chiave] { return s }
        if modoIstantanea, let s = FintiSettimana.testi?[chiave] { return s }
        return StatoSettimana.condiviso.testi[chiave] ?? t(chiave)
    }


    func breve(_ minuti: Int) -> String {


        if minuti < 60 {
            return ts("breve_minuti").replacingOccurrences(of: "{m}", with: minuti.formatted()).replacingOccurrences(of: "{n}", with: minuti.formatted())
        }
        let h = minuti / 60, m = minuti % 60
        if m == 0 {
            let modello = ts("breve_ore").isEmpty ? ts("breve_ore_tonde") : ts("breve_ore")
            return modello.replacingOccurrences(of: "{h}", with: h.formatted())
        }
        return ts("breve_ore_minuti").replacingOccurrences(of: "{h}", with: h.formatted())
            .replacingOccurrences(of: "{mm}", with: String(format: "%02d", m))
    }



    nonisolated static func chiusa(_ v: VoceCosa) -> Bool { v.chiusaOra }


    func aiutoCerchio(_ v: VoceCosa) -> String {
        let chiave = Self.chiusa(v) ? "aiuto_cerchio_chiusa" : "aiuto_cerchio_aperta"
        let modello = t(chiave)
        guard modello != chiave else { return t("aiuto_cerchio_\(v.stato ?? "da_fare")") }
        return modello.replacingOccurrences(of: "{nome}", with: v.stato_nome ?? "")
    }



    func parolaCassetto(scadute: Int, senza: Int) -> String {
        let unisci = t("cassetto_unisci")
        guard !unisci.isEmpty else {
            return t("cassetto_chiuso").replacingOccurrences(of: "{s}", with: scadute.formatted())
                .replacingOccurrences(of: "{n}", with: senza.formatted())
        }
        let a = scadute == 1 ? t("cassetto_scaduta") : t("cassetto_scadute").replacingOccurrences(of: "{n}", with: scadute.formatted())
        let b = t("cassetto_senza").replacingOccurrences(of: "{n}", with: senza.formatted())
        return unisci.replacingOccurrences(of: "{a}", with: a).replacingOccurrences(of: "{b}", with: b)
    }


    func pianifica(ids: [String], quando: String, durata: Int?) async {
        var valori = [quando]
        if let durata { valori += ["--durata", "\(durata)"] }
        await gestoTask("pianifica", ids, valori)
    }


    func togliDalTempo(_ ids: [String]) async {
        await pianifica(ids: ids, quando: "togli", durata: nil)
    }



    func cambiaSettimana(_ passo: Int) {
        guard let s = settimanaVista, let g = passo < 0 ? s.prima : s.dopo else { return }
        StatoSettimana.condiviso.giorno = g
    }


    func settimanaDiOggi() {
        StatoSettimana.condiviso.giorno = nil
    }



    func scegliScala(_ scala: String, giorno: String? = nil) {
        let st = StatoSettimana.condiviso
        st.scalaScelta = scala
        if let giorno { st.giorno = giorno }
        guard !modoIstantanea, let v = schedaCose, !vistaSpeciale else { return }
        Task { await gestoVista(["vista-imposta", v.id, "scala", "\"\(scala)\""], annullabile: false) }
    }


    func mostraCalendario(_ id: String, _ si: Bool) {
        guard !modoIstantanea, let v = schedaCose, let s = settimanaVista else { return }
        var nascosti = Set(s.calendari.filter { $0.visibile == false }.map(\.id))
        if si { nascosti.remove(id) } else { nascosti.insert(id) }
        let json = (try? String(data: JSONEncoder().encode(nascosti.sorted()), encoding: .utf8)) ?? "[]"
        Task { await gestoVista(["vista-imposta", v.id, "calendari_nascosti", json], annullabile: false) }
    }


    func mostraRifiutati(_ si: Bool) {
        guard !modoIstantanea, let v = schedaCose else { return }
        Task { await gestoVista(["vista-imposta", v.id, "rifiutati", si ? "true" : "false"], annullabile: false) }
    }



    func aggiornaCalendari() {
        let st = StatoSettimana.condiviso
        guard !modoIstantanea, !st.aggiorna else { return }
        st.aggiorna = true
        Task { @MainActor in
            defer { st.aggiorna = false }
            let r = try? JSONDecoder().decode(StatoCalendari.self,
                                              from: await motore.chiedi(["cose", "calendario-aggiorna"], scadenza: 20).dati)
            guard let r, r.ok else {
                coseEsito = EsitoRiga(testo: r?.errore ?? t("errore_motore"), errore: true)
                return
            }
            let fine = r.in_corso == true ? await aspettaCalendari() : nil
            if let f = fine?.ultimo_tasto, let frase = f.frase {
                coseEsito = EsitoRiga(testo: frase, errore: f.esito != "ok")
            }
            await caricaCose()
        }
    }



    func aspettaCalendari() async -> StatoCalendari? {
        var ultimo: StatoCalendari?
        for _ in 0..<90 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            let s = try? JSONDecoder().decode(StatoCalendari.self,
                                              from: await motore.chiedi(["cose", "calendario-stato"], scadenza: 15).dati)
            ultimo = s
            if s == nil || (s?.in_corso != true && s?.indice_in_corso != true) { break }
        }
        return ultimo
    }



    func aggiornaSeVecchi() {
        guard !modoIstantanea, let s = settimanaVista else { return }
        let st = StatoSettimana.condiviso
        if s.aggiornati?.vecchi == true, s.aggiornati?.in_corso != true, !st.aggiornateAllApertura.contains(s.id) {
            st.aggiornateAllApertura.insert(s.id)
            aggiornaCalendari()
            return
        }
        if s.indice == "rifacendo" || s.aggiornati?.indice_in_corso == true, !st.aspettaIndice, !st.aggiorna {
            st.aspettaIndice = true
            Task { @MainActor in
                _ = await aspettaCalendari()
                await caricaCose()
                st.aspettaIndice = false
            }
        }
    }


    func buchi(per id: String) async -> RispostaBuchi {
        guard !modoIstantanea else { return RispostaBuchi(ok: true, buchi: [], messaggio: nil, errore: nil) }
        let vista = schedaCose.map { ["--vista", $0.id] } ?? []
        let r = await motore.chiedi(["cose", "buchi", id] + vista, scadenza: 15)
        return (try? JSONDecoder().decode(RispostaBuchi.self, from: r.dati))
            ?? RispostaBuchi(ok: false, buchi: nil, messaggio: nil, errore: t("errore_motore"))
    }



    func nuovaAllOra(_ giorno: String, _ minuto: Int) {
        nuovaQui("pianificata", "\(giorno)T\(Self.oraDi(minuto))")
    }


    func nomeQuiSettimana(_ campo: String, _ valore: String) -> String? {
        guard campo == "pianificata", valore.count >= 16 else { return nil }
        let giorno = String(valore.prefix(10))
        let minuti = (Int(valore.dropFirst(11).prefix(2)) ?? 0) * 60 + (Int(valore.dropFirst(14).prefix(2)) ?? 0)
        let quando = settimanaVista?.giorni.first { $0.giorno == giorno }?.quando ?? giorno


        let modello = !ts("nuova_alle").isEmpty ? ts("nuova_alle") : t("quando_alle")
        return modello.replacingOccurrences(of: "{quando}", with: quando).replacingOccurrences(of: "{giorno}", with: quando)
            .replacingOccurrences(of: "{ora}", with: Self.oraBreve(minuti))
    }


    nonisolated static func oraDi(_ minuto: Int) -> String {
        let m = max(0, min(minuto, 24 * 60))
        return String(format: "%02d:%02d", m / 60, m % 60)
    }


    nonisolated static func oraBreve(_ minuto: Int) -> String {
        let m = max(0, min(minuto, 24 * 60))
        return String(format: "%d:%02d", m / 60, m % 60)
    }
}



enum MisureSettimana {

    static let ora: CGFloat = 48
    static let giorno: CGFloat = ora * 24
    static let colonnaOre: CGFloat = 52
    static let rigaFascia: CGFloat = 20

    static let righeFascia = 3

    static let scatto = 15

    static func y(_ minuto: Int) -> CGFloat { CGFloat(minuto) / 60 * ora }

    static let bloccoConCerchio: CGFloat = 34
    static let bloccoOraAccanto: CGFloat = 90
    static let bloccoDueRighe: CGFloat = 64
    static func minuti(_ y: CGFloat) -> Int { Int((y / ora * 60).rounded()) }
    static func scatta(_ minuti: Int) -> Int { Int((Double(minuti) / Double(scatto)).rounded()) * scatto }

    static func scattaGiu(_ minuti: Int) -> Int { (max(0, minuti) / scatto) * scatto }
}

extension Color {

    static func esadecimale(_ s: String?) -> Color? {
        guard var h = s?.trimmingCharacters(in: .whitespaces), !h.isEmpty else { return nil }
        if h.hasPrefix("#") { h.removeFirst() }
        guard h.count == 6, let v = UInt32(h, radix: 16) else { return nil }
        return Color(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}


func idsDaTesto(_ valori: [String]) -> [String] {
    valori.flatMap { $0.split(separator: ",").map(String.init) }.filter { !$0.isEmpty && !$0.hasPrefix("vista:") }
}




struct SceltaScala: View {
    let cose: Cose
    let store: Store
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        Picker("", selection: Binding(get: { store.scalaCalendario }, set: { nuova in
            withAnimation(Movimento.cambio(ridotto)) { store.scegliScala(nuova) }
        })) {
            Text(store.ts("scala_giorno")).tag("giorno")
            Text(store.ts("scala_settimana")).tag("settimana")
            Text(store.ts("scala_mese")).tag("mese")
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .controlSize(.small)
        .fixedSize()
        .help(store.ts("aiuto_scala"))
    }
}


struct CalendarioScala: View {
    let cose: Cose
    let store: Store

    var body: some View {
        switch store.scalaCalendario {
        case "giorno", "settimana": SettimanaCose(cose: cose, store: store)
        default: CalendarioCose(cose: cose, store: store)
        }
    }
}



struct SettimanaCose: View {
    let cose: Cose
    let store: Store
    @State private var larghezza: CGFloat = 1000
    @State private var fasciaAperta = false
    @FocusState private var fuoco: Bool
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        let righe = store.disposizione().flatMap(\.righe)
        let oggi = store.settimanaVista?.oggi ?? store.oggiNelFuso()
        let scadute = righe.filter { ($0.giorno ?? "9") < oggi && $0.giorno != nil }
            .sorted { ($0.oPriorita, $0.giorno ?? "") < ($1.oPriorita, $1.giorno ?? "") }
        let senza = righe.filter { $0.giorno == nil }.sorted { $0.oPriorita < $1.oPriorita }
        let cassetto = store.coseCassetto ?? (larghezza >= 1000)
        VStack(alignment: .leading, spacing: 8) {
            if let s = store.settimanaVista, !s.giorni.isEmpty {
                TestaSettimana(cose: cose, store: store, settimana: s, cassetto: cassetto,
                               scadute: scadute.count, senza: senza.count)
                HStack(alignment: .top, spacing: 12) {
                    if cassetto {
                        CassettoSettimana(cose: cose, store: store, scadute: scadute, senza: senza,
                                          daRipianificare: s.da_ripianificare.compactMap { store.coseIndice[$0] })
                            .frame(width: 248)
                            .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("settimana")) } action: {
                                StatoSettimana.condiviso.cornici["cassetto"] = $0
                            }
                            .transition(ridotto ? .opacity : .move(edge: .leading).combined(with: .opacity))
                    }
                    GrigliaSettimana(cose: cose, store: store, settimana: s, fasciaAperta: $fasciaAperta)
                }
            } else {


                TestaVuotaSettimana(cose: cose, store: store)
                if let e = StatoSettimana.condiviso.errore, !store.modoIstantanea || ProcessInfo.processInfo.environment["SB_SETT_ERRORE"] != nil {
                    HStack(spacing: 10) {
                        Label(e, systemImage: Simbolo.attenzione).font(.system(size: 12)).foregroundStyle(.secondary)

                        Button {
                            StatoSettimana.condiviso.errore = nil
                            Task { await store.caricaCose() }
                        } label: {
                            if store.t("riprova").isEmpty { Image(systemName: "arrow.clockwise") } else { Text(store.t("riprova")) }
                        }
                        .buttonStyle(.link).font(.system(size: 12))
                    }
                    .frame(maxWidth: .infinity, alignment: .center).padding(.top, 40)
                    Spacer()
                } else {
                    RigheFerme()
                }
            }
        }
        .padding(12)
        .coordinateSpace(.named("settimana"))
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezza = $0 }
        .focusable()
        .focusEffectDisabled()
        .focused($fuoco)
        .onKeyPress(keys: [.leftArrow, .rightArrow], phases: .down) { k in
            guard k.modifiers.isEmpty else { return .ignored }
            store.cambiaSettimana(k.key == .leftArrow ? -1 : 1)
            return .handled
        }
        .onKeyPress(characters: CharacterSet(charactersIn: "jkt"), phases: .down) { k in
            guard k.modifiers.isEmpty else { return .ignored }
            switch k.characters {
            case "j": store.cambiaSettimana(1)
            case "k": store.cambiaSettimana(-1)
            default: store.settimanaDiOggi()
            }
            return .handled
        }
        .task(id: "\(store.coseVista)|\(store.giornoSettimana)|\(store.scalaCalendario)") {


            guard !store.modoIstantanea else { return }
            if !store.settimanaGiusta { await store.caricaCose() }
            store.aggiornaSeVecchi()
        }
    }
}


private struct TestaVuotaSettimana: View {
    let cose: Cose
    let store: Store

    var body: some View {
        HStack {
            Spacer()
            SceltaScala(cose: cose, store: store)
        }
    }
}



struct TestaSettimana: View {
    let cose: Cose
    let store: Store
    let settimana: SettimanaCal
    let cassetto: Bool
    let scadute: Int
    let senza: Int
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        let giorno = settimana.scala == "giorno" || store.scalaCalendario == "giorno"
        HStack(alignment: .center, spacing: 10) {
            Button {
                withAnimation(Movimento.cambio(ridotto)) { store.coseCassetto = !cassetto }
            } label: {

                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 4) {
                        Image(systemName: "sidebar.left")
                        if !cassetto {
                            Text(store.parolaCassetto(scadute: scadute, senza: senza))
                                .font(.system(size: 11)).monospacedDigit().lineLimit(1).fixedSize()
                        }
                    }
                    Image(systemName: "sidebar.left")
                }
            }
            .buttonStyle(.borderless)
            .help(cassetto ? cose.t("aiuto_cassetto")
                  : cose.t("aiuto_cassetto_chiuso") + " " + store.parolaCassetto(scadute: scadute, senza: senza))
            VStack(alignment: .leading, spacing: 1) {
                Text(settimana.titolo ?? "").font(Testo.titoloSezione).lineLimit(1)
                aggiornamento
            }
            .layoutPriority(1)
            Spacer(minLength: 8)
            ViewThatFits(in: .horizontal) {
                comandi(pieni: true)
                comandi(pieni: false)
            }
            HStack(spacing: 2) {
                Button { store.cambiaSettimana(-1) } label: { Image(systemName: "chevron.left") }
                    .help(store.ts(giorno ? "aiuto_giorno_prima" : "aiuto_settimana_prima"))
                Button(store.ts("oggi")) { store.settimanaDiOggi() }
                    .help(store.ts("aiuto_settimana_oggi"))
                    .disabled(settimana.giorni.contains { $0.oggi })
                Button { store.cambiaSettimana(1) } label: { Image(systemName: "chevron.right") }
                    .help(store.ts(giorno ? "aiuto_giorno_dopo" : "aiuto_settimana_dopo"))
            }
            .buttonStyle(.borderless)
            .fixedSize()
        }
        .frame(minHeight: 32)
    }



    @ViewBuilder
    private var aggiornamento: some View {
        if let a = settimana.aggiornati {
            let lavora = a.in_corso == true || StatoSettimana.condiviso.aggiorna
            HStack(spacing: 6) {
                if lavora { ProgressView().controlSize(.mini) }
                Text(lavora && a.in_corso != true ? store.ts("aggiornati_in_corso") : (a.frase ?? ""))
                    .foregroundStyle(a.vecchi == true && !lavora ? Salute.attenzione.colore : .secondary)
                ForEach(a.errori ?? [], id: \.self) { e in
                    Label(e.frase, systemImage: Simbolo.attenzione)
                        .foregroundStyle(Salute.attenzione.colore)
                        .help(e.motivo ?? e.frase)
                }
            }
            .font(.system(size: 11))
            .lineLimit(1)
        }
    }

    @ViewBuilder
    private func comandi(pieni: Bool) -> some View {
        HStack(spacing: 10) {
            MenuCalendari(store: store, settimana: settimana, pieno: pieni)
            Button { store.aggiornaCalendari() } label: {
                if pieni { Label(store.ts("aggiorna"), systemImage: Simbolo.aggiorna) } else { Image(systemName: Simbolo.aggiorna) }
            }
            .buttonStyle(.borderless)
            .disabled(StatoSettimana.condiviso.aggiorna || settimana.aggiornati?.in_corso == true)
            .help(store.ts("aiuto_aggiorna"))
            SceltaScala(cose: cose, store: store)
        }
        .font(.system(size: 12))
        .fixedSize()
    }
}



struct MenuCalendari: View {
    let store: Store
    let settimana: SettimanaCal
    var pieno = true

    var body: some View {
        let calendari = settimana.calendari
        let caselle = calendari.reduce(into: [String]()) { if !$0.contains($1.casella ?? "") { $0.append($1.casella ?? "") } }
        Menu {
            ForEach(caselle, id: \.self) { casella in
                Section(casella) {
                    ForEach(calendari.filter { ($0.casella ?? "") == casella }) { c in
                        Toggle(isOn: Binding(get: { c.visibile != false }, set: { store.mostraCalendario(c.id, $0) })) {
                            Label {
                                Text(c.nome)
                            } icon: {
                                Image(nsImage: Self.pallino(Color.esadecimale(c.colore) ?? .accentColor))
                            }
                        }
                    }
                }
            }
            Divider()
            Toggle(store.ts("mostra_rifiutati"), isOn: Binding(get: { settimana.mostra_rifiutati == true },
                                                              set: { store.mostraRifiutati($0) }))
        } label: {
            if pieno { Label(store.ts("calendari"), systemImage: "calendar") } else { Image(systemName: "calendar") }
        }
        .menuStyle(.button).buttonStyle(.borderless).menuIndicator(pieno ? .visible : .hidden).fixedSize()
        .help(store.ts("aiuto_calendari"))
    }


    static func pallino(_ c: Color) -> NSImage {
        let img = NSImage(size: NSSize(width: 10, height: 10), flipped: false) { r in
            NSColor(c).setFill()
            NSBezierPath(ovalIn: r.insetBy(dx: 1, dy: 1)).fill()
            return true
        }
        img.isTemplate = false
        return img
    }
}



struct GrigliaSettimana: View {
    let cose: Cose
    let store: Store
    let settimana: SettimanaCal
    @Binding var fasciaAperta: Bool
    @State private var larghezza: CGFloat = 800
    @State private var anteprima: AnteprimaOra?
    @State private var apertaPer: String = ""

    @State private var oraVista: String?

    @State private var posizione = ScrollPosition(edge: .top)

    init(cose: Cose, store: Store, settimana: SettimanaCal, fasciaAperta: Binding<Bool>) {
        self.cose = cose
        self.store = store
        self.settimana = settimana
        _fasciaAperta = fasciaAperta
        _oraVista = State(initialValue: Self.oraDaAprire(settimana))
        _apertaPer = State(initialValue: settimana.id)
    }

    var body: some View {
        let giorni = settimana.giorni
        let colonna = max(20, (larghezza - MisureSettimana.colonnaOre) / CGFloat(max(giorni.count, 1)))
        let calendari = Dictionary(settimana.calendari.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        VStack(spacing: 0) {
            TesteGiorni(store: store, settimana: settimana, colonna: colonna)
            FasciaTuttoIlGiorno(cose: cose, store: store, settimana: settimana, calendari: calendari, colonna: colonna,
                                aperta: $fasciaAperta)
                .onGeometryChange(for: CGRect.self) { $0.frame(in: .named("settimana")) } action: {
                    StatoSettimana.condiviso.cornici["fascia"] = $0
                }
            Rectangle().fill(Superficie.separatore).frame(height: 0.5)
            ScrollView(.vertical) {
                ZStack(alignment: .topLeading) {

                    SfondoGriglia(giorni: giorni, colonna: colonna, ore: settimana.ore_lavoro)
                    ForEach(Array(giorni.enumerated()), id: \.element.giorno) { i, g in
                        ForEach(blocchi(g, giorni), id: \.chiave) { b in
                            let x = MisureSettimana.colonnaOre + CGFloat(i) * colonna
                            if b.task {
                                BloccoTaskSett(cose: cose, store: store, blocco: b, giorni: giorni, indice: i, colonna: colonna)
                                    .posizionato(b, x: x, colonna: colonna)
                            } else {
                                BloccoEventoSett(store: store, blocco: b, calendario: calendari[b.cal ?? ""], colonna: colonna)
                                    .posizionato(b, x: x, colonna: colonna)
                            }
                        }
                    }
                    if let i = giorni.firstIndex(where: \.oggi) {
                        LineaAdesso(fuso: settimana.fuso)
                            .frame(width: colonna)
                            .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna)
                    }
                    if let a = anteprima {
                        AnteprimaOraVista(anteprima: a)
                            .frame(width: colonna - 4)
                            .offset(x: MisureSettimana.colonnaOre + CGFloat(a.giorno) * colonna + 2, y: MisureSettimana.y(a.minuto) - 9)
                            .allowsHitTesting(false)
                    }
                }


                .frame(maxWidth: .infinity, minHeight: MisureSettimana.giorno, maxHeight: MisureSettimana.giorno, alignment: .topLeading)
                .contentShape(Rectangle())
                .onTapGesture(count: 2, coordinateSpace: .local) { p in
                    guard let (i, m) = punto(p, giorni: giorni, colonna: colonna) else { return }
                    store.nuovaAllOra(giorni[i].giorno, MisureSettimana.scattaGiu(m))
                }
                .onDrop(of: [.plainText, .utf8PlainText, .text],
                        delegate: LasciaSulTempo(giorni: giorni, colonna: colonna, anteprima: $anteprima) { ids, i, m in
                            Task { await store.pianifica(ids: ids, quando: "\(giorni[i].giorno)T\(Store.oraDi(m))", durata: nil) }
                        })
                .help(store.ts("aiuto_griglia"))
            }
            .scrollIndicators(.automatic)
            .scrollPosition($posizione)
            .task(id: settimana.id) {


                guard apertaPer != settimana.id || oraVista != nil else { return }
                let y = Self.yDaAprire(settimana)
                apertaPer = settimana.id
                oraVista = nil
                for attesa in [0, 60, 150, 300, 500] as [UInt64] {
                    try? await Task.sleep(nanoseconds: attesa * 1_000_000)
                    posizione.scrollTo(y: y)
                }
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezza = $0 }
        .background(Superficie.scheda)
        .clipShape(RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous).strokeBorder(Superficie.bordo, lineWidth: 1))
    }



    static func oraDaAprire(_ s: SettimanaCal) -> String {
        "ora-\(max(0, min(23, (s.apri_al_minuto ?? 480) / 60)))"
    }


    static func yDaAprire(_ s: SettimanaCal) -> CGFloat {
        let h = max(0, min(23, (s.apri_al_minuto ?? 480) / 60))
        return max(0, CGFloat(h) * MisureSettimana.ora - 12)
    }


    private func blocchi(_ g: GiornoSett, _ giorni: [GiornoSett]) -> [BloccoSett] {
        let volo = StatoSettimana.condiviso.inVolo
        guard !volo.isEmpty else { return g.blocchi }
        var out = g.blocchi.filter { !($0.task && volo[$0.id] != nil) }
        for (id, p) in volo where p.giorno == g.giorno {
            if let prima = giorni.lazy.compactMap({ $0.blocchi.first { $0.task && $0.id == id } }).first {
                out.append(prima.spostato(da: p.da, a: p.a))
            }
        }
        return out
    }

    private func punto(_ p: CGPoint, giorni: [GiornoSett], colonna: CGFloat) -> (Int, Int)? {
        let x = p.x - MisureSettimana.colonnaOre
        guard x >= 0, !giorni.isEmpty else { return nil }
        let i = min(giorni.count - 1, Int(x / colonna))
        return (i, max(0, min(24 * 60 - MisureSettimana.scatto, MisureSettimana.minuti(p.y))))
    }
}

extension View {

    func posizionato(_ b: BloccoSett, x: CGFloat, colonna: CGFloat) -> some View {
        let n = CGFloat(max(b.colonne, 1))
        let w = colonna / n
        let alto = max(MisureSettimana.y(b.a) - MisureSettimana.y(b.da), MisureSettimana.y(15)) - 1
        return self
            .frame(width: max(8, w * CGFloat(max(b.ampiezza, 1)) - 3), height: max(10, alto), alignment: .topLeading)
            .offset(x: x + w * CGFloat(b.colonna) + 1, y: MisureSettimana.y(b.da))
    }
}






struct SfondoGriglia: View {
    let giorni: [GiornoSett]
    let colonna: CGFloat
    var ore: OreLavoro?

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(giorni.enumerated()), id: \.element.giorno) { i, g in
                if g.festivo || g.passato {
                    Rectangle().fill(g.festivo ? Superficie.incasso : Superficie.incasso.opacity(0.45))
                        .frame(width: colonna, height: MisureSettimana.giorno)
                        .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna)
                } else if let dalle = ore?.dalle, let alle = ore?.alle, dalle < alle {

                    Rectangle().fill(Superficie.incasso.opacity(0.5))
                        .frame(width: colonna, height: MisureSettimana.y(dalle))
                        .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna)
                    Rectangle().fill(Superficie.incasso.opacity(0.5))
                        .frame(width: colonna, height: MisureSettimana.giorno - MisureSettimana.y(alle))
                        .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna, y: MisureSettimana.y(alle))
                }
            }
            RigheGriglia(giorni: giorni.count, colonna: colonna, mezze: false)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 0.5)
            RigheGriglia(giorni: giorni.count, colonna: colonna, mezze: true)
                .stroke(Color(nsColor: .separatorColor).opacity(0.5), style: StrokeStyle(lineWidth: 0.5, dash: [2, 3]))
            ForEach(1..<24, id: \.self) { h in
                Text(Store.oraBreve(h * 60)).font(.system(size: 10)).monospacedDigit().foregroundStyle(.secondary)
                    .fixedSize()
                    .frame(width: MisureSettimana.colonnaOre - 10, alignment: .trailing)
                    .position(x: (MisureSettimana.colonnaOre - 10) / 2, y: MisureSettimana.y(h * 60))
            }
        }
        .frame(maxWidth: .infinity, minHeight: MisureSettimana.giorno, maxHeight: MisureSettimana.giorno, alignment: .topLeading)
    }
}


struct RigheGriglia: Shape {
    let giorni: Int
    let colonna: CGFloat
    let mezze: Bool

    func path(in r: CGRect) -> Path {
        var p = Path()
        if mezze {
            for h in 0..<24 {
                let y = MisureSettimana.y(h * 60 + 30)
                p.move(to: CGPoint(x: MisureSettimana.colonnaOre, y: y))
                p.addLine(to: CGPoint(x: r.width, y: y))
            }
        } else {
            for h in 1..<24 {
                let y = MisureSettimana.y(h * 60)
                p.move(to: CGPoint(x: MisureSettimana.colonnaOre - 6, y: y))
                p.addLine(to: CGPoint(x: r.width, y: y))
            }
            for i in 0...giorni {
                let x = MisureSettimana.colonnaOre + CGFloat(i) * colonna
                p.move(to: CGPoint(x: x, y: 0))
                p.addLine(to: CGPoint(x: x, y: r.height))
            }
        }
        return p
    }
}


struct LineaAdesso: View {
    let fuso: String?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let minuto = Self.minuto(ctx.date, fuso)
            ZStack(alignment: .leading) {
                Rectangle().fill(Color.red).frame(height: 1.5)
                Circle().fill(Color.red).frame(width: 9, height: 9).offset(x: -4.5)
            }
            .offset(y: MisureSettimana.y(minuto) - 0.75)
        }
        .frame(height: MisureSettimana.giorno, alignment: .top)
        .allowsHitTesting(false)
    }

    static func minuto(_ d: Date, _ fuso: String?) -> Int {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: fuso ?? "UTC") ?? .current
        let x = c.dateComponents([.hour, .minute], from: d)
        return (x.hour ?? 0) * 60 + (x.minute ?? 0)
    }
}




struct TesteGiorni: View {
    let store: Store
    let settimana: SettimanaCal
    let colonna: CGFloat

    var body: some View {
        HStack(spacing: 0) {
            Text(settimana.fuso_nome ?? "").font(.system(size: 9)).foregroundStyle(.tertiary)
                .multilineTextAlignment(.trailing).lineLimit(2)
                .frame(width: MisureSettimana.colonnaOre - 6, alignment: .trailing)
                .padding(.trailing, 6)
            ForEach(settimana.giorni) { g in
                Button {
                    if settimana.giorni.count > 1 { store.scegliScala("giorno", giorno: g.giorno) }
                } label: {
                    VStack(spacing: 2) {
                        HStack(spacing: 5) {
                            Text(g.nome).font(.system(size: 11)).foregroundStyle(g.passato ? .tertiary : .secondary)
                            if g.oggi {
                                Text("\(g.numero)").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                                    .frame(width: 22, height: 22).background(Color.accentColor, in: Circle())
                            } else {
                                Text("\(g.numero)").font(.system(size: 15, weight: .medium))
                                    .foregroundStyle(g.passato ? .tertiary : .primary)
                            }
                        }
                        carico(g)
                    }
                    .frame(maxWidth: .infinity, minHeight: 34, maxHeight: 34)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(aiuto(g))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }


    @ViewBuilder
    private func carico(_ g: GiornoSett) -> some View {
        if g.minuti_giornata > 0, g.minuti_task > 0 {
            let quota = min(1, Double(g.minuti_task) / Double(g.minuti_giornata))
            Capsule().fill(Superficie.incasso)
                .frame(width: min(64, colonna - 16), height: 3)
                .overlay(alignment: .leading) {
                    Capsule().fill(g.minuti_task > g.minuti_giornata ? Salute.errore.colore : Color.accentColor.opacity(0.7))
                        .frame(width: min(64, colonna - 16) * quota, height: 3)
                }
        } else {
            Color.clear.frame(height: 3)
        }
    }

    private func aiuto(_ g: GiornoSett) -> String {
        guard g.minuti_giornata > 0, g.minuti_task > 0 else { return g.quando }
        return g.quando + "\n" + store.ts("aiuto_carico").replacingOccurrences(of: "{task}", with: store.breve(g.minuti_task))
            .replacingOccurrences(of: "{giornata}", with: store.breve(g.minuti_giornata))
    }
}


func coloriEvento(_ ev: DettagliEvento, _ calendario: CalendarioSett?) -> (fondo: Color, testo: Color) {
    let fondo = Color.esadecimale(ev.colore) ?? Color.esadecimale(calendario?.colore) ?? .accentColor
    let testo: Color = ev.colore != nil ? .white : (Color.esadecimale(calendario?.testo) ?? .white)
    return (fondo, testo)
}


func simboloTipoEvento(_ tipo: String?) -> String? {
    switch tipo {
    case "focusTime": "headphones"
    case "outOfOffice": "airplane"
    case "workingLocation": "building.2"
    default: nil
    }
}


func titoloConSegno(_ titolo: String, _ tipo: String?) -> Text {
    guard let s = simboloTipoEvento(tipo) else { return Text(verbatim: titolo) }
    return Text("\(Image(systemName: s)) \(titolo)")
}




struct FasciaTuttoIlGiorno: View {
    let cose: Cose
    let store: Store
    let settimana: SettimanaCal
    let calendari: [String: CalendarioSett]
    let colonna: CGFloat
    @Binding var aperta: Bool
    @State private var puntata: String?


    private struct Pezzo: Identifiable {
        let id: String
        let riga: Int
        let dal: Int
        let al: Int
        let task: VoceCosa?
        let evento: FasciaSett?
    }

    var body: some View {
        let giorni = settimana.giorni
        let tasks = giorni.map { g in
            (g.scadenze + g.pianificate.filter { !g.scadenze.contains($0) }).compactMap { store.coseIndice[$0] }
        }
        let righeTask = tasks.map(\.count).max() ?? 0
        let righeEventi = max(settimana.righe_tutto_il_giorno ?? 0, giorni.map(\.righe).max() ?? 0)
        let totali = righeTask + righeEventi
        let chiusa = totali > MisureSettimana.righeFascia && !aperta

        let pezzi = pezzi(giorni, tasks, chiusa ? min(righeTask, 1) : righeTask)
        let aVista = chiusa ? MisureSettimana.righeFascia - 1 : totali
        let altezza = CGFloat(chiusa ? MisureSettimana.righeFascia : max(totali, 1)) * MisureSettimana.rigaFascia + 6
        ZStack(alignment: .topLeading) {

            ForEach(Array(giorni.enumerated()), id: \.element.giorno) { i, g in
                Rectangle()
                    .fill(puntata == g.giorno ? Superficie.selezione : (g.festivo ? Superficie.incasso : Color.clear))
                    .frame(width: colonna, height: altezza)
                    .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna)
                    .dropDestination(for: String.self) { valori, _ in
                        let ids = idsDaTesto(valori).filter { store.coseIndice[$0]?.giorno != g.giorno }
                        guard !ids.isEmpty else { return false }
                        Task { await store.gestoTask("data", ids, [g.giorno]) }
                        return true
                    } isTargeted: { puntata = $0 ? g.giorno : (puntata == g.giorno ? nil : puntata) }
            }
            if totali > MisureSettimana.righeFascia && aperta {
                Button(store.ts("fascia_meno")) { aperta = false }
                    .buttonStyle(.link).font(.system(size: 10))
                    .frame(width: MisureSettimana.colonnaOre - 8, alignment: .trailing)
                    .offset(y: altezza - MisureSettimana.rigaFascia)
                    .help(store.ts("aiuto_fascia_meno"))
            }
            ForEach(pezzi.filter { $0.riga < aVista }) { p in
                pezzo(p, giorni: giorni)
                    .frame(width: max(8, CGFloat(p.al - p.dal + 1) * colonna - 4), height: MisureSettimana.rigaFascia - 2,
                           alignment: .leading)
                    .offset(x: MisureSettimana.colonnaOre + CGFloat(p.dal) * colonna + 2,
                            y: 3 + CGFloat(p.riga) * MisureSettimana.rigaFascia)
            }
            if chiusa {
                ForEach(Array(giorni.enumerated()), id: \.element.giorno) { i, g in
                    let n = pezzi.filter { $0.riga >= aVista && $0.dal <= i && i <= $0.al }.count
                    if n > 0 {
                        Button(store.ts("altri_n").replacingOccurrences(of: "{n}", with: n.formatted())) { aperta = true }
                            .buttonStyle(.plain).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                            .frame(width: colonna - 4, height: MisureSettimana.rigaFascia - 2, alignment: .leading)
                            .contentShape(Rectangle())
                            .offset(x: MisureSettimana.colonnaOre + CGFloat(i) * colonna + 6,
                                    y: 3 + CGFloat(aVista) * MisureSettimana.rigaFascia)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: altezza, maxHeight: altezza, alignment: .topLeading)
        .overlay(alignment: .topLeading) {
            Text(store.ts("tutto_il_giorno")).font(.system(size: 9)).foregroundStyle(.tertiary)
                .lineLimit(2).multilineTextAlignment(.trailing)
                .frame(width: MisureSettimana.colonnaOre - 8, alignment: .trailing)
                .padding(.top, 5)
                .allowsHitTesting(false)
        }
        .animation(.smooth(duration: 0.2), value: aperta)
    }


    private func pezzi(_ giorni: [GiornoSett], _ tasks: [[VoceCosa]], _ righeTask: Int) -> [Pezzo] {
        var out: [Pezzo] = []
        for (i, voci) in tasks.enumerated() {
            for (r, v) in voci.enumerated() {

                out.append(Pezzo(id: "s-\(i)-\(v.id)", riga: r < righeTask ? r : 1000 + r, dal: i, al: i, task: v, evento: nil))
            }
        }
        for b in settimana.barre {
            let dal = max(0, b.dal ?? 0), al = min(giorni.count - 1, b.al ?? dal)
            out.append(Pezzo(id: "b-\(b.id)-\(dal)", riga: righeTask + b.riga, dal: dal, al: max(dal, al), task: nil, evento: b))
        }
        for (i, g) in giorni.enumerated() {
            for e in g.tutto_il_giorno {
                out.append(Pezzo(id: "t-\(i)-\(e.id)", riga: righeTask + e.riga, dal: i, al: i, task: nil, evento: e))
            }
        }
        return out
    }

    @ViewBuilder
    private func pezzo(_ p: Pezzo, giorni: [GiornoSett]) -> some View {
        if let v = p.task {
            PromemoriaTask(cose: cose, store: store, voce: v,
                           pianificata: giorni[safe: p.dal].map { $0.pianificate.contains(v.id) && !$0.scadenze.contains(v.id) } ?? false)
        } else if let e = p.evento {
            EventoFascia(store: store, evento: e, calendario: calendari[e.cal ?? ""])
        }
    }
}



struct EventoFascia: View {
    let store: Store
    let evento: FasciaSett
    let calendario: CalendarioSett?
    @Environment(\.colorScheme) private var schema
    @State private var aperto = false

    var body: some View {
        let (colore, testoGoogle) = coloriEvento(evento.ev, calendario)
        let risposta = evento.ev.risposta ?? "accettato"
        let pieno = risposta == "accettato" || risposta == "rifiutato"
        let scuro = schema == .dark
        let forma = RoundedRectangle(cornerRadius: 4, style: .continuous)
        HStack(spacing: 3) {
            if evento.continua_prima { Image(systemName: "chevron.left").font(.system(size: 8, weight: .bold)) }
            if let o = evento.ora { Text(o).font(.system(size: 10)).monospacedDigit().opacity(0.85) }
            titoloConSegno(evento.titolo, evento.ev.tipo_evento).font(.system(size: 11, weight: .medium)).lineLimit(1)
                .strikethrough(risposta == "rifiutato")
            Spacer(minLength: 0)
            if evento.continua_dopo { Image(systemName: "chevron.right").font(.system(size: 8, weight: .bold)) }
        }
        .foregroundStyle(pieno ? (scuro ? Color.primary : testoGoogle) : (scuro ? Color.primary : colore))
        .padding(.horizontal, 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background {
            ZStack {
                if pieno {
                    forma.fill(scuro ? colore.opacity(0.55) : colore)
                } else {
                    forma.fill(Superficie.scheda)
                    forma.fill(colore.opacity(scuro ? 0.16 : 0.10))
                    if risposta == "forse" { RigheForse(colore: colore.opacity(scuro ? 0.35 : 0.28)).clipShape(forma) }
                }
            }
        }
        .overlay(forma.strokeBorder(pieno ? Color.clear : colore, lineWidth: 1.25))
        .opacity(risposta == "rifiutato" ? 0.5 : 1)
        .contentShape(forma)
        .onTapGesture { aperto = true }
        .help(evento.ev.aiuto ?? evento.titolo)
        .popover(isPresented: $aperto, arrowEdge: .bottom) {
            RiquadroEvento(store: store, titolo: evento.titolo, ev: evento.ev, calendario: calendario)
        }
    }
}




struct PromemoriaTask: View {
    let cose: Cose
    let store: Store
    let voce: VoceCosa
    var pianificata = false
    @State private var sopra = false

    var body: some View {
        let fatta = Store.chiusa(voce)
        let scelta = store.coseScelte.contains(voce.id)
        HStack(spacing: 4) {
            Button { Task { await store.fattaORiapri([voce.id]) } } label: {
                SegnoStato(stato: voce.stato ?? "da_fare", anteprima: sopra, dimensione: 11)
            }
            .buttonStyle(.plain)
            .help(store.aiutoCerchio(voce))
            if pianificata { Image(systemName: "calendar").font(.system(size: 9)).foregroundStyle(.secondary) }
            Text(voce.titolo).font(.system(size: 11)).lineLimit(1)
                .strikethrough(fatta)
                .foregroundStyle(fatta ? .secondary : .primary)
            Spacer(minLength: 0)
        }
        .padding(.leading, voce.priorita == 0 ? 6 : 4).padding(.trailing, 4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(sopra ? Superficie.riquadroPremuto : Superficie.riquadro,
                    in: RoundedRectangle(cornerRadius: 4, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous)
            .strokeBorder(scelta ? Color.accentColor : Superficie.bordo, lineWidth: scelta ? 1.5 : 0.5))
        .overlay(alignment: .leading) {
            if voce.priorita == 0 && !fatta {
                RoundedRectangle(cornerRadius: 1).fill(TintaPriorita.testo(0)).frame(width: 3).padding(.vertical, 2)
            }
        }
        .onHover { sopra = $0 }
        .help(voce.titolo)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { store.coseScelte = [voce.id]; store.cosaAperta = voce.id; store.dettaglioCose = true }
        .onTapGesture { store.coseScelte = [voce.id] }
        .contextMenu {
            if pianificata {
                Button(store.ts("togli_dal_calendario")) { Task { await store.togliDalTempo([voce.id]) } }
                Divider()
            }
            VociTask(cose: cose, store: store, ids: scelta ? store.idsAzione : [voce.id], conDettaglio: true)
        }
        .draggable(scelta && store.coseScelte.count > 1 ? store.idsAzione.joined(separator: ",") : voce.id)
    }
}






struct BloccoEventoSett: View {
    let store: Store
    let blocco: BloccoSett
    let calendario: CalendarioSett?

    var colonna: CGFloat = 200
    @Environment(\.colorScheme) private var schema
    @State private var aperto = false

    var body: some View {
        let (colore, testoGoogle) = coloriEvento(blocco.ev, calendario)
        let risposta = blocco.risposta ?? "accettato"
        let scuro = schema == .dark
        let pieno = (risposta == "accettato" || risposta == "rifiutato") && blocco.ev.libero != true
        let altezza = MisureSettimana.y(blocco.a - blocco.da)
        let forma = RoundedRectangle(cornerRadius: 4, style: .continuous)
        let largo = colonna / CGFloat(max(blocco.colonne, 1)) * CGFloat(max(blocco.ampiezza, 1)) - 3
        VStack(alignment: .leading, spacing: 0) {
            if blocco.continua_prima {
                Image(systemName: "chevron.compact.up").font(.system(size: 9, weight: .bold)).frame(maxWidth: .infinity)
            }
            HStack(alignment: .firstTextBaseline, spacing: 3) {

                titoloConSegno(blocco.titolo ?? "", blocco.ev.tipo_evento)
                    .font(.system(size: 11, weight: .semibold))
                    .strikethrough(risposta == "rifiutato")
                    .lineLimit(altezza >= 36 && largo >= MisureSettimana.bloccoDueRighe ? 2 : 1)
                if altezza < 34, largo >= MisureSettimana.bloccoOraAccanto, let o = blocco.ora {

                    Text(o).font(.system(size: 10)).monospacedDigit().opacity(0.85).lineLimit(1).fixedSize()
                }
            }
            if altezza >= 34, let o = blocco.ora {
                HStack(spacing: 3) {
                    Text([o, blocco.ora_fine].compactMap { $0 }.joined(separator: "-"))
                        .font(.system(size: 10)).monospacedDigit().opacity(0.85).lineLimit(1)
                    if blocco.ev.video != nil { Image(systemName: "video").font(.system(size: 9)).opacity(0.85) }
                    if blocco.ev.luogo == true { Image(systemName: "mappin").font(.system(size: 9)).opacity(0.85) }
                }
            }
            Spacer(minLength: 0)
            if blocco.continua_dopo {
                Image(systemName: "chevron.compact.down").font(.system(size: 9, weight: .bold)).frame(maxWidth: .infinity)
            }
        }
        .foregroundStyle(pieno ? (scuro ? Color.primary : testoGoogle) : (scuro ? Color.primary : colore))
        .padding(.horizontal, 5).padding(.vertical, altezza >= 20 ? 3 : 0)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipShape(forma)
        .background {
            ZStack {
                if pieno {
                    forma.fill(scuro ? colore.opacity(0.42) : colore)
                } else {
                    forma.fill(Superficie.scheda)
                    forma.fill(colore.opacity(scuro ? 0.16 : 0.10))
                    if risposta == "forse" { RigheForse(colore: colore.opacity(scuro ? 0.35 : 0.28)).clipShape(forma) }
                }
            }
        }
        .overlay(forma.strokeBorder(pieno ? Superficie.scheda.opacity(0.6) : colore,
                                    style: StrokeStyle(lineWidth: pieno ? 0.5 : 1.25,
                                                       dash: blocco.ev.incerto == true ? [3, 2] : [])))
        .overlay(alignment: .leading) {
            if scuro && pieno { Rectangle().fill(colore).frame(width: 3).clipShape(forma) }
        }
        .opacity(risposta == "rifiutato" ? 0.5 : 1)
        .contentShape(forma)
        .onTapGesture { aperto = true }
        .help(blocco.aiuto ?? blocco.titolo ?? "")
        .popover(isPresented: $aperto, arrowEdge: .trailing) {
            RiquadroEvento(store: store, titolo: blocco.titolo ?? "", ev: blocco.ev, calendario: calendario)
        }
    }
}


struct RigheForse: View {
    let colore: Color

    var body: some View {

        StrisceForse().stroke(colore, lineWidth: 2)
    }
}

struct StrisceForse: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        var x: CGFloat = -r.height
        while x < r.width {
            p.move(to: CGPoint(x: x, y: r.height))
            p.addLine(to: CGPoint(x: x + r.height, y: 0))
            x += 7
        }
        return p
    }
}



struct RiquadroEvento: View {
    let store: Store
    let titolo: String
    let ev: DettagliEvento
    let calendario: CalendarioSett?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                if let s = simboloTipoEvento(ev.tipo_evento) { Image(systemName: s).foregroundStyle(.secondary) }
                Text(titolo).font(.system(size: 14, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
            }
            if let a = ev.aiuto, !a.isEmpty {
                Text(a).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if let c = calendario {
                HStack(spacing: 6) {
                    Circle().fill(coloriEvento(DettagliEvento(), c).fondo).frame(width: 8, height: 8)
                    Text([c.nome, c.casella ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")).font(.system(size: 12))
                }
            }
            if ev.video != nil || ev.link != nil {
                HStack {
                    if let v = ev.video, let u = URL(string: v) {
                        Button(store.ts("videochiamata")) { NSWorkspace.shared.open(u) }.buttonStyle(.borderedProminent)
                    }
                    if let g = ev.link, let u = URL(string: g) {
                        Button(store.ts("apri_in_google")) { NSWorkspace.shared.open(u) }
                    }
                }
                .controlSize(.small)
            }
        }
        .padding(14)
        .frame(width: 280, alignment: .leading)
    }
}





struct BloccoTaskSett: View {
    let cose: Cose
    let store: Store
    let blocco: BloccoSett
    let giorni: [GiornoSett]
    let indice: Int
    let colonna: CGFloat
    @State private var sposta: CGSize = .zero
    @State private var allunga: CGFloat = 0
    @State private var sopra = false
    @State private var posti: RispostaBuchi?
    @State private var cercoPosti = false
    @State private var cursore = false

    var body: some View {
        let v = store.coseIndice[blocco.id]
        let fatta = v.map(Store.chiusa) ?? false
        let scelta = store.coseScelte.contains(blocco.id)
        let passoMin = MisureSettimana.scatta(MisureSettimana.minuti(sposta.height))
        let passoGiorni = Int((sposta.width / max(colonna, 1)).rounded())
        let allungoMin = MisureSettimana.scatta(MisureSettimana.minuti(allunga))
        let durata = max(MisureSettimana.scatto, blocco.a - blocco.da + allungoMin)
        let trascina = sposta != .zero || allunga != 0
        let forma = RoundedRectangle(cornerRadius: 5, style: .continuous)
        let bordo: Color = scelta ? .accentColor

            : (blocco.oltre_scadenza == true ? Color.primary.opacity(0.55) : (blocco.sovrapposta == true ? Salute.attenzione.colore : Superficie.bordo))


        let largo = colonna / CGFloat(max(blocco.colonne, 1)) * CGFloat(max(blocco.ampiezza, 1)) - 3
        HStack(alignment: .top, spacing: 4) {
            if largo >= MisureSettimana.bloccoConCerchio {
                Button { Task { await store.fattaORiapri([blocco.id]) } } label: {
                    SegnoStato(stato: v?.stato ?? "da_fare", anteprima: sopra, dimensione: 12)
                }
                .buttonStyle(.plain)
                .help(v.map(store.aiutoCerchio) ?? "")
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(v?.titolo ?? "").font(.system(size: 11, weight: .medium))
                    .lineLimit(MisureSettimana.y(durata) >= 40 && largo >= MisureSettimana.bloccoDueRighe ? 2 : 1)
                    .strikethrough(fatta).foregroundStyle(fatta ? .secondary : .primary)
                if MisureSettimana.y(durata) >= MisureSettimana.y(45) || trascina {
                    Text(trascina ? orario(passoMin, durata) : [blocco.ora, blocco.ora_fine].compactMap { $0 }.joined(separator: "-"))
                        .font(.system(size: 10)).monospacedDigit().foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.tail)
                }
            }
            .frame(minWidth: 0)
            Spacer(minLength: 0)
        }
        .padding(.leading, 6).padding(.trailing, 3).padding(.top, 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .clipShape(forma)
        .background {
            ZStack(alignment: .bottom) {
                forma.fill(Superficie.scheda)
                forma.fill(Superficie.riquadro)
                if blocco.durata_detta == false {

                    LinearGradient(colors: [.clear, Superficie.scheda.opacity(0.9)], startPoint: .top, endPoint: .bottom)
                        .clipShape(forma)
                }
            }
        }
        .overlay(forma.strokeBorder(bordo, style: StrokeStyle(lineWidth: scelta || blocco.sovrapposta == true || blocco.oltre_scadenza == true ? 1.5 : 1,
                                                                  dash: blocco.durata_detta == false ? [3, 2] : [])))
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1.5).fill(coloreP(v?.priorita)).frame(width: 3).padding(.vertical, 3).padding(.leading, 1)
        }
        .overlay(alignment: .bottom) { maniglia }
        .opacity(fatta ? 0.55 : 1)
        .frame(height: max(10, MisureSettimana.y(durata) - 1), alignment: .top)
        .frame(maxHeight: .infinity, alignment: .top)
        .shadow(color: .black.opacity(trascina ? 0.18 : 0), radius: 6, y: 2)
        .offset(x: CGFloat(passoGiorni) * colonna, y: MisureSettimana.y(passoMin))
        .zIndex(trascina ? 10 : 1)
        .onHover { sopra = $0 }
        .contentShape(forma)
        .onTapGesture(count: 2) { store.coseScelte = [blocco.id]; store.cosaAperta = blocco.id; store.dettaglioCose = true }
        .onTapGesture {
            if NSEvent.modifierFlags.contains(.command) || NSEvent.modifierFlags.contains(.shift) {
                if scelta { store.coseScelte.remove(blocco.id) } else { store.coseScelte.insert(blocco.id) }
            } else {
                store.coseScelte = [blocco.id]
            }
        }
        .gesture(DragGesture(minimumDistance: 4, coordinateSpace: .named("settimana"))
            .onChanged { sposta = $0.translation }
            .onEnded { fine($0.location, passoMin, passoGiorni) })
        .help(blocco.aiuto.map { $0 + "\n" + store.ts("aiuto_blocco_task") } ?? store.ts("aiuto_blocco_task"))
        .contextMenu {
            Button(store.ts("togli_dal_calendario")) { Task { await store.togliDalTempo([blocco.id]) } }
            Button(store.ts("trova_un_posto")) { cercaPosti() }
            Divider()
            VociTask(cose: cose, store: store, ids: scelta ? store.idsAzione : [blocco.id], conDettaglio: true)
        }
        .popover(isPresented: $cercoPosti, arrowEdge: .trailing) { riquadroPosti }
    }


    private var maniglia: some View {
        Rectangle().fill(Color.clear).frame(height: 6).contentShape(Rectangle())
            .onHover { dentro in


                if dentro, !cursore { NSCursor.resizeUpDown.push(); cursore = true }
                if !dentro, cursore { NSCursor.pop(); cursore = false }
            }
            .onDisappear { if cursore { NSCursor.pop(); cursore = false } }
            .gesture(DragGesture(minimumDistance: 2)
                .onChanged { allunga = $0.translation.height }
                .onEnded { _ in

                    if blocco.continua_prima == true || blocco.continua_dopo == true { allunga = 0; return }
                    let nuova = max(MisureSettimana.scatto, blocco.a - blocco.da + MisureSettimana.scatta(MisureSettimana.minuti(allunga)))
                    allunga = 0
                    guard nuova != blocco.a - blocco.da, let g = giorni[safe: indice] else { return }
                    StatoSettimana.condiviso.inVolo[blocco.id] = PosizioneInVolo(giorno: g.giorno, da: blocco.da, a: min(24 * 60, blocco.da + nuova))
                    Task { await store.pianifica(ids: [blocco.id], quando: "\(g.giorno)T\(Store.oraDi(blocco.da))", durata: nuova) }
                })
            .help(store.ts("aiuto_maniglia"))
    }

    private func fine(_ dove: CGPoint, _ passoMin: Int, _ passoGiorni: Int) {
        sposta = .zero
        let cornici = StatoSettimana.condiviso.cornici

        if cornici["fascia"]?.contains(dove) == true || cornici["cassetto"]?.contains(dove) == true {
            Task { await store.togliDalTempo([blocco.id]) }
            return
        }

        guard !blocco.continua_prima else { return }
        let j = max(0, min(giorni.count - 1, indice + passoGiorni))
        let durata = blocco.a - blocco.da
        let da = max(0, min(24 * 60 - MisureSettimana.scatto, blocco.da + passoMin))
        guard j != indice || da != blocco.da else { return }
        let g = giorni[j]
        StatoSettimana.condiviso.inVolo[blocco.id] = PosizioneInVolo(giorno: g.giorno, da: da, a: min(24 * 60, da + durata))
        Task { await store.pianifica(ids: [blocco.id], quando: "\(g.giorno)T\(Store.oraDi(da))", durata: nil) }
    }

    private func orario(_ passo: Int, _ durata: Int) -> String {
        let da = max(0, blocco.da + passo)
        return Store.oraBreve(da) + "-" + Store.oraBreve(min(24 * 60, da + durata))
    }

    private func coloreP(_ p: Int?) -> Color {

        TintaPriorita.testo(p ?? 2)
    }

    private func cercaPosti() {
        posti = nil
        cercoPosti = true
        Task { posti = await store.buchi(per: blocco.id) }
    }


    @ViewBuilder
    private var riquadroPosti: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let posti {
                if let e = posti.errore, posti.ok != true {
                    Text(e).font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                } else {
                    if let m = posti.messaggio {
                        Text(m).font(.system(size: 13, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(posti.buchi ?? [], id: \.self) { b in
                        Button(b.frase) {
                            cercoPosti = false
                            Task { await store.pianifica(ids: [blocco.id], quando: b.pianifica ?? String(b.inizio.prefix(16)), durata: nil) }
                        }
                        .buttonStyle(.link)
                    }
                }
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .padding(14)
        .frame(width: 260, alignment: .leading)
    }
}

extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}



struct AnteprimaOra: Equatable {
    let giorno: Int
    let minuto: Int
}


struct AnteprimaOraVista: View {
    let anteprima: AnteprimaOra

    var body: some View {
        HStack(spacing: 4) {
            Text(Store.oraDi(anteprima.minuto)).font(.system(size: 10, weight: .semibold)).monospacedDigit()
                .foregroundStyle(.white)
                .padding(.horizontal, 5).padding(.vertical, 1)
                .background(Color.accentColor, in: Capsule())
            Rectangle().fill(Color.accentColor).frame(height: 2)
        }
        .frame(height: 18)
    }
}



struct LasciaSulTempo: DropDelegate {
    let giorni: [GiornoSett]
    let colonna: CGFloat
    @Binding var anteprima: AnteprimaOra?
    let lascia: ([String], Int, Int) -> Void

    private func dove(_ p: CGPoint) -> AnteprimaOra? {
        let x = p.x - MisureSettimana.colonnaOre
        guard x >= 0, !giorni.isEmpty else { return nil }
        let i = min(giorni.count - 1, Int(x / max(colonna, 1)))
        let m = MisureSettimana.scatta(MisureSettimana.minuti(p.y))
        return AnteprimaOra(giorno: i, minuto: max(0, min(24 * 60 - MisureSettimana.scatto, m)))
    }

    func validateDrop(info: DropInfo) -> Bool { info.hasItemsConforming(to: [.text]) }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        let nuova = dove(info.location)
        if nuova != anteprima { anteprima = nuova }
        return DropProposal(operation: .move)
    }

    func dropExited(info: DropInfo) { anteprima = nil }

    func performDrop(info: DropInfo) -> Bool {
        guard let a = dove(info.location) else { anteprima = nil; return false }
        anteprima = nil
        let fornitori = info.itemProviders(for: [.text])
        guard !fornitori.isEmpty else { return false }
        for f in fornitori {
            _ = f.loadObject(ofClass: NSString.self) { s, _ in
                guard let s = s as? String else { return }
                let ids = idsDaTesto([s])
                DispatchQueue.main.async { if !ids.isEmpty { lascia(ids, a.giorno, a.minuto) } }
            }
        }
        return true
    }
}






struct CassettoSettimana: View {
    let cose: Cose
    let store: Store
    let scadute: [VoceCosa]
    let senza: [VoceCosa]
    let daRipianificare: [VoceCosa]
    @State private var apriRipianificare = true
    @State private var apriScadute = true
    @State private var apriSenza = false
    @State private var puntata = false

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 6, pinnedViews: [.sectionHeaders]) {
                if !daRipianificare.isEmpty {
                    Section {
                        if apriRipianificare {
                            ForEach(daRipianificare) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: true) }
                        }
                    } header: {
                        testa(store.ts("da_ripianificare"), daRipianificare.count, $apriRipianificare)
                            .help(store.ts("aiuto_da_ripianificare"))
                    }
                }
                Section {
                    if apriScadute {
                        ForEach(scadute) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: true) }
                        if scadute.isEmpty { Text(cose.t("cal_nessuna_scaduta")).font(.system(size: 11)).foregroundStyle(.tertiary) }
                    }
                } header: {
                    testa(cose.t("cal_scadute"), scadute.count, $apriScadute)
                }
                Section {
                    if apriSenza {
                        ForEach(senza) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: true) }
                        if senza.isEmpty { Text(cose.t("cal_nessuna_senza")).font(.system(size: 11)).foregroundStyle(.tertiary) }
                    }
                } header: {
                    testa(cose.t("cal_senza_data"), senza.count, $apriSenza)
                        .background(puntata ? Superficie.selezione : Color.clear,
                                    in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
                        .dropDestination(for: String.self) { valori, _ in
                            let ids = idsDaTesto(valori).filter { store.coseIndice[$0]?.giorno != nil }
                            guard !ids.isEmpty else { return false }
                            Task { await store.gestoTask("data", ids, ["togli"]) }
                            return true
                        } isTargeted: { puntata = $0 }
                }
            }
            .padding(8)
        }
        .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous))
        .help(cose.t("aiuto_cassetto"))
    }

    private func testa(_ nome: String, _ n: Int, _ aperto: Binding<Bool>) -> some View {
        Button { aperto.wrappedValue.toggle() } label: {
            HStack(spacing: 6) {
                Image(systemName: "chevron.right").font(.system(size: 9, weight: .semibold))
                    .rotationEffect(.degrees(aperto.wrappedValue ? 90 : 0))
                Text(nome).font(.system(size: 13, weight: .semibold))
                Text(n.formatted()).font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary)
                Spacer()
            }
            .frame(height: 28).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(Superficie.incasso)
    }
}
