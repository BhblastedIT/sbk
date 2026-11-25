import AppKit
import SwiftUI





















struct VoceFiltri: Codable, Hashable, Identifiable {
    let id: String
    let nome: String

    init(id: String, nome: String) {
        self.id = id
        self.nome = nome
    }

    enum CodingKeys: String, CodingKey { case id, nome }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        let n = p.testo(.nome)
        nome = n.isEmpty ? id : n
    }
}



struct DimensioneFiltri: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let voci: [VoceFiltri]
    let aiuto: String
    let una: Bool

    init(id: String, nome: String, voci: [VoceFiltri], aiuto: String = "", una: Bool = true) {
        self.id = id
        self.nome = nome
        self.voci = voci
        self.aiuto = aiuto
        self.una = una
    }

    enum CodingKeys: String, CodingKey { case id, nome, voci, aiuto, una, piu_voci }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        let n = p.testo(.nome)
        nome = n.isEmpty ? id : n
        voci = (p.elenco(.voci) as [VoceFiltri]).filter { !$0.id.isEmpty }
        aiuto = p.testo(.aiuto)
        una = (p.uno(.una) as Bool?) ?? !((p.uno(.piu_voci) as Bool?) ?? false)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(nome, forKey: .nome)
        try c.encode(voci, forKey: .voci)
        try c.encode(aiuto, forKey: .aiuto)
        try c.encode(una, forKey: .una)
    }

    func nome(di voce: String) -> String { voci.first { $0.id == voce }?.nome ?? voce }
}




struct SceltaFiltri: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let campo: String
    let verso: String
    let vuoti: String
    let dimensione: String?

    init(id: String, nome: String, campo: String = "", verso: String = "", vuoti: String = "", dimensione: String? = nil) {
        self.id = id
        self.nome = nome
        self.campo = campo
        self.verso = verso
        self.vuoti = vuoti
        self.dimensione = dimensione
    }

    enum CodingKeys: String, CodingKey { case id, nome, campo, verso, vuoti, dimensione }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        let n = p.testo(.nome)
        nome = n.isEmpty ? id : n
        campo = p.testo(.campo)
        verso = p.testo(.verso)
        vuoti = p.testo(.vuoti)
        dimensione = p.uno(.dimensione)
    }
}



struct FiltriBacheca: Codable, Hashable {
    let dimensioni: [DimensioneFiltri]
    let ordini: [SceltaFiltri]
    let gruppi: [SceltaFiltri]

    enum CodingKeys: String, CodingKey { case dimensioni, ordini, gruppi, ordina, raggruppa }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        dimensioni = (p.elenco(.dimensioni) as [DimensioneFiltri]).filter { !$0.id.isEmpty }
        let o: [SceltaFiltri] = p.elenco(.ordini)
        ordini = (o.isEmpty ? p.elenco(.ordina) : o).filter { !$0.id.isEmpty }
        let g: [SceltaFiltri] = p.elenco(.gruppi)
        gruppi = (g.isEmpty ? p.elenco(.raggruppa) : g).filter { !$0.id.isEmpty }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(dimensioni, forKey: .dimensioni)
        try c.encode(ordini, forKey: .ordini)
        try c.encode(gruppi, forKey: .gruppi)
    }
}



struct ScelteFiltri: Codable, Hashable {
    let v: [String: [String]]

    init(_ v: [String: [String]]) { self.v = v }

    init(from decoder: Decoder) throws {
        var tutte: [String: [String]] = [:]
        if let c = try? decoder.container(keyedBy: ChiaveLibera.self) {
            for k in c.allKeys {
                if let elenco = try? c.decode([String].self, forKey: k) {
                    tutte[k.stringValue] = elenco.filter { !$0.isEmpty }
                } else if let una = try? c.decode(String.self, forKey: k), !una.isEmpty {
                    tutte[k.stringValue] = [una]
                }
            }
        }
        v = tutte.filter { !$0.value.isEmpty }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: ChiaveLibera.self)
        for k in v.keys.sorted() { try c.encode(v[k] ?? [], forKey: ChiaveLibera(stringValue: k)) }
    }
}




struct FiltroSpunti: Codable, Hashable {
    var scelte: [String: [String]]
    var ordine: String
    var gruppo: String

    static let ordinePartenza = "recenti"
    static let gruppoPartenza = "niente"

    static let partenza = FiltroSpunti(scelte: [:], ordine: ordinePartenza, gruppo: gruppoPartenza)

    init(scelte: [String: [String]], ordine: String, gruppo: String) {
        self.scelte = scelte
        self.ordine = ordine
        self.gruppo = gruppo
    }

    enum CodingKeys: String, CodingKey { case scelte, ordina, raggruppa, ordine, gruppo }



    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        if let s: ScelteFiltri = p.uno(.scelte) {
            scelte = s.v
        } else {
            let tutte = (try? ScelteFiltri(from: decoder))?.v ?? [:]
            scelte = tutte.filter { !["ordina", "raggruppa", "ordine", "gruppo", "scelte"].contains($0.key) }
        }
        let o = p.testo(.ordine).isEmpty ? p.testo(.ordina) : p.testo(.ordine)
        ordine = o.isEmpty ? Self.ordinePartenza : o
        let g = p.testo(.gruppo).isEmpty ? p.testo(.raggruppa) : p.testo(.gruppo)
        gruppo = g.isEmpty ? Self.gruppoPartenza : g
    }


    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(ScelteFiltri(scelte.filter { !$0.value.isEmpty }), forKey: .scelte)
        try c.encode(ordine, forKey: .ordine)
        try c.encode(gruppo, forKey: .gruppo)
    }


    static let passo = "passo"

    var passoScelto: String? { scelte[Self.passo]?.first }


    var dimensioniScelte: [String] { scelte.filter { $0.key != Self.passo && !$0.value.isEmpty }.map(\.key) }


    var senzaScelte: Bool { scelte.values.allSatisfy(\.isEmpty) }


    mutating func scegli(_ dimensione: String, _ voce: String, _ si: Bool) {
        var voci = scelte[dimensione] ?? []
        if si, !voci.contains(voce) { voci.append(voce) }
        if !si { voci.removeAll { $0 == voce } }
        scelte[dimensione] = voci.isEmpty ? nil : voci
    }


    func uguale(_ altro: FiltroSpunti) -> Bool {
        func norm(_ s: [String: [String]]) -> [String: Set<String>] {
            s.filter { !$0.value.isEmpty }.mapValues(Set.init)
        }
        return norm(scelte) == norm(altro.scelte) && ordine == altro.ordine && gruppo == altro.gruppo
    }
}



struct FiltroConNome: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let filtro: FiltroSpunti
    let aiuto: String

    init(id: String, nome: String, filtro: FiltroSpunti, aiuto: String = "") {
        self.id = id
        self.nome = nome
        self.filtro = filtro
        self.aiuto = aiuto
    }

    enum CodingKeys: String, CodingKey { case id, nome, filtro, aiuto }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        nome = p.testo(.nome)
        let i = p.testo(.id)
        id = i.isEmpty ? nome : i
        filtro = p.uno(.filtro) ?? .partenza
        aiuto = p.testo(.aiuto)
    }
}



struct EsitoFiltriSalvati: Decodable {
    let ok: Bool
    let messaggio: String?
    let filtri: [FiltroConNome]?
    let siLegge: Bool?

    enum CodingKeys: String, CodingKey { case ok, messaggio, filtri_salvati, salvati, filtri_salvati_si_legge }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decode(Bool.self, forKey: .ok)
        messaggio = try? c.decodeIfPresent(String.self, forKey: .messaggio)
        let elenco = (try? c.decodeIfPresent([FiltroConNome].self, forKey: .filtri_salvati))
            ?? (try? c.decodeIfPresent([FiltroConNome].self, forKey: .salvati))
        filtri = elenco.map { $0.filter { !$0.nome.isEmpty } }
        siLegge = try? c.decodeIfPresent(Bool.self, forKey: .filtri_salvati_si_legge)
    }
}






struct QuadroFiltri {
    let dimensioni: [DimensioneFiltri]
    let ordini: [SceltaFiltri]
    let gruppi: [SceltaFiltri]
    let pronti: [FiltroConNome]

    let faccette: [String: [String: [String]]]

    let dalMotore: Bool


    let dimensionePasso: DimensioneFiltri?
    private let note: Set<String>

    init(dimensioni: [DimensioneFiltri], ordini: [SceltaFiltri], gruppi: [SceltaFiltri], pronti: [FiltroConNome],
         faccette: [String: [String: [String]]], dalMotore: Bool) {

        dimensionePasso = dimensioni.first { $0.id == FiltroSpunti.passo }
        self.dimensioni = dimensioni.filter { $0.id != FiltroSpunti.passo && !$0.voci.isEmpty }
        self.ordini = ordini
        self.gruppi = gruppi
        self.pronti = pronti.filter { !$0.nome.isEmpty }
        self.faccette = faccette
        self.dalMotore = dalMotore
        note = Set(self.dimensioni.map(\.id))
    }





    static func di(_ i: Inspiration) -> QuadroFiltri {
        if let f = i.filtriMotore {
            var faccette: [String: [String: [String]]] = [:]
            for s in i.voci { faccette[s.id] = s.faccetteMotore }
            let ordini = !f.ordini.isEmpty ? f.ordini : (i.ordinaMotore ?? AdattatoreFiltri.ordini(i))
            let gruppi = !f.gruppi.isEmpty ? f.gruppi : (i.raggruppaMotore ?? AdattatoreFiltri.gruppi(i))
            return QuadroFiltri(dimensioni: f.dimensioni, ordini: ordini, gruppi: gruppi,
                                pronti: i.filtriProntiMotore ?? [], faccette: faccette, dalMotore: true)
        }
        return AdattatoreFiltri.quadro(i)
    }

    func dimensione(_ id: String) -> DimensioneFiltri? { dimensioni.first { $0.id == id } }


    func conosce(_ dimensione: String) -> Bool { dimensione == FiltroSpunti.passo || note.contains(dimensione) }


    func voci(_ s: Spunto, _ dimensione: String) -> [String] {
        if dimensione == FiltroSpunti.passo { return [s.passoVoce] }
        let v = faccette[s.id]?[dimensione] ?? []
        return v.isEmpty ? [AdattatoreFiltri.senza] : v
    }


    func passa(_ s: Spunto, _ f: FiltroSpunti, tranne: String? = nil) -> Bool {
        for (dimensione, scelte) in f.scelte where dimensione != tranne && !scelte.isEmpty && conosce(dimensione) {
            if Set(voci(s, dimensione)).isDisjoint(with: scelte) { return false }
        }
        return true
    }


    func conti(_ base: [Spunto], _ f: FiltroSpunti, _ dimensione: String) -> [String: Int] {
        var n: [String: Int] = [:]
        for s in base where passa(s, f, tranne: dimensione) {
            for v in Set(voci(s, dimensione)) { n[v, default: 0] += 1 }
        }
        return n
    }


    func quanti(_ base: [Spunto], _ f: FiltroSpunti) -> Int { base.reduce(0) { $0 + (passa($1, f) ? 1 : 0) } }




    static let gruppiDetti: [String: String] = ["strada": "cosa_ne_facciamo", "passo": "a_che_punto", "stato": "a_che_punto"]













    func dimensioneDelGruppo(_ gruppo: String) -> String? {
        guard gruppo != FiltroSpunti.gruppoPartenza, let g = gruppi.first(where: { $0.id == gruppo }) else { return nil }
        if let d = g.dimensione {
            return d.isEmpty ? nil : (d == FiltroSpunti.passo || dimensione(d) != nil ? d : nil)
        }
        if dimensione(gruppo) != nil { return gruppo }
        let nome = Self.chiave(g.nome)
        if !nome.isEmpty {
            if let d = dimensioni.first(where: { Self.chiave($0.nome) == nome }) { return d.id }
            if let p = dimensionePasso, Self.chiave(p.nome) == nome { return FiltroSpunti.passo }
        }
        if let d = Self.gruppiDetti[gruppo], dimensione(d) != nil { return d }
        return gruppo == FiltroSpunti.passo ? FiltroSpunti.passo : nil
    }


    private static func chiave(_ nome: String) -> String { nome.trimmingCharacters(in: .whitespaces).lowercased() }






    func gruppoVero(_ scelto: String) -> String {
        if scelto == FiltroSpunti.gruppoPartenza || dimensioneDelGruppo(scelto) != nil { return scelto }
        if let voluta = dimensione(scelto) != nil ? scelto : Self.gruppiDetti[scelto],
           let g = gruppi.first(where: { dimensioneDelGruppo($0.id) == voluta }) {
            return g.id
        }
        return FiltroSpunti.gruppoPartenza
    }



    func normale(_ f: FiltroSpunti) -> FiltroSpunti {
        var n = f
        n.scelte = f.scelte.filter { conosce($0.key) && !$0.value.isEmpty }
        n.ordine = ordineVero(f.ordine)
        n.gruppo = gruppoVero(f.gruppo)
        return n
    }



    func raggruppa(_ voci: [Spunto], _ gruppo: String, _ i: Inspiration) -> [(id: String, nome: String, voci: [Spunto])] {
        guard let dim = dimensioneDelGruppo(gruppoVero(gruppo)) else { return [] }
        if dim == FiltroSpunti.passo, let passi = i.passiMenu {
            var fuori: [(id: String, nome: String, voci: [Spunto])] = passi.compactMap { p in
                let g = voci.filter { $0.passoVoce == p.id }
                return g.isEmpty ? nil : (p.id, p.nome, g)
            }

            let noti = Set(passi.map(\.id))
            let altri = voci.filter { !noti.contains($0.passoVoce) }
            if !altri.isEmpty {
                let senza = AdattatoreFiltri.senza
                let nome = dimensionePasso?.voci.first { $0.id == senza }?.nome
                    ?? dimensione("a_che_punto")?.voci.first { $0.id == senza }?.nome ?? senza
                fuori.append((senza, nome, altri))
            }
            return fuori
        }
        guard let d = dimensione(dim) else { return [] }
        var perVoce: [String: [Spunto]] = [:]
        for s in voci { perVoce[self.voci(s, dim).first ?? AdattatoreFiltri.senza, default: []].append(s) }
        var fuori: [(id: String, nome: String, voci: [Spunto])] = d.voci.compactMap { v in
            perVoce.removeValue(forKey: v.id).map { (v.id, v.nome, $0) }
        }

        for (id, g) in perVoce.sorted(by: { $0.key < $1.key }) { fuori.append((id, id, g)) }
        return fuori
    }


    func saRaggruppare(_ gruppo: String) -> Bool {
        gruppo == FiltroSpunti.gruppoPartenza || gruppoVero(gruppo) != FiltroSpunti.gruppoPartenza
    }





    func ordina(_ voci: [Spunto], _ scelto: String) -> [Spunto] {
        let ordine = ordineVero(scelto)
        let recenti = voci.sorted { $0.quando > $1.quando }
        if let o = ordini.first(where: { $0.id == ordine }), let campo = Self.campo(o.campo) {
            let su = o.verso.lowercased().hasPrefix("asc")
            let pieni = recenti.filter { !campo($0).isEmpty }.sorted { su ? campo($0) < campo($1) : campo($0) > campo($1) }
            let vuoti = recenti.filter { campo($0).isEmpty }
            return o.vuoti == "in_cima" ? vuoti + pieni : pieni + vuoti
        }
        switch ordine {
        case "vecchi": return recenti.reversed()
        case "per_te":

            if voci.contains(where: { $0.per_te?.v != nil }) {
                return recenti.filter { $0.per_te?.v == true } + recenti.filter { $0.per_te?.v != true }
            }
            return recenti.filter { $0.tocca == "te" } + recenti.filter { $0.tocca != "te" }
        case "in_attesa", "attesa":
            let con = recenti.filter { !$0.propostoQuando.isEmpty }.sorted { $0.propostoQuando < $1.propostoQuando }
            return con + recenti.filter { $0.propostoQuando.isEmpty }
        default: return recenti
        }
    }



    func ordineVero(_ scelto: String) -> String {
        ordini.isEmpty || ordini.contains(where: { $0.id == scelto }) ? scelto : (ordini.first?.id ?? FiltroSpunti.ordinePartenza)
    }


    static func campo(_ nome: String) -> ((Spunto) -> String)? {
        switch nome {
        case "quando": return { $0.quando }
        case "proposto_quando": return { $0.propostoQuando }
        case "ultimo_gesto_quando": return { $0.ultimoGestoQuando }
        default: return nil
        }
    }
}









enum AdattatoreFiltri {

    static let senza = "senza"

    static let settimana = 7
    static let mese = 30


    static let uscite: Set<String> = ["riferimento", "cosa_da_fare", "letto", "non_serve"]



    struct Soglie {
        let adesso: String
        let oggi: String
        let settimana: String
        let mese: String

        init(_ ora: Date) {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = .current
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            adesso = f.string(from: ora)
            oggi = String(adesso.prefix(10))
            settimana = f.string(from: ora.addingTimeInterval(-Double(AdattatoreFiltri.settimana) * 86400))
            mese = f.string(from: ora.addingTimeInterval(-Double(AdattatoreFiltri.mese) * 86400))
        }
    }


    static func eData(_ iso: String) -> Bool {
        let b = Array(iso.utf8.prefix(19))
        return b.count == 19 && b[4] == 45 && b[7] == 45 && b[10] == 84 && b[13] == 58 && b[0] >= 48 && b[0] <= 57
    }

    static func quadro(_ i: Inspiration, adesso: Date = Date()) -> QuadroFiltri {
        let soglie = Soglie(adesso)
        var faccette: [String: [String: [String]]] = [:]
        for s in i.voci { faccette[s.id] = Self.faccette(s, i, soglie) }
        let d = dimensioni(i, faccette)
        return QuadroFiltri(dimensioni: d, ordini: ordini(i), gruppi: gruppi(i), pronti: pronti(i),
                            faccette: faccette, dalMotore: false)
    }



    static func faccette(_ s: Spunto, _ i: Inspiration, _ soglie: Soglie) -> [String: [String]] {
        let sc = s.lavorazione?.scopeFila
        return [
            "a_che_punto": [aChePunto(s, i)],
            "cosa_ne_facciamo": [cosaNeFacciamo(sc)],
            "che_cosa_e": [pieno(sc?.tipo)],
            "progetto": [pieno(s.progettoVista.lowercased())],
            "area": [pieno(sc?.area)],
            "le_tue_parole": parole(s),
            "domande": domande(sc),
            "da_dove": [pieno(s.piattaforma.lowercased())],
            "contenuto": [pieno(s.tipo)],
            "quando": quando(s.quando, soglie),
            "attesa": attesa(s.propostoQuando, soglie),
        ]
    }

    static func pieno(_ v: String?) -> String {
        let t = (v ?? "").trimmingCharacters(in: .whitespaces)
        return t.isEmpty ? senza : t
    }



    static func aChePunto(_ s: Spunto, _ i: Inspiration) -> String {
        let tipo = s.segno?.tipo ?? ""
        let passo = s.passoVoce
        if uscite.contains(passo), ["uscito", "da_fare", ""].contains(tipo) { return passo }
        switch tipo {
        case "da_confermare": return s.segno?.salute == "accento" ? "nuovi" : "da_confermare"
        case "domanda": return s.segno?.parola == i.testi["segno_ti_aspetta"] ? "ti_aspetta" : "domanda"
        case "da_dire": return "da_dire"
        case "da_far_partire", "da_avviare", "tocca_te": return "da_far_partire"
        case "da_leggere", "ritorno": return "da_leggere"
        case "da_scegliere": return "da_scegliere"
        case "task_da_creare": return "task_da_creare"
        case "agente_aperto": return "agente_aperto"
        case "lavora": return "al_lavoro"
        case "capisco", "scende": return "capisco"
        case "fermo": return "fermo"
        case "da_fare": return "cosa_da_fare"
        default: return senza
        }
    }


    static func cosaNeFacciamo(_ sc: ScopeSpunto?) -> String {
        guard let sc, !sc.strada.isEmpty else { return senza }
        if sc.strada == "cosa_da_fare", ["owner", "team"].contains(sc.chi) { return "cosa_da_fare_\(sc.chi)" }
        return sc.strada
    }


    static func parole(_ s: Spunto) -> [String] {
        let d = s.dettaglio
        let audio = !(s.frase_audio ?? "").isEmpty || !(d.audio_owner ?? []).isEmpty || d.parole_owner.contains { $0.fileAudio != nil }
        let scritte = !d.parole_owner.isEmpty || !s.frase_owner.isEmpty || d.nessuna_parola_vale == false
        var v: [String] = []
        if scritte { v.append("parole") }
        if audio { v.append("audio") }
        return v.isEmpty ? [senza] : v
    }


    static func domande(_ sc: ScopeSpunto?) -> [String] {
        let tutte = (sc?.domande ?? []) + (sc?.altre_domande ?? [])
        if tutte.isEmpty { return [senza] }
        return tutte.contains(where: \.policy) ? ["con", "legge"] : ["con"]
    }



    static func quando(_ iso: String, _ soglie: Soglie) -> [String] {
        guard eData(iso) else { return [senza] }

        let t = min(String(iso.prefix(19)), soglie.adesso)
        var v: [String] = []
        if t.hasPrefix(soglie.oggi) { v.append("oggi") }
        if t > soglie.settimana { v.append("settimana") }

        v.append(t >= soglie.mese ? "mese" : "prima")
        return v
    }



    static func attesa(_ iso: String, _ soglie: Soglie) -> [String] {
        guard eData(iso) else { return [senza] }
        let t = String(iso.prefix(19))
        var v = [t > soglie.settimana ? "meno_settimana" : "piu_settimana"]
        if t <= soglie.mese { v.append("piu_mese") }
        return v
    }




    static func t(_ i: Inspiration, _ chiave: String, _ ripiego: String, n: Int? = nil) -> String {
        let testo = i.testi[chiave].flatMap { $0.isEmpty ? nil : $0 } ?? ripiego
        return n.map { testo.replacingOccurrences(of: "{n}", with: "\($0)") } ?? testo
    }


    static func taskInAttivita(_ i: Inspiration) -> Bool {
        if case .si(true) = i.impostazioni?.voci.first(where: { $0.chiave == "task_in_attivita" })?.valore { return true }
        return false
    }


    static func maiuscola(_ t: String) -> String { t.prefix(1).uppercased() + t.dropFirst() }



    static func scelteScope(_ i: Inspiration) -> ScelteScope? {
        i.voci.lazy.compactMap { $0.lavorazione?.scopeFila?.scelte }.first { !$0.vuote }
    }

    static func dimensioni(_ i: Inspiration, _ faccette: [String: [String: [String]]]) -> [DimensioneFiltri] {
        let scelte = scelteScope(i)

        func voci(_ dimensione: String, _ elenco: [VoceFiltri], senzaNome: String) -> [VoceFiltri] {
            var viste = Set([senza])
            var fuori: [VoceFiltri] = []
            for v in elenco where viste.insert(v.id).inserted { fuori.append(v) }
            for s in i.voci {
                for v in faccette[s.id]?[dimensione] ?? [] where viste.insert(v).inserted { fuori.append(VoceFiltri(id: v, nome: v)) }
            }
            return fuori + [VoceFiltri(id: senza, nome: senzaNome)]
        }
        func vf(_ id: String, _ chiave: String, _ ripiego: String) -> VoceFiltri { VoceFiltri(id: id, nome: t(i, chiave, ripiego)) }
        let nonDetto = t(i, "filtri_voce_non_detto", "Not said yet")

        let aChePunto = [
            vf("nuovi", "segno_nuovo_da_confermare", "New, to confirm"),
            vf("da_confermare", "segno_da_confermare", "To confirm"),
            vf("domanda", "filtri_voce_domanda", "Questions for you"),
            vf("ti_aspetta", "segno_ti_aspetta", "Waiting for you in the terminal"),
            vf("da_dire", "segno_da_dire", "To tell the agent"),
            vf("da_far_partire", "segno_da_far_partire", "To start"),
            vf("da_leggere", "filtri_voce_da_leggere", "To read"),
            vf("da_scegliere", "segno_da_scegliere", "To choose"),
            vf("task_da_creare", "segno_task_da_creare", "Task to create"),
            vf("agente_aperto", "filtri_voce_agente_aperto", "Agent open in the terminal"),
            vf("al_lavoro", "segno_lavora", "Working"),
            vf("capisco", "segno_capisco", "Still figuring it out"),
            vf("fermo", "filtri_voce_fermo", "Stopped"),
            vf("riferimento", "menu_riferimento", "References"),
            vf("cosa_da_fare", "menu_cosa_da_fare", "To do"),
            vf("letto", "menu_letto", "Studies read"),
            vf("non_serve", "menu_non_serve", "Not needed"),
        ]
        let strade = [
            vf("sviluppo", "strada_sviluppo", "We develop it"),
            vf("studio", "strada_studio", "We study it"),


            taskInAttivita(i) ? vf("cosa_da_fare_owner", "strada_cosa_da_fare_attivita", "I put it in Tasks")
                : vf("cosa_da_fare_owner", "strada_cosa_da_fare_owner", "It's a thing to do, you do it"),
            vf("cosa_da_fare_team", "strada_cosa_da_fare_team", "It's for the team to do"),
            vf("cosa_da_fare", "strada_cosa_da_fare", "It's a thing to do"),
            vf("riferimento", "strada_riferimento", "I keep it as a reference"),
            vf("non_serve", "strada_non_serve", "Not needed"),
        ]
        let tipiScope = ["funzione", "strumento", "contenuto", "negozio_sito", "idea_societa", "lettura"]
        let cosaE = tipiScope.map { id in
            VoceFiltri(id: id, nome: scelte?.tipi.first { $0.id == id }?.parola ?? maiuscola(t(i, "tipo_\(id)", id)))
        }
        let progetti = i.progettiVista.filter { !$0.id.isEmpty }.map { VoceFiltri(id: $0.id.lowercased(), nome: $0.nome) }
        let aree = (scelte?.aree ?? []).map { VoceFiltri(id: $0.id, nome: $0.parola) }

        var perPiattaforma: [String: Int] = [:]
        for s in i.voci where !s.piattaforma.isEmpty { perPiattaforma[s.piattaforma, default: 0] += 1 }
        let piattaforme = perPiattaforma.sorted { ($0.value, $1.key) > ($1.value, $0.key) }
            .map { VoceFiltri(id: $0.key.lowercased(), nome: $0.key) }
        let contenuti = i.tipi.map { VoceFiltri(id: $0.id, nome: $0.nome) }

        var d = [
            DimensioneFiltri(id: "a_che_punto", nome: t(i, "filtri_dim_a_che_punto", "Status"),
                             voci: voci("a_che_punto", aChePunto, senzaNome: t(i, "filtri_voce_altri", "Set aside"))),
            DimensioneFiltri(id: "cosa_ne_facciamo",
                             nome: t(i, "filtri_dim_cosa_ne_facciamo", t(i, "scope_scegli_strada", "What we do with it")),
                             voci: voci("cosa_ne_facciamo", strade, senzaNome: nonDetto)),
            DimensioneFiltri(id: "che_cosa_e", nome: t(i, "filtri_dim_che_cosa_e", "What it is"),
                             voci: voci("che_cosa_e", cosaE, senzaNome: nonDetto)),
            DimensioneFiltri(id: "progetto", nome: t(i, "filtri_dim_progetto", t(i, "progetto", "Project")),
                             voci: voci("progetto", progetti, senzaNome: t(i, "senza_progetto", "Without project"))),
            DimensioneFiltri(id: "area", nome: t(i, "filtri_dim_area", t(i, "scope_area", "Area")),
                             voci: voci("area", aree, senzaNome: t(i, "filtri_voce_senza_area", "Without area"))),
            DimensioneFiltri(id: "le_tue_parole", nome: t(i, "filtri_dim_le_tue_parole", t(i, "le_tue_parole", "Your words")),
                             voci: [vf("parole", "filtri_voce_parole", "With your words"),
                                    vf("audio", "filtri_voce_audio", "With an audio of yours"),
                                    vf(senza, "filtri_voce_senza_parole", "Without your words")],
                             una: false),
            DimensioneFiltri(id: "domande", nome: t(i, "filtri_dim_domande", "Questions"),
                             voci: [vf("con", "filtri_voce_con_domande", "With questions"),
                                    vf("legge", "filtri_voce_domande_legge", "With legal questions"),
                                    vf(senza, "filtri_voce_senza_domande", "Without questions")],
                             una: false),
            DimensioneFiltri(id: "da_dove", nome: t(i, "filtri_dim_da_dove", "Where from"),
                             voci: voci("da_dove", piattaforme, senzaNome: t(i, "filtri_voce_senza_dove", "Unknown"))),
            DimensioneFiltri(id: "contenuto", nome: t(i, "filtri_dim_contenuto", "Format"),
                             voci: voci("contenuto", contenuti, senzaNome: t(i, "filtri_voce_senza_tipo", "Unknown"))),
            DimensioneFiltri(id: "quando", nome: t(i, "filtri_dim_quando", "When it arrived"),
                             voci: [vf("oggi", "filtri_voce_oggi", "Today"),
                                    VoceFiltri(id: "settimana", nome: t(i, "filtri_voce_ultimi_giorni", "In the last {n} days", n: settimana)),
                                    VoceFiltri(id: "mese", nome: t(i, "filtri_voce_ultimi_giorni", "In the last {n} days", n: mese)),
                                    VoceFiltri(id: "prima", nome: t(i, "filtri_voce_giorni_fa", "More than {n} days ago", n: mese)),
                                    vf(senza, "filtri_voce_senza_data", "Without date")],
                             una: false),
        ]

        if i.voci.contains(where: { !$0.propostoQuando.isEmpty }) {
            d.append(DimensioneFiltri(
                id: "attesa", nome: t(i, "filtri_dim_attesa", "How long it's been waiting"),
                voci: [VoceFiltri(id: "meno_settimana", nome: t(i, "filtri_voce_meno_di", "Less than {n} days", n: settimana)),
                       VoceFiltri(id: "piu_settimana", nome: t(i, "filtri_voce_prima_di", "More than {n} days", n: settimana)),
                       VoceFiltri(id: "piu_mese", nome: t(i, "filtri_voce_prima_di", "More than {n} days", n: mese)),
                       vf(senza, "filtri_voce_non_ti_aspetta", "Not waiting for you")],
                una: false))
        }
        return d
    }



    static func ordini(_ i: Inspiration) -> [SceltaFiltri] {
        var o = [
            SceltaFiltri(id: "recenti", nome: t(i, "ordine_recenti", "Most recent"), campo: "quando", verso: "discendente",
                         vuoti: "in_fondo"),
            SceltaFiltri(id: "vecchi", nome: t(i, "ordine_vecchi", "Oldest"), campo: "quando", verso: "ascendente",
                         vuoti: "in_fondo"),
        ]
        if i.voci.contains(where: { !$0.propostoQuando.isEmpty }) {
            o.append(SceltaFiltri(id: "attesa", nome: t(i, "filtri_ordine_attesa", "Waiting for you the longest"),
                                  campo: "proposto_quando", verso: "ascendente", vuoti: "in_fondo"))
        }

        o.append(SceltaFiltri(id: "per_te", nome: t(i, "ordine_per_te", "Yours first")))
        return o
    }



    static func gruppi(_ i: Inspiration) -> [SceltaFiltri] {
        [
            SceltaFiltri(id: "niente", nome: t(i, "filtri_gruppo_niente", "No group"), dimensione: ""),
            SceltaFiltri(id: "progetto", nome: t(i, "filtri_dim_progetto", t(i, "progetto", "Project")), dimensione: "progetto"),
            SceltaFiltri(id: "strada", nome: t(i, "filtri_dim_cosa_ne_facciamo", t(i, "scope_scegli_strada", "What we do with it")),
                         dimensione: "cosa_ne_facciamo"),
            SceltaFiltri(id: "a_che_punto", nome: t(i, "filtri_dim_a_che_punto", "Status"), dimensione: "a_che_punto"),
        ]
    }


    static func pronti(_ i: Inspiration) -> [FiltroConNome] {
        let daConfermare = ["nuovi", "da_confermare"]
        let attesa = i.voci.contains(where: { !$0.propostoQuando.isEmpty }) ? "attesa" : FiltroSpunti.ordinePartenza
        func p(_ id: String, _ ripiego: String, _ scelte: [String: [String]], _ ordina: String = FiltroSpunti.ordinePartenza,
               _ raggruppa: String = FiltroSpunti.gruppoPartenza) -> FiltroConNome {
            FiltroConNome(id: id, nome: t(i, "filtri_pronto_\(id)", ripiego),
                          filtro: FiltroSpunti(scelte: scelte, ordine: ordina, gruppo: raggruppa))
        }
        return [
            p("nuovi", "New to confirm", ["a_che_punto": ["nuovi"]]),
            p("arretrati", "To confirm, proposed earlier", ["a_che_punto": ["da_confermare"]], attesa, "strada"),
            p("riferimento", "To keep as a reference", ["a_che_punto": daConfermare, "cosa_ne_facciamo": ["riferimento"]]),
            p("team", "To do for the team", ["a_che_punto": daConfermare, "cosa_ne_facciamo": ["cosa_da_fare_team"]],
              FiltroSpunti.ordinePartenza, "progetto"),
            p("mie_parole", "With your words, to confirm", ["a_che_punto": daConfermare, "le_tue_parole": ["parole"]]),
            p("legge", "Legal questions", ["domande": ["legge"]], FiltroSpunti.ordinePartenza, "progetto"),
            p("terminale", "Waiting for you in the terminal", ["a_che_punto": ["ti_aspetta", "da_dire"]], attesa),
        ]
    }
}






struct BarraFiltri: View {
    let ispirazione: Inspiration
    let scheda: String
    let quadro: QuadroFiltri

    let base: [Spunto]

    var conRicerca = false
    @Environment(Store.self) private var store

    var body: some View {
        let f = store.filtroInspiration

        let altri = !f.dimensioniScelte.isEmpty || store.vistaInspiration != nil
            || !store.cercaInspiration.trimmingCharacters(in: .whitespaces).isEmpty
        let contiPasso = altri ? quadro.conti(base, f, FiltroSpunti.passo) : nil
        let quanti = f.dimensioniScelte.filter(quadro.conosce).count




        RigaControlli(conRicerca: conRicerca) {
            MenuFase(ispirazione: ispirazione, scheda: scheda, conti: contiPasso)
            PulsanteFiltri(ispirazione: ispirazione, quanti: quanti)
            MenuFiltriSalvati(ispirazione: ispirazione, quadro: quadro)
            MenuOrdineEGruppi(ispirazione: ispirazione, quadro: quadro)
            if conRicerca {
                TextField(ispirazione.t("cerca"), text: Binding(get: { store.cercaInspiration }, set: { store.cercaInspiration = $0 }))
                    .textFieldStyle(.roundedBorder)
            }
        }
    }
}






struct RigaControlli: Layout {
    var conRicerca: Bool
    var spazio: CGFloat = 8
    var interlinea: CGFloat = 8
    var ricercaMin: CGFloat = 150
    var ricercaMax: CGFloat = 240

    private func posti(_ larghezza: CGFloat, _ pezzi: Subviews) -> (posti: [(Int, CGRect)], alta: CGFloat) {
        let n = pezzi.count - (conRicerca && !pezzi.isEmpty ? 1 : 0)
        let misure = (0..<n).map { pezzi[$0].sizeThatFits(.unspecified) }
        var righe: [[Int]] = [[]]
        var x: CGFloat = 0
        for k in 0..<n {
            if x > 0, x + misure[k].width > larghezza {
                righe.append([])
                x = 0
            }
            righe[righe.count - 1].append(k)
            x += misure[k].width + spazio
        }
        let ultima = righe[righe.count - 1]
        let fine = ultima.reduce(CGFloat(0)) { $0 + misure[$1].width } + spazio * CGFloat(max(0, ultima.count - 1))
        let resta = larghezza - fine - (ultima.isEmpty ? 0 : spazio)
        let accanto = conRicerca && resta >= ricercaMin
        let largaRicerca = accanto ? min(ricercaMax, resta) : larghezza
        let altaRicerca = conRicerca ? pezzi[n].sizeThatFits(ProposedViewSize(width: largaRicerca, height: nil)).height : 0
        var fuori: [(Int, CGRect)] = []
        var y: CGFloat = 0
        for (i, riga) in righe.enumerated() {
            let conLaRicerca = accanto && i == righe.count - 1
            if riga.isEmpty && !conLaRicerca { continue }
            let alta = max(riga.map { misure[$0].height }.max() ?? 0, conLaRicerca ? altaRicerca : 0)
            var xx: CGFloat = 0
            for k in riga {
                fuori.append((k, CGRect(x: xx, y: y + (alta - misure[k].height) / 2, width: misure[k].width, height: misure[k].height)))
                xx += misure[k].width + spazio
            }
            if conLaRicerca {
                fuori.append((n, CGRect(x: larghezza - largaRicerca, y: y + (alta - altaRicerca) / 2, width: largaRicerca,
                                        height: altaRicerca)))
            }
            y += alta + interlinea
        }
        if conRicerca && !accanto {
            fuori.append((n, CGRect(x: 0, y: y, width: largaRicerca, height: altaRicerca)))
            y += altaRicerca + interlinea
        }
        return (fuori, max(0, y - interlinea))
    }


    private func ideale(_ pezzi: Subviews) -> CGFloat {
        let n = pezzi.count - (conRicerca && !pezzi.isEmpty ? 1 : 0)
        let controlli = (0..<n).reduce(CGFloat(0)) { $0 + pezzi[$1].sizeThatFits(.unspecified).width }
            + spazio * CGFloat(max(0, n - 1))
        return controlli + (conRicerca ? (n > 0 ? spazio : 0) + ricercaMax : 0)
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let larghezza = proposal.width.flatMap { $0.isFinite ? $0 : nil } ?? ideale(subviews)
        return CGSize(width: larghezza, height: posti(larghezza, subviews).alta)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for (k, r) in posti(bounds.width, subviews).posti {
            subviews[k].place(at: CGPoint(x: bounds.minX + r.minX, y: bounds.minY + r.minY), anchor: .topLeading,
                              proposal: ProposedViewSize(width: r.width, height: r.height))
        }
    }
}


struct PulsanteFiltri: View {
    let ispirazione: Inspiration
    let quanti: Int
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        let parola = Parole.filtri(ispirazione)
        Toggle(isOn: $store.pannelloFiltriInspiration) {
            Label(quanti > 0 ? "\(parola) \(quanti)" : parola, systemImage: "line.3.horizontal.decrease.circle")
                .monospacedDigit()
        }
        .toggleStyle(.button)
        .tint(quanti > 0 ? Color.accentColor : nil)
        .fixedSize()
        .help(Parole.t(ispirazione, "aiuto_filtri",
                       "You can pick several items. Under the same title one is enough, under different titles they all count. "
                           + "The number next to each item takes into account the choices under the other titles."))
    }
}









struct MenuOrdineEGruppi: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        let ordine = quadro.ordineVero(store.filtroInspiration.ordine)
        let gruppo = quadro.gruppoVero(store.filtroInspiration.gruppo)
        let acceso = ordine != FiltroSpunti.ordinePartenza || gruppo != FiltroSpunti.gruppoPartenza
        let nomeOrdine = quadro.ordini.first { $0.id == ordine }?.nome ?? ""
        let nomeGruppo = quadro.gruppi.first { $0.id == gruppo }?.nome ?? ""

        let adesso = [nomeOrdine,
                      gruppo == FiltroSpunti.gruppoPartenza ? nomeGruppo : "\(Parole.raggruppaPer(i)) \(nomeGruppo.lowercased())"]
            .filter { !$0.isEmpty }.joined(separator: " · ")
        let spiega = [i.t("aiuto_ordine"),
                      Parole.t(i, "aiuto_raggruppa", "The ideas split into groups, each with its title and its number.")]
            .filter { !$0.isEmpty }.joined(separator: " ")

        let etichetta = ordine != FiltroSpunti.ordinePartenza && !nomeOrdine.isEmpty
            ? Parole.corto(nomeOrdine, 28) : Parole.ordineEGruppi(i)
        Menu {
            Section(Parole.ordinaPer(i)) {
                ForEach(quadro.ordini) { o in
                    Toggle(o.nome, isOn: Binding(get: { ordine == o.id },
                                                 set: { if $0 { store.filtroInspiration.ordine = o.id } }))
                }
            }
            Section(Parole.raggruppaPer(i)) {
                ForEach(quadro.gruppi) { g in
                    Toggle(g.nome, isOn: Binding(get: { gruppo == g.id },
                                                 set: { if $0 { store.filtroInspiration.gruppo = g.id } }))
                }
            }
        } label: {
            Label(etichetta, systemImage: acceso ? "arrow.up.arrow.down.circle.fill" : "arrow.up.arrow.down")
        }
        .fixedSize()
        .tint(acceso ? Color.accentColor : nil)
        .help([adesso, spiega].filter { !$0.isEmpty }.joined(separator: ". "))

        .accessibilityLabel(acceso ? "\(Parole.ordineEGruppi(i)). \(adesso.replacingOccurrences(of: " · ", with: ", "))"
                                   : Parole.ordineEGruppi(i))
    }
}



struct MenuFiltriSalvati: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        let salvati = store.filtriSalvati(i)
        let acceso = store.filtroSalvatoAcceso(i, quadro)
        let qualcosa = store.filtroDaSalvare
        Menu {
            VociFiltriSalvati(ispirazione: i, quadro: quadro, salvati: salvati, acceso: acceso, qualcosa: qualcosa)
        } label: {

            Label(acceso.map { Parole.corto($0.nome, 28) } ?? Parole.salvati(i),
                  systemImage: acceso == nil ? "bookmark" : "bookmark.fill")
        }
        .fixedSize()
        .tint(acceso == nil ? nil : Color.accentColor)
        .help(Parole.t(i, "aiuto_filtri_salvati",
                       "The ready filters and the ones you saved. Pick one and all its choices come back, including the order and the groups."))
    }
}


struct VociFiltriSalvati: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    let salvati: [FiltroConNome]
    let acceso: FiltroConNome?
    let qualcosa: Bool
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        if !quadro.pronti.isEmpty {
            Section(Parole.pronti(i)) {
                ForEach(quadro.pronti) { p in voce(p) }
            }
        }
        if !salvati.isEmpty {
            Section(Parole.tuoi(i)) {
                ForEach(salvati) { p in voce(p) }
            }
        }
        Divider()
        Button(Parole.salvaQuesto(i)) { store.chiediNomeFiltroInspiration = true }
            .disabled(!qualcosa)
            .help(Parole.t(i, "filtri_salva_aiuto", "You find it here under the name you give it"))
        if !salvati.isEmpty {
            Menu(Parole.togliSalvato(i)) {
                ForEach(salvati) { p in
                    Button(p.nome) { Task { await store.togliFiltroSalvatoInspiration(p.nome) } }
                        .help(Parole.t(i, "filtri_togli_aiuto", "It leaves the list, you can save it again whenever you want"))
                }
            }
        }
    }

    private func voce(_ p: FiltroConNome) -> some View {
        let n = quadro.quanti(ispirazione.voci, p.filtro)
        return Toggle(isOn: Binding(get: { acceso?.id == p.id && acceso?.nome == p.nome }, set: { si in
            if si { store.applicaFiltroInspiration(p.filtro) } else { store.togliFiltriInspiration() }
        })) {
            Text("\(p.nome) \(n)")
        }
        .help(p.aiuto)
    }
}





struct GettoniFiltri: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    let restano: Int
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        let f = store.filtroInspiration
        FilaACapo(spazio: 8, interlinea: 6) {
            Text(Parole.conto(i, restano)).font(Testo.secondario).foregroundStyle(.secondary).monospacedDigit()
            if let v = store.vistaInspiration, let r = i.testa?.righeTesta?.first(where: { $0.vista == v }) {
                Gettone(testo: Parole.gettoneVista(i, r), aiuto: r.pulsante_aiuto, togli: Parole.togli(i)) {
                    store.vistaInspiration = nil
                }
            }
            if let p = f.passoScelto, let passo = i.passiMenu?.first(where: { $0.id == p }) {
                Gettone(testo: passo.nome, aiuto: passo.frase, togli: Parole.togli(i)) {
                    store.faseInspiration = nil
                }
            }
            ForEach(quadro.dimensioni.filter { !(f.scelte[$0.id] ?? []).isEmpty }) { d in
                let nomi = (f.scelte[d.id] ?? []).map { d.nome(di: $0) }.joined(separator: ", ")
                Gettone(testo: nomi, aiuto: "\(d.nome) · \(nomi)", togli: Parole.togli(i)) {
                    store.filtroInspiration.scelte[d.id] = nil
                }
            }
            Button(Parole.togliTutti(i)) { store.togliFiltriInspiration() }
                .buttonStyle(.link).font(Testo.secondario)
            if store.filtroDaSalvare {
                Button(Parole.salvaQuesto(i)) { store.chiediNomeFiltroInspiration = true }
                    .buttonStyle(.link).font(Testo.secondario)
            }
        }
    }
}


struct Gettone: View {
    let testo: String
    let aiuto: String
    let togli: String
    let azione: () -> Void

    var body: some View {
        HStack(spacing: 5) {
            Text(testo).font(Testo.secondario.weight(.medium)).lineLimit(1)
            Button(action: azione) {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help(togli)
            .accessibilityLabel(togli)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 3)
        .background(Superficie.selezione, in: Capsule())
        .fixedSize()
        .help(aiuto)
    }
}






struct PannelloFiltri: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    let base: [Spunto]
    let restano: Int
    @Environment(Store.self) private var store



    static let larghezza: CGFloat = 264

    var body: some View {
        let i = ispirazione
        let f = store.filtroInspiration

        let tutti = FiltroSpunti.partenza
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Parole.filtri(i)).font(Testo.titoloSezione)
                Text(Parole.conto(i, restano)).font(Testo.secondario).foregroundStyle(.secondary).monospacedDigit()
                Spacer(minLength: 4)
                Button { store.pannelloFiltriInspiration = false } label: {
                    Image(systemName: "xmark").font(.system(size: 11, weight: .semibold))
                }
                .buttonStyle(.borderless)
                .help(i.t("chiudi"))
                .accessibilityLabel(i.t("chiudi"))
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 10)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(quadro.dimensioni) { d in
                        SezioneFiltri(ispirazione: i, dimensione: d, conti: quadro.conti(base, f, d.id),
                                      esistono: quadro.conti(i.voci, tutti, d.id), scelte: f.scelte[d.id] ?? [])
                    }
                    if !f.senzaScelte || store.vistaInspiration != nil {
                        HStack(spacing: 12) {
                            Button(Parole.togliTutti(i)) { store.togliFiltriInspiration() }
                            if store.filtroDaSalvare {
                                Button(Parole.salvaQuesto(i)) { store.chiediNomeFiltroInspiration = true }
                            }
                        }
                        .buttonStyle(.link)
                        .font(Testo.secondario)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(width: Self.larghezza)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Superficie.scheda)
    }
}



struct PannelloFiltriBacheca: View {
    @Environment(Store.self) private var store

    var body: some View {
        if let i = store.inspiration {
            let scheda = Bacheca.selezione(i, store: store)
            let quadro = QuadroFiltri.di(i)
            let base = Bacheca.base(i.voci, store: store, scheda: scheda, ispirazione: i)
            PannelloFiltri(ispirazione: i, quadro: quadro, base: base,
                           restano: Bacheca.inFila(base, store: store, ispirazione: i, quadro: quadro).count)
        }
    }
}


struct SezioneFiltri: View {
    let ispirazione: Inspiration
    let dimensione: DimensioneFiltri
    let conti: [String: Int]
    let esistono: [String: Int]
    let scelte: [String]
    @Environment(Store.self) private var store

    var body: some View {
        let d = dimensione
        let aVista = d.voci.filter { (esistono[$0.id] ?? 0) > 0 || scelte.contains($0.id) }

        let fuori = scelte.filter { s in !d.voci.contains { $0.id == s } }.map { VoceFiltri(id: $0, nome: $0) }
        if !aVista.isEmpty || !fuori.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(d.nome).font(Testo.titoloGruppo)
                        .help(d.aiuto)
                    Spacer(minLength: 4)
                    if !scelte.isEmpty {
                        Button(Parole.togli(ispirazione)) { store.filtroInspiration.scelte[d.id] = nil }
                            .buttonStyle(.link)
                            .font(Testo.minimo)
                    }
                }
                ForEach(aVista + fuori) { v in riga(v) }
            }
        }
    }

    private func riga(_ v: VoceFiltri) -> some View {
        let n = conti[v.id] ?? 0
        let scelta = scelte.contains(v.id)
        return Toggle(isOn: Binding(get: { scelta }, set: { store.filtroInspiration.scegli(dimensione.id, v.id, $0) })) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(v.nome).lineLimit(2).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 6)
                Text("\(n)").monospacedDigit().foregroundStyle(.secondary)
            }
            .foregroundStyle(n == 0 && !scelta ? Color.secondary : Color.primary)
        }
        .toggleStyle(.checkbox)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}



struct MenuFiltriInPagina: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri
    let base: [Spunto]
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        let f = store.filtroInspiration
        let altri = !f.dimensioniScelte.isEmpty || store.vistaInspiration != nil
        let conti = altri ? quadro.conti(base, f, FiltroSpunti.passo) : nil

        FilaACapo(spazio: 28, interlinea: 14, centra: false) {
            colonna(i.testi["passi_menu_titolo"] ?? i.t("fase")) {
                ForEach(i.passiMenu ?? []) { p in
                    Toggle(MenuFase.testoPasso(p, i, conti), isOn: .constant((f.passoScelto ?? "tutti") == p.id))
                }
            }
            colonna(Parole.ordinaPer(i)) {
                ForEach(quadro.ordini) { o in Toggle(o.nome, isOn: .constant(quadro.ordineVero(f.ordine) == o.id)) }
            }
            colonna(Parole.raggruppaPer(i)) {
                ForEach(quadro.gruppi) { g in Toggle(g.nome, isOn: .constant(quadro.gruppoVero(f.gruppo) == g.id)) }
            }
            colonna(Parole.salvati(i)) {
                VociFiltriSalvati(ispirazione: i, quadro: quadro, salvati: store.filtriSalvati(i),
                                  acceso: store.filtroSalvatoAcceso(i, quadro), qualcosa: store.filtroDaSalvare)
            }
        }
        .toggleStyle(.checkbox)
        .padding(12)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
    }

    private func colonna(_ titolo: String, @ViewBuilder _ voci: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(titolo).font(.headline)
            voci()
        }
        .frame(minWidth: 150, alignment: .leading)
    }
}





struct FoglioSalvaFiltro: View {
    let ispirazione: Inspiration
    let quadro: QuadroFiltri

    var nellaPagina = false
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi
    @State private var nome = ""
    @FocusState private var dentro: Bool

    var body: some View {
        let i = ispirazione
        VStack(alignment: .leading, spacing: 12) {
            Text(Parole.salva(i)).font(Testo.titoloSezione)

            Text(store.riassuntoFiltroInspiration(i, quadro))
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField(Parole.t(i, "filtri_nome_segnaposto", "The filter name"), text: $nome)
                .textFieldStyle(.roundedBorder)
                .focused($dentro)
                .onSubmit(fai)
            HStack {
                Spacer()
                Button(Parole.t(i, "annulla", "Cancel"), role: .cancel) { esci() }
                    .keyboardShortcut(.cancelAction)
                Button(Parole.t(i, "filtri_salva_pulsante", "Save"), action: fai)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(nome.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(18)
        .frame(width: 380)
        .onAppear { if !nellaPagina { dentro = true } }
    }

    private func esci() {
        if nellaPagina { store.chiediNomeFiltroInspiration = false } else { chiudi() }
    }

    private func fai() {
        let n = nome.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        esci()
        Task { await store.salvaFiltroInspiration(n) }
    }
}





enum Parole {
    static func t(_ i: Inspiration, _ chiave: String, _ ripiego: String) -> String {
        i.testi[chiave].flatMap { $0.isEmpty ? nil : $0 } ?? ripiego
    }

    static func filtri(_ i: Inspiration) -> String { t(i, "filtri_titolo", "Filters") }
    static func salvati(_ i: Inspiration) -> String { t(i, "filtri_salvati", "Saved filters") }

    static func salva(_ i: Inspiration) -> String { t(i, "filtri_salva", "Save this filter") }
    static func salvaQuesto(_ i: Inspiration) -> String { salva(i).hasSuffix("…") ? salva(i) : salva(i) + "…" }
    static func ordinaPer(_ i: Inspiration) -> String { t(i, "filtri_ordine", "Sort by") }
    static func raggruppaPer(_ i: Inspiration) -> String { t(i, "filtri_gruppo", "Group by") }

    static func ordineEGruppi(_ i: Inspiration) -> String { t(i, "filtri_ordine_e_gruppi", "Order and groups") }
    static func pronti(_ i: Inspiration) -> String { t(i, "filtri_pronti", "Ready") }
    static func tuoi(_ i: Inspiration) -> String { t(i, "filtri_tuoi", "Yours") }
    static func togli(_ i: Inspiration) -> String { t(i, "filtri_togli", t(i, "togli", "Remove")) }
    static func togliTutti(_ i: Inspiration) -> String { t(i, "filtri_togli_tutti", t(i, "togli_filtri", "Remove the filters")) }
    static func togliSalvato(_ i: Inspiration) -> String { t(i, "filtri_togli_salvato", "Remove a saved filter") }





    static func gettoneVista(_ i: Inspiration, _ r: RigaTesta) -> String {
        if !r.gettone.isEmpty { return r.gettone }
        switch r.vista {
        case "nuovi": return t(i, "filtri_pronto_nuovi", "New to confirm")
        case "di_prima": return t(i, "filtri_pronto_arretrati", "To confirm, proposed earlier")
        default: return senzaNumeroInTesta(r.frase)
        }
    }



    static func senzaNumeroInTesta(_ frase: String) -> String {
        let resto = frase.drop(while: { $0.isNumber || $0 == "." }).drop(while: { $0 == " " })
        guard resto.count < frase.count, let prima = resto.first else { return frase }
        return prima.uppercased() + resto.dropFirst()
    }


    static func corto(_ t: String, _ n: Int) -> String { t.count <= n ? t : String(t.prefix(n - 1)) + "…" }


    static func conto(_ i: Inspiration, _ n: Int) -> String {
        if n == 1 { return t(i, "spunti_conto_uno", "1 spunto") }
        return t(i, "spunti_conto", "{n} spunti").replacingOccurrences(of: "{n}", with: "\(n)")
    }
}



extension Store {
    static let chiaveFiltroInspiration = "inspirationFiltro"
    static let chiaveVistaInspiration = "inspirationVista"
    static let chiavePannelloFiltri = "inspirationPannelloFiltri"




    static func misuraBacheca(_ dati: Data) {
        guard ProcessInfo.processInfo.environment["SB_MISURA_BACHECA"] == "1" else { return }
        func ms(_ d: Duration) -> Double { Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15 }
        var decodifiche: [Double] = []
        var quadri: [Double] = []
        var ultima: Inspiration?
        for _ in 0..<7 {
            let t0 = ContinuousClock.now
            ultima = try? JSONDecoder().decode(Inspiration.self, from: dati)
            decodifiche.append(ms(ContinuousClock.now - t0))
        }
        if let i = ultima {
            for _ in 0..<7 {
                let t0 = ContinuousClock.now
                _ = QuadroFiltri.di(i)
                quadri.append(ms(ContinuousClock.now - t0))
            }
        }
        func riga(_ v: [Double]) -> String {
            let s = v.sorted()
            return s.isEmpty ? "-" : String(format: "min %.1f mediana %.1f max %.1f", s[0], s[s.count / 2], s[s.count - 1])
        }
        let motore = ultima.map { QuadroFiltri.di($0).dalMotore ? "motore" : "adattatore" } ?? "?"
        FileHandle.standardError.write(
            "MISURA_BACHECA byte \(dati.count) · decodifica \(riga(decodifiche)) · quadro (\(motore)) \(riga(quadri))\n"
                .data(using: .utf8)!)
    }


    static func filtroInspirationRicordato() -> FiltroSpunti {
        guard let dati = UserDefaults.standard.data(forKey: chiaveFiltroInspiration),
              let f = try? JSONDecoder().decode(FiltroSpunti.self, from: dati) else { return .partenza }
        return f
    }

    static func ricordaFiltroInspiration(_ f: FiltroSpunti) {
        if let dati = try? JSONEncoder().encode(f) { UserDefaults.standard.set(dati, forKey: chiaveFiltroInspiration) }
    }


    func filtriSalvati(_ i: Inspiration) -> [FiltroConNome] {
        (i.filtriSalvatiMotore ?? filtriSalvatiInspiration).filter { !$0.nome.isEmpty }
    }


    func filtroSalvatoAcceso(_ i: Inspiration, _ q: QuadroFiltri) -> FiltroConNome? {
        guard vistaInspiration == nil, cercaInspiration.trimmingCharacters(in: .whitespaces).isEmpty,
              !filtroInspiration.senzaScelte else { return nil }
        let adesso = q.normale(filtroInspiration)
        return (filtriSalvati(i) + q.pronti).first { q.normale($0.filtro).uguale(adesso) }
    }



    var filtroDaSalvare: Bool { !filtroInspiration.senzaScelte && (inspiration?.filtriSalvatiSiLegge ?? true) }


    var pannelloFiltriAVista: Bool {
        guard pannelloFiltriInspiration, sezione == .inspiration, stato != nil, let i = inspiration,
              ricerca.trimmingCharacters(in: .whitespaces).isEmpty else { return false }
        return spuntoAperto.map { id in !(i.voci + i.a_parte).contains { $0.id == id } } ?? true
    }




    func togliFiltriInspiration() {
        filtroInspiration.scelte = [:]
        vistaInspiration = nil
        cercaInspiration = ""
    }



    func applicaFiltroInspiration(_ f: FiltroSpunti) {
        filtroInspiration = f
        vistaInspiration = nil
        cercaInspiration = ""
    }



    func potaFiltroInspiration() {
        guard let i = inspiration else { return }
        let q = QuadroFiltri.di(i)
        var f = filtroInspiration
        for k in f.scelte.keys where !q.conosce(k) { f.scelte[k] = nil }
        if let p = f.passoScelto, let passi = i.passiMenu, !passi.contains(where: { $0.id == p }) {
            f.scelte[FiltroSpunti.passo] = nil
        }



        f.gruppo = q.gruppoVero(f.gruppo)
        f.ordine = q.ordineVero(f.ordine)
        if f != filtroInspiration { filtroInspiration = f }
    }


    func riassuntoFiltroInspiration(_ i: Inspiration, _ q: QuadroFiltri) -> String {
        let f = filtroInspiration
        var pezzi: [String] = []
        if let p = f.passoScelto, let passo = i.passiMenu?.first(where: { $0.id == p }) { pezzi.append(passo.nome) }
        for d in q.dimensioni {
            if let scelte = f.scelte[d.id], !scelte.isEmpty { pezzi.append(scelte.map { d.nome(di: $0) }.joined(separator: ", ")) }
        }
        let ordine = q.ordineVero(f.ordine)
        let gruppo = q.gruppoVero(f.gruppo)
        if ordine != FiltroSpunti.ordinePartenza, let o = q.ordini.first(where: { $0.id == ordine }) { pezzi.append(o.nome) }
        if gruppo != FiltroSpunti.gruppoPartenza, let g = q.gruppi.first(where: { $0.id == gruppo }) {
            pezzi.append("\(Parole.raggruppaPer(i)) \(g.nome.lowercased())")
        }
        return pezzi.joined(separator: " · ")
    }




    func leggiFiltriSalvatiInspiration() async {
        guard inspiration?.filtriSalvatiMotore == nil else { return }
        for argomenti in [["inspiration", "filtri-salvati"], ["inspiration", "filtri-salvati", "leggi"]] {
            let r = await motore.chiedi(argomenti, scadenza: 30)
            if let e = try? JSONDecoder().decode(EsitoFiltriSalvati.self, from: r.dati), e.ok, let f = e.filtri {
                filtriSalvatiInspiration = f
                return
            }
        }
    }



    func salvaFiltroInspiration(_ nome: String) async {
        var f = filtroInspiration
        if let i = inspiration {
            let q = QuadroFiltri.di(i)
            f.ordine = q.ordineVero(f.ordine)
            f.gruppo = q.gruppoVero(f.gruppo)
        }
        let codifica = JSONEncoder()
        codifica.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        guard let dati = try? codifica.encode(f), let json = String(data: dati, encoding: .utf8) else { return }
        await gestoFiltriSalvati(["--da", "owner", "--", "salva", nome, json])
    }



    func togliFiltroSalvatoInspiration(_ nome: String) async {
        await gestoFiltriSalvati(["--da", "owner", "--", "togli", nome])
    }



    private func gestoFiltriSalvati(_ argomenti: [String]) async {
        let r = await motore.chiedi(["inspiration", "filtri-salvati"] + argomenti, scadenza: 30)
        let esito = try? JSONDecoder().decode(EsitoFiltriSalvati.self, from: r.dati)
        guard let esito else {
            let titolo = inspiration?.testi["errore_titolo"] ?? "It didn't work"
            erroreGesto = r.scaduto
                ? "\(titolo). \(inspiration?.testi["motore_scaduto"] ?? "The engine did not respond in time. Try again")"
                : "\(titolo). The engine did not respond as it should."
            return
        }
        guard esito.ok else {
            erroreGesto = esito.messaggio ?? (inspiration?.testi["errore_titolo"] ?? "It didn't work")
            return
        }
        if let f = esito.filtri { filtriSalvatiInspiration = f } else { await leggiFiltriSalvatiInspiration() }
        if let m = esito.messaggio?.trimmingCharacters(in: .whitespacesAndNewlines), !m.isEmpty { notizia = m }

        await caricaInspiration(motivo: "after the saved filters")
    }
}




struct FilaACapo: Layout {
    var spazio: CGFloat = 8
    var interlinea: CGFloat = 6
    var centra = true

    private func righe(_ larghezza: CGFloat, _ pezzi: Subviews) -> [[(Int, CGSize)]] {
        var tutte: [[(Int, CGSize)]] = [[]]
        var x: CGFloat = 0
        for (k, p) in pezzi.enumerated() {
            let d = p.sizeThatFits(.unspecified)
            if x > 0, x + d.width > larghezza {
                tutte.append([])
                x = 0
            }
            tutte[tutte.count - 1].append((k, d))
            x += d.width + spazio
        }
        return tutte.filter { !$0.isEmpty }
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let larghezza = proposal.width ?? .infinity
        let r = righe(larghezza, subviews)
        let alta = r.reduce(0) { $0 + ($1.map(\.1.height).max() ?? 0) } + interlinea * CGFloat(max(0, r.count - 1))
        let larga = r.map { riga in riga.reduce(0) { $0 + $1.1.width } + spazio * CGFloat(max(0, riga.count - 1)) }.max() ?? 0
        return CGSize(width: proposal.width ?? larga, height: alta)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for riga in righe(bounds.width, subviews) {
            let alta = riga.map(\.1.height).max() ?? 0
            var x = bounds.minX
            for (k, d) in riga {
                subviews[k].place(at: CGPoint(x: x, y: y + (centra ? (alta - d.height) / 2 : 0)), anchor: .topLeading,
                                proposal: ProposedViewSize(d))
                x += d.width + spazio
            }
            y += alta + interlinea
        }
    }
}
