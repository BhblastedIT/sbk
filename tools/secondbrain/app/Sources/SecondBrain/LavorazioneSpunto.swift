import AVFoundation
import AppKit
import SwiftUI
















struct FaseInspiration: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let n: Int
    let aspettano_te: Int
    let aiuto: String

    let frase: String?
    let vuota: String?
}

struct EsitoInspiration: Codable, Hashable, Identifiable {
    let id: String
    let parole: String
}

struct Lavorazione: Codable, Hashable {
    let fase: String
    let tocca: String
    let tocca_frase: String

    let stato_scheda: String?
    let perche: PercheSpunto
    let domande: [DomandaSpunto]
    let sessione: SessioneSpunto
    let piano: PianoSpunto
    let scheda: String?
    let lavoro: LavoroSpunto
    let cartella: String

    let cartella_registro: String?
    let azioni: AzioniLavorazione


    let percorso: [PassoPercorso]?
    let percorso_parole: [String: String]?

    let dopo_frase: String?

    let comprensione: ComprensioneLavorazione?

    let rilettura: RiletturaLavorazione?

    let passo_dopo: PassoDopo?

    let smistamento: SmistamentoSpunto?


    let stato_riquadro: String?



    let passo: Tollera<String>?
    let percorso6: Tollera<[PassoFila]>?
    let scope: Tollera<ScopeSpunto>?
    let adesso: Tollera<AdessoSpunto>?
    let fatto: Tollera<[PassoFatto]>?
    let dopo: Tollera<[PassoDopoFila]>?
    let cambio_scope: Tollera<CambioScope>?
    let uscita: Tollera<UscitaSpunto>?

    let task_manca: Tollera<Bool>?



    var adessoFila: AdessoSpunto? {
        guard let a = adesso?.v, !a.frase.isEmpty || !a.titolo.isEmpty || a.pulsante != nil else { return nil }
        return a
    }
    var passoAcceso: String { passo?.v ?? adessoFila?.passo ?? "" }
    var passiFila: [PassoFila] { (percorso6?.v ?? []).filter { !$0.nome.isEmpty } }
    var scopeFila: ScopeSpunto? { scope?.v }
    var fattoFila: [PassoFatto] { (fatto?.v ?? []).filter { !$0.nome.isEmpty } }
    var dopoFila: [PassoDopoFila] { (dopo?.v ?? []).filter { !$0.nome.isEmpty } }
    var cambioFila: CambioScope? { cambio_scope?.v.flatMap { $0.vuoto ? nil : $0 } }
    var uscitaFila: UscitaSpunto? { uscita?.v.flatMap { $0.frase.isEmpty ? nil : $0 } }

    var rigaRaddrizzaFatto: String? { scopeFila.flatMap { $0.raddrizza_riga.isEmpty ? nil : $0.raddrizza_riga } }

    var cartellaRegistro: String {
        if let c = cartella_registro, !c.isEmpty { return c }
        return URL(fileURLWithPath: cartella).deletingLastPathComponent().deletingLastPathComponent().path
    }
}




struct Tollera<T: Codable & Hashable>: Codable, Hashable {
    let v: T?

    init(from decoder: Decoder) throws {
        v = try? decoder.singleValueContainer().decode(T.self)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(v)
    }
}


struct Pezzi<K: CodingKey> {
    let c: KeyedDecodingContainer<K>?

    init(_ decoder: Decoder, _ chiavi: K.Type) { c = try? decoder.container(keyedBy: chiavi) }

    func testo(_ k: K) -> String { (try? c?.decodeIfPresent(String.self, forKey: k)) ?? "" }
    func si(_ k: K) -> Bool { (try? c?.decodeIfPresent(Bool.self, forKey: k)) ?? false }
    func numero(_ k: K) -> Int? { try? c?.decodeIfPresent(Int.self, forKey: k) }
    func uno<T: Decodable>(_ k: K) -> T? { try? c?.decodeIfPresent(T.self, forKey: k) }
    func elenco<T: Decodable>(_ k: K) -> [T] { (try? c?.decodeIfPresent([T].self, forKey: k)) ?? [] }
}


struct RigaFila: Codable, Hashable {
    let testo: String
    let quando: String

    enum CodingKeys: String, CodingKey { case testo, quando, frase, parola }

    init(from decoder: Decoder) throws {
        if let s = try? decoder.singleValueContainer().decode(String.self) {
            testo = s
            quando = ""
            return
        }
        let p = Pezzi(decoder, CodingKeys.self)
        testo = [p.testo(.testo), p.testo(.frase), p.testo(.parola)].first { !$0.isEmpty } ?? ""
        quando = p.testo(.quando)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(testo, forKey: .testo)
        try c.encode(quando, forKey: .quando)
    }
}


struct SceltaFila: Codable, Hashable, Identifiable {
    let id: String
    let parola: String

    enum CodingKeys: String, CodingKey { case id, parola, nome }

    init(from decoder: Decoder) throws {
        if let s = try? decoder.singleValueContainer().decode(String.self) {
            id = s
            parola = s
            return
        }
        let p = Pezzi(decoder, CodingKeys.self)
        let parola = p.testo(.parola).isEmpty ? p.testo(.nome) : p.testo(.parola)
        id = p.testo(.id).isEmpty ? parola : p.testo(.id)
        self.parola = parola.isEmpty ? id : parola
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(parola, forKey: .parola)
    }
}


struct PassoFila: Codable, Hashable {
    let id: String
    let nome: String
    let stato: String
    let quando: String
    let riassunto: String
    let rivedi: Bool

    enum CodingKeys: String, CodingKey { case id, nome, stato, quando, riassunto, rivedi }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        nome = p.testo(.nome)
        stato = p.testo(.stato)
        quando = p.testo(.quando)
        riassunto = p.testo(.riassunto)
        rivedi = p.si(.rivedi)
    }
}


struct DomandaFila: Codable, Hashable, Identifiable {
    let id: String
    let testo: String
    let risposta: String
    let policy: Bool

    enum CodingKeys: String, CodingKey { case id, testo, risposta, policy }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        testo = p.testo(.testo)
        risposta = p.testo(.risposta)
        policy = p.si(.policy)
    }
}

struct ScelteScope: Codable, Hashable {
    let strade: [SceltaFila]
    let tipi: [SceltaFila]
    let progetti: [SceltaFila]
    let aree: [SceltaFila]

    let chi: [SceltaFila]

    enum CodingKeys: String, CodingKey { case strade, tipi, progetti, aree, chi }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        strade = p.elenco(.strade)
        tipi = p.elenco(.tipi)
        progetti = p.elenco(.progetti)
        aree = p.elenco(.aree)
        chi = p.elenco(.chi)
    }

    var vuote: Bool { strade.isEmpty && tipi.isEmpty && progetti.isEmpty && aree.isEmpty }
}


struct ScopeSpunto: Codable, Hashable {
    let versione: Int?
    let cosa_intendi: String
    let strada: String
    let strada_frase: String
    let tipo: String
    let progetto: String
    let area: String

    let chi: String
    let dove_arrivare: String
    let dove_va_frase: String
    let info_chiave: [RigaFila]
    let su_cosa_poggia_frase: String
    let prima_dicevo: [RigaFila]
    let confermato: Bool
    let confermato_frase: String
    let domande: [DomandaFila]
    let altre_domande: [DomandaFila]
    let altre_domande_frase: String
    let scelte: ScelteScope?

    let parole_di_owner_accanto: [RigaFila]


    let proposta_in_attesa: PropostaInAttesa?

    let le_tue_parole: TueParole?

    let raddrizza_riga: String

    let aspetta_task: Bool

    enum CodingKeys: String, CodingKey {
        case versione, cosa_intendi, strada, strada_frase, tipo, progetto, area, chi, dove_arrivare, dove_va_frase, info_chiave,
             su_cosa_poggia_frase, prima_dicevo, confermato, confermato_frase, domande, altre_domande, altre_domande_frase,
             scelte, parole_di_owner_accanto, proposta_in_attesa, le_tue_parole, raddrizza_riga, aspetta_task
    }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        versione = p.numero(.versione)
        cosa_intendi = p.testo(.cosa_intendi)
        strada = p.testo(.strada)
        strada_frase = p.testo(.strada_frase)
        tipo = p.testo(.tipo)
        progetto = p.testo(.progetto)
        area = p.testo(.area)
        chi = p.testo(.chi)
        dove_arrivare = p.testo(.dove_arrivare)
        dove_va_frase = p.testo(.dove_va_frase)

        info_chiave = Self.righe(p, .info_chiave)
        su_cosa_poggia_frase = p.testo(.su_cosa_poggia_frase)
        prima_dicevo = Self.righe(p, .prima_dicevo)
        confermato = p.si(.confermato)
        confermato_frase = p.testo(.confermato_frase)
        domande = p.elenco(.domande).filter { (d: DomandaFila) in !d.testo.isEmpty }
        altre_domande = p.elenco(.altre_domande).filter { (d: DomandaFila) in !d.testo.isEmpty }
        altre_domande_frase = p.testo(.altre_domande_frase)
        scelte = p.uno(.scelte)
        parole_di_owner_accanto = Self.righe(p, .parole_di_owner_accanto)
        let pr: PropostaInAttesa? = p.uno(.proposta_in_attesa)
        proposta_in_attesa = pr.flatMap { $0.frase.isEmpty ? nil : $0 }
        let tp: TueParole? = p.uno(.le_tue_parole)
        le_tue_parole = tp.flatMap { $0.prima.isEmpty && $0.altre.isEmpty && !$0.audio ? nil : $0 }
        raddrizza_riga = p.testo(.raddrizza_riga)
        aspetta_task = p.si(.aspetta_task)
    }

    static func righe(_ p: Pezzi<CodingKeys>, _ k: CodingKeys) -> [RigaFila] {
        let tutte: [RigaFila] = p.elenco(k)
        if !tutte.isEmpty { return tutte.filter { !$0.testo.isEmpty } }
        let una: RigaFila? = p.uno(k)
        return una.map { $0.testo.isEmpty ? [] : [$0] } ?? []
    }


    var pieno: Bool { !cosa_intendi.isEmpty || !strada_frase.isEmpty || !dove_arrivare.isEmpty || !domande.isEmpty }
}



struct TueParole: Codable, Hashable {
    let prima: String
    let altre: [String]
    let audio: Bool

    let audio_voci: [AudioParola]
    let tutte_parola: String

    enum CodingKeys: String, CodingKey { case prima, altre, audio, audio_voci, tutte_parola }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        prima = p.testo(.prima)
        altre = (p.elenco(.altre) as [String]).filter { !$0.isEmpty }

        let voci: [AudioParola] = p.elenco(.audio_voci) + p.elenco(.audio)
        audio_voci = voci.filter { !$0.file.isEmpty || !$0.trascrizione.isEmpty }
        audio = p.si(.audio) || !audio_voci.isEmpty
        tutte_parola = p.testo(.tutte_parola)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(prima, forKey: .prima)
        try c.encode(altre, forKey: .altre)
        try c.encode(audio, forKey: .audio)
        try c.encode(tutte_parola, forKey: .tutte_parola)
    }
}

struct AudioParola: Codable, Hashable {
    let file: String
    let quando: String
    let trascrizione: String

    let frase: String

    enum CodingKeys: String, CodingKey { case file, quando, trascrizione, frase }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        file = p.testo(.file)
        quando = p.testo(.quando)
        trascrizione = p.testo(.trascrizione)
        frase = p.testo(.frase)
    }
}


struct PropostaInAttesa: Codable, Hashable {
    let frase: String
    let quando: String
    let campi: [String]

    enum CodingKeys: String, CodingKey { case frase, quando, campi }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        frase = p.testo(.frase)
        quando = p.testo(.quando)
        campi = p.elenco(.campi)
    }
}



struct PulsanteFila: Codable, Hashable {
    let verbo: String
    let riga: String
    let parola: String
    let parola_con_testo: String
    let aiuto: String


    let riga_con_testo: String
    let aiuto_con_testo: String

    enum CodingKeys: String, CodingKey { case verbo, riga, parola, parola_con_testo, aiuto, riga_con_testo, aiuto_con_testo }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        verbo = p.testo(.verbo)
        riga = p.testo(.riga)
        parola = p.testo(.parola)
        parola_con_testo = p.testo(.parola_con_testo)
        aiuto = p.testo(.aiuto)
        riga_con_testo = p.testo(.riga_con_testo)
        aiuto_con_testo = p.testo(.aiuto_con_testo)
    }
}

struct CampoFila: Codable, Hashable {
    let segnaposto: String
    let audio: Bool

    let valido: Bool

    enum CodingKeys: String, CodingKey { case segnaposto, audio, valido }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        segnaposto = p.testo(.segnaposto)
        audio = p.si(.audio)
        valido = p.c != nil
    }
}


struct AdessoSpunto: Codable, Hashable {
    let passo: String
    let titolo: String
    let chi: String
    let frase: String
    let salute: String
    let pulsante: PulsanteFila?
    let secondari: [PulsanteFila]
    let campo: CampoFila?
    let poi: String
    let avanzamento: String

    let domande: [DomandaFila]

    let altre_domande: [DomandaFila]
    let altre_domande_frase: String

    enum CodingKeys: String, CodingKey {
        case passo, titolo, chi, frase, salute, pulsante, secondari, campo, poi, avanzamento, domande, altre_domande,
             altre_domande_frase
    }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        passo = p.testo(.passo)
        titolo = p.testo(.titolo)
        chi = p.testo(.chi)
        frase = p.testo(.frase)
        salute = p.testo(.salute)

        let pu: PulsanteFila? = p.uno(.pulsante)
        pulsante = pu.flatMap { $0.parola.isEmpty || $0.verbo.isEmpty ? nil : $0 }
        secondari = p.elenco(.secondari).filter { (s: PulsanteFila) in !s.parola.isEmpty && !s.verbo.isEmpty }
        let ca: CampoFila? = p.uno(.campo)
        campo = ca.flatMap { $0.valido ? $0 : nil }
        poi = p.testo(.poi)
        avanzamento = p.testo(.avanzamento)
        domande = p.elenco(.domande).filter { (d: DomandaFila) in !d.testo.isEmpty }
        altre_domande = p.elenco(.altre_domande).filter { (d: DomandaFila) in !d.testo.isEmpty }
        altre_domande_frase = p.testo(.altre_domande_frase)
    }


    func ha(_ verbo: String) -> Bool { pulsante?.verbo == verbo || secondari.contains { $0.verbo == verbo } }
}


struct PassoFatto: Codable, Hashable {
    let passo: String
    let nome: String
    let quando_frase: String
    let riassunto: String
    let rivedi: Bool
    let raddrizza: Bool


    let riapri: PulsanteFila?

    enum CodingKeys: String, CodingKey { case passo, nome, quando_frase, riassunto, rivedi, raddrizza, riapri }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        passo = p.testo(.passo)
        nome = p.testo(.nome)
        quando_frase = p.testo(.quando_frase)
        riassunto = p.testo(.riassunto)
        rivedi = p.si(.rivedi)
        raddrizza = p.si(.raddrizza)
        let r: PulsanteFila? = p.uno(.riapri)
        riapri = r.flatMap { $0.parola.isEmpty || $0.verbo.isEmpty ? nil : $0 }
    }
}

struct PassoDopoFila: Codable, Hashable {
    let passo: String
    let nome: String
    let frase: String

    enum CodingKeys: String, CodingKey { case passo, nome, frase }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        passo = p.testo(.passo)
        nome = p.testo(.nome)
        frase = p.testo(.frase)
    }
}


struct CambioScope: Codable, Hashable {
    let adesso_e: String
    let rifa: [RifaPasso]
    let resta_frase: String
    let pulsante_rifai: String
    let pulsante_tieni: String
    let aiuto_rifai: String
    let aiuto_tieni: String

    let da_decidere: Bool

    enum CodingKeys: String, CodingKey {
        case adesso_e, rifa, resta_frase, pulsante_rifai, pulsante_tieni, aiuto_rifai, aiuto_tieni, da_decidere
    }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        adesso_e = p.testo(.adesso_e)
        rifa = p.elenco(.rifa).filter { (r: RifaPasso) in !r.frase.isEmpty || !r.passo.isEmpty }
        resta_frase = p.testo(.resta_frase)
        pulsante_rifai = p.testo(.pulsante_rifai)
        pulsante_tieni = p.testo(.pulsante_tieni)
        aiuto_rifai = p.testo(.aiuto_rifai)
        aiuto_tieni = p.testo(.aiuto_tieni)
        da_decidere = p.si(.da_decidere)
    }

    var vuoto: Bool { adesso_e.isEmpty && rifa.isEmpty && pulsante_rifai.isEmpty && pulsante_tieni.isEmpty }
}

struct RifaPasso: Codable, Hashable {
    let passo: String
    let nome: String
    let quando_frase: String
    let frase: String

    enum CodingKeys: String, CodingKey { case passo, nome, quando_frase, frase }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        passo = p.testo(.passo)
        nome = p.testo(.nome)
        quando_frase = p.testo(.quando_frase)
        frase = p.testo(.frase)
    }
}


struct UscitaSpunto: Codable, Hashable {
    let tipo: String
    let frase: String
    let riapri_parola: String
    let riapri_aiuto: String
    let task: TaskUscita?


    let crea_task: PulsanteFila?

    enum CodingKeys: String, CodingKey { case tipo, frase, riapri_parola, riapri_aiuto, task, crea_task }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        tipo = p.testo(.tipo)
        frase = p.testo(.frase)
        riapri_parola = p.testo(.riapri_parola)
        riapri_aiuto = p.testo(.riapri_aiuto)
        let t: TaskUscita? = p.uno(.task)
        task = t.flatMap { $0.dove_frase.isEmpty ? nil : $0 }
        let ct: PulsanteFila? = p.uno(.crea_task)
        crea_task = ct.flatMap { $0.parola.isEmpty || $0.verbo.isEmpty ? nil : $0 }
    }
}

struct TaskUscita: Codable, Hashable {
    let dove_frase: String
    let id: String



    let dove: String
    let stato: String
    let stato_nome: String
    let rifai: PulsanteFila?

    enum CodingKeys: String, CodingKey { case dove_frase, id, dove, stato, stato_nome, rifai }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        dove_frase = p.testo(.dove_frase)
        id = p.testo(.id)
        dove = p.testo(.dove)
        stato = p.testo(.stato)
        stato_nome = p.testo(.stato_nome)
        let r: PulsanteFila? = p.uno(.rifai)
        rifai = r.flatMap { $0.parola.isEmpty || $0.verbo.isEmpty ? nil : $0 }
    }
}


struct PassoPercorso: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let stato: String
    let quando: String?
    let aiuto: String?
}

struct PercheSpunto: Codable, Hashable {
    let c_e: Bool
    let esito: String
    let esito_parole: String

    let esito_proposto_parole: String?
    let testo: String
    let dove_arrivare: String
    let sicurezza: String
    let su_cosa_poggia: String

    let su_cosa_poggia_frase: String?
    let confermato: Bool
    let confermato_quando: String

    let stato_frase: String?
    let corretto: Bool?
    let correzione: String
    let correzione_in_arrivo: Bool?
    let correzione_in_trascrizione: Bool
    let correzione_stato: String?

    let correzione_frase: String?
    let correzione_audio_file: String?
    let correzione_durata: String?

    let prima_dicevo: String?
    let riletto: Bool?

    var eCorretto: Bool { corretto ?? (!correzione.isEmpty || correzione_in_trascrizione) }
    var inArrivo: Bool { correzione_in_arrivo ?? (correzione_in_trascrizione && correzione.isEmpty) }
    var fileCorrezione: String? { (correzione_audio_file?.isEmpty == false) ? correzione_audio_file : nil }
}

struct DomandaSpunto: Codable, Hashable, Identifiable {
    let id: String
    let testo: String
    let serve_per: String
    let chiusa: Bool
    let risposta: String
    let in_trascrizione: Bool

    let da: String?
    let audio: String?
    let durata: String?

    let stato: String?
    let stato_frase: String?
    let quando_risposta: String?
    let da_sistema: Bool?

    let insieme: Bool?

    let parole_sentite: String?

    var fileAudio: String? { (audio?.isEmpty == false) ? audio : nil }
    var insiemeAltre: Bool { insieme ?? false }
    var paroleSentite: String { parole_sentite ?? "" }
    var statoAudio: String { stato ?? (in_trascrizione ? "in_trascrizione" : "") }
    var dalSistema: Bool { da_sistema ?? false }

    var inViaggio: Bool { in_trascrizione || statoAudio == "in_trascrizione" || statoAudio == "aspetta_memoria" }
    var dallaSessioneDiLavoro: Bool { da == "sessione di lavoro" }
}

struct SessioneSpunto: Codable, Hashable {
    let aperta: Bool
    let titolo: String
    let quando: String
    let c_e: Bool?
    let chiusa_quando: String?
}

struct PianoSpunto: Codable, Hashable {
    let c_e: Bool
    let passi: [String]
    let dati: [String]
    let punto_di_arrivo: String
    let cosa_non_fare: [String]
    let permessi: String
}

struct LavoroSpunto: Codable, Hashable {
    let avviato: Bool
    let titolo: String
    let quando: String
    let permessi: String
    let ritorno: String?
    let ritorno_parziale: String?
    let ritorno_letto: Bool
    let task: String
    let finito_quando: String?
    let letto_quando: String?
    let chiuso: Bool?


    let task_dove: Tollera<String>?
    let task_stato: Tollera<String>?
    let task_stato_nome: Tollera<String>?
    let task_rifai: PulsanteFila?
}

struct AzioniLavorazione: Codable, Hashable {
    let conferma: Bool
    let ci_lavoriamo: Bool
    let vai_sessione: Bool
    let avvia: Bool
    let vai_lavoro: Bool
    let ritorno_letto: Bool
    let rispondi: Bool

    let correggi: Bool?

    let capisci: Bool?
    let vai_comprensione: Bool?

    let capisci_pannello: Bool?


    let capisci_pannello_menu: Bool?


    let avvia_task: Tollera<Bool>?
}


struct ComprensioneLavorazione: Codable, Hashable {
    let aperta: Bool
    let quando: String?
    let titolo: String?
    let sottofondo: Bool?
}


struct RiletturaLavorazione: Codable, Hashable {
    let aperta: Bool
    let quando: String?
    let fatta: Bool?
    let ferma: String?
}



struct PassoDopo: Codable, Hashable {
    let c_e: Bool
    let stato: String
    let titolo: String
    let frase: String
    let quando: String?
    let perche_breve: String?
    let dove_arrivare: String?
    let esito_parole: String?
    let azioni: AzioniPassoDopo?
}



struct SmistamentoSpunto: Codable, Hashable {
    let c_e: Bool
    let confermato: Bool
    let esito: String?
    let riga_esito: String?
    let riga_dove: String?
    let riga_nota: String?
    let riga_motivo: String?
    let task: String?
    let esiti: [EsitoSmistamento]?
    let azioni: AzioniSmistamento
    let parole: [String: String]?

    func t(_ k: String, _ o: String) -> String { parole?[k] ?? o }
}

struct EsitoSmistamento: Codable, Hashable, Identifiable {
    let id: String
    let parole: String
}

struct AzioniSmistamento: Codable, Hashable {
    let si: Bool
    let cambia: Bool
    let rimetti: Bool
}

struct AzioniPassoDopo: Codable, Hashable {
    let conferma: Bool
    let correggi: Bool
    let ci_lavoriamo: Bool
    let vai_sessione: Bool
}

struct EsitoAzione: Codable {
    let ok: Bool
    let messaggio: String?



    let avviso: Bool?


    let task: TaskDelGesto?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decode(Bool.self, forKey: .ok)
        messaggio = try? c.decodeIfPresent(String.self, forKey: .messaggio)
        avviso = try? c.decodeIfPresent(Bool.self, forKey: .avviso)
        task = try? c.decodeIfPresent(TaskDelGesto.self, forKey: .task)
        if avviso == true, !ok, let messaggio { Self.avvisi.insert(messaggio) }
    }




    var taskInAttivita: String? {
        guard let t = task, t.dove == "attivita" else { return nil }
        let id = t.id.hasPrefix("attivita:") ? String(t.id.dropFirst("attivita:".count)) : t.id
        return id.isEmpty ? nil : id
    }




    nonisolated(unsafe) static var avvisi: Set<String> = []
    static func eAvviso(_ frase: String) -> Bool { avvisi.contains(frase) }
}


struct TaskDelGesto: Codable, Hashable {
    let dove: String
    let id: String
    let c_era: Bool

    enum CodingKeys: String, CodingKey { case dove, id, c_era }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        dove = p.testo(.dove)
        id = p.testo(.id)
        c_era = p.si(.c_era)
    }
}





struct Registrazione: Equatable {
    let file: URL
    let voce: String
    let chiave: String
    let cosa: String
    let esito: String
    let cartella: String
    let cartellaRegistro: String
    let secondi: Int


    static let alloScope = "scope"

    var argomenti: [String] {
        var a: [String]
        if chiave == "scope" {


            a = ["scope", voce, "--audio", file.path]
            if !esito.isEmpty { a += ["--versione", esito] }
        } else if chiave == "perche" {
            a = ["conferma", voce, "--audio", file.path]
            if !esito.isEmpty { a += ["--esito", esito] }
        } else if esito.hasPrefix(Self.alloScope), !chiave.isEmpty, chiave != "dettaglio" {



            let v = esito.dropFirst(Self.alloScope.count).trimmingCharacters(in: .whitespaces)
            a = ["scope", voce, "--domanda", chiave, "--audio", file.path] + (v.isEmpty ? [] : ["--versione", v])
        } else if chiave.isEmpty || chiave == "dettaglio" {
            a = ["rispondi", voce, "--audio", file.path]
        } else {
            a = ["rispondi", voce, "--domanda", chiave, "--audio", file.path]
        }
        return a + ["--durata", "\(secondi)"]
    }
}








@MainActor
@Observable
final class Registratore {
    enum Stato: Equatable { case fermo, chiedo, registra, invio, negato, corta, annullata }


    struct DaParte: Equatable {
        let registrazione: Registrazione
        let corta: Bool
    }

    private(set) var stato: Stato = .fermo
    private(set) var secondi = 0
    private(set) var voce: String?
    private(set) var chiave: String?

    private(set) var cosa = ""
    private(set) var esito = ""
    private(set) var cartella: String?
    private(set) var cartellaRegistro: String?
    private(set) var daParte: DaParte?

    private(set) var problema: String?
    private(set) var problemaPer: String?
    private(set) var negato = false


    private(set) var livello: Double = 0
    private(set) var picco: Float = -160



    var bassa: Bool { stato == .registra && secondi >= 4 && picco < -40 }
    @ObservationIgnored private var registratore: AVAudioRecorder?
    @ObservationIgnored private var orologio: Timer?
    @ObservationIgnored private var file: URL?
    @ObservationIgnored private var inizio: Date?
    @ObservationIgnored private var osservatore: NSObjectProtocol?

    static let condiviso = Registratore()

    init() {

        osservatore = NotificationCenter.default.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil,
                                                             queue: .main) { _ in
            Task { @MainActor in Registratore.condiviso.ricontrollaPermesso() }
        }
    }


    var occupato: Bool { stato == .registra || stato == .chiedo || stato == .invio }

    func e(_ voce: String, _ chiave: String) -> Bool { self.voce == voce && self.chiave == chiave }



    func comincia(voce: String, chiave: String, cosa: String, esito: String, cartella: String, cartellaRegistro: String,
                  testi: (String) -> String) async {
        guard stato != .registra, stato != .chiedo, stato != .invio else { return }
        problema = nil
        problemaPer = nil
        daParte = nil
        self.voce = voce
        self.chiave = chiave
        self.cosa = cosa
        self.esito = esito
        self.cartella = cartella
        self.cartellaRegistro = cartellaRegistro
        var consentito: Bool
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            consentito = true
        case .notDetermined:
            stato = .chiedo
            registra("microphone permission requested from macOS")
            consentito = await AVCaptureDevice.requestAccess(for: .audio)
            registra(consentito ? "permission granted by you" : "permission denied by you")
        default:
            consentito = false
            registra("microphone permission denied in System Settings")
        }


        guard stato != .registra else { return }
        guard consentito else {
            stato = .negato
            negato = true
            problemaPer = chiave
            problema = testi("microfono_negato")
            return
        }
        let dir = URL(fileURLWithPath: cartella).appendingPathComponent("audio")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            stato = .fermo
            problemaPer = chiave
            problema = testi("microfono_non_parte")
            registra("did not start, the audio folder cannot be created: \(error.localizedDescription)")
            return
        }
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        let adesso = Date()
        let url = dir.appendingPathComponent("\(f.string(from: adesso))-\(chiave).m4a")
        let impostazioni: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        let r: AVAudioRecorder
        do {
            r = try AVAudioRecorder(url: url, settings: impostazioni)
        } catch {
            stato = .fermo
            problemaPer = chiave
            problema = testi("microfono_non_parte")
            registra("did not start: \(error.localizedDescription)")
            return
        }
        r.isMeteringEnabled = true
        guard r.record() else {
            stato = .fermo
            problemaPer = chiave
            problema = testi("microfono_non_parte")
            registra("did not start: the recorder did not start (no audio input?)")
            return
        }

        let biglietto: [String: String] = ["voce": voce, "chiave": chiave, "inizio": Self.iso(adesso)]
        if let dati = try? JSONSerialization.data(withJSONObject: biglietto, options: [.sortedKeys]) {
            try? dati.write(to: Self.biglietto(url), options: .atomic)
        }
        registratore = r
        file = url
        inizio = Date()
        secondi = 0
        livello = 0
        picco = -160
        stato = .registra
        registra("start, \(url.lastPathComponent)")

        let t = Timer(timeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in Registratore.condiviso.aggiornaSecondi() }
        }
        RunLoop.main.add(t, forMode: .common)
        orologio = t
    }

    private func aggiornaSecondi() {
        guard stato == .registra, let inizio else { return }
        secondi = Int(Date().timeIntervalSince(inizio))
        if let reg = registratore {
            reg.updateMeters()
            let p = reg.peakPower(forChannel: 0)
            livello = Double(max(0, min(1, (p + 50) / 50)))
            picco = max(picco, p)
        }
    }

    private func durataAttuale() -> Int {
        let dal = registratore?.currentTime ?? 0
        let da = inizio.map { Date().timeIntervalSince($0) } ?? 0
        return Int(max(dal, da).rounded())
    }

    private func spegni() {
        orologio?.invalidate()
        orologio = nil
        registratore?.stop()
        registratore = nil
        inizio = nil
    }

    private func dati(_ f: URL, _ durata: Int) -> Registrazione {
        Registrazione(file: f, voce: voce ?? "", chiave: chiave ?? "", cosa: cosa, esito: esito, cartella: cartella ?? "",
                      cartellaRegistro: cartellaRegistro ?? "", secondi: durata)
    }



    func ferma() -> Registrazione? {
        guard stato == .registra, let f = file else { return nil }
        let durata = durataAttuale()
        spegni()
        file = nil
        secondi = durata
        if durata < 1 {
            let spostato = mettiDaParte(f)
            daParte = DaParte(registrazione: dati(spostato, durata), corta: true)
            stato = .corta
            registra("stopped under a second, set aside, \(spostato.lastPathComponent)")
            return nil
        }
        stato = .invio
        registra("stopped and sent, \(durata) s, peak \(Int(picco)) dB, \(f.lastPathComponent)")
        return dati(f, durata)
    }



    func annulla() {
        guard stato == .registra, let f = file else { return }
        let durata = durataAttuale()
        spegni()
        file = nil
        secondi = durata
        let spostato = mettiDaParte(f)
        daParte = DaParte(registrazione: dati(spostato, durata), corta: false)
        stato = .annullata
        registra("canceled after \(durata) s, set aside, \(spostato.lastPathComponent)")
    }

    private func mettiDaParte(_ f: URL) -> URL {
        let fm = FileManager.default
        let dir = f.deletingLastPathComponent().appendingPathComponent("annullati")
        let dest = dir.appendingPathComponent(f.lastPathComponent)
        do {
            try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            try fm.moveItem(at: f, to: dest)
        } catch {

            registra("not moved to annullati: \(error.localizedDescription)")
            return f
        }
        let b = Self.biglietto(f)
        if fm.fileExists(atPath: b.path) { try? fm.moveItem(at: b, to: dir.appendingPathComponent(b.lastPathComponent)) }
        return dest
    }


    func riprendiDaParte() -> Registrazione? {
        guard let d = daParte else { return nil }
        daParte = nil
        stato = .invio
        registra("sent anyway, \(d.registrazione.secondi) s, \(d.registrazione.file.lastPathComponent)")
        return d.registrazione
    }


    func lasciaDaParte() {
        daParte = nil
        if stato == .annullata || stato == .corta { stato = .fermo }
    }


    func inviata(_ errore: String?) {
        if stato == .invio { stato = .fermo }
        registra(errore == nil ? "the engine took the audio" : "the engine said no: \(errore ?? ""). The file stays with its ticket")
    }

    func chiudiProblema() {
        problema = nil
        problemaPer = nil
        if stato == .negato { stato = .fermo }
    }

    func ricontrollaPermesso() {
        guard negato, AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else { return }
        negato = false
        chiudiProblema()
        registra("microphone permission recovered on returning to the app")
    }


    static func apriImpostazioni() {
        if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
            NSWorkspace.shared.open(u)
        }
    }





    func registra(_ evento: String) {
        let riga = "\(Self.iso(Date())) voce=\(voce ?? "-") chiave=\(chiave ?? "-") stato=\(stato) \(evento)\n"
        if let c = cartella, !c.isEmpty {
            Self.appendi(riga, a: URL(fileURLWithPath: c).appendingPathComponent("registratore.log"))
        }
        let radice = (cartellaRegistro?.isEmpty == false ? cartellaRegistro : nil)
            ?? cartella.map { URL(fileURLWithPath: $0).deletingLastPathComponent().deletingLastPathComponent().path }
        if let radice, !radice.isEmpty {
            Self.appendi(riga, a: URL(fileURLWithPath: radice).appendingPathComponent("registro-app.log"))
        }
    }

    static func appendi(_ riga: String, a percorso: URL) {
        let fm = FileManager.default
        if !fm.fileExists(atPath: percorso.path) {
            try? fm.createDirectory(at: percorso.deletingLastPathComponent(), withIntermediateDirectories: true)
            fm.createFile(atPath: percorso.path, contents: nil)
        }
        guard let h = try? FileHandle(forWritingTo: percorso) else { return }
        defer { try? h.close() }
        _ = try? h.seekToEnd()
        try? h.write(contentsOf: Data(riga.utf8))
    }

    static func biglietto(_ audio: URL) -> URL { audio.deletingPathExtension().appendingPathExtension("json") }

    static func iso(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: d)
    }

    static func durata(_ s: Int) -> String { String(format: "%d:%02d", s / 60, s % 60) }
}



struct RiquadroLavorazione: View {
    let spunto: Spunto
    let lavorazione: Lavorazione
    let ispirazione: Inspiration


    var prossimo: (() -> Void)?
    @Environment(Store.self) private var store
    @State private var correggendo = false

    @State private var correggendoInFondo = false
    @State private var correzione = ""
    @State private var esito = ""
    @State private var rispondendo: String?
    @State private var risposta = ""
    @State private var dettaglio = ""

    @State private var inCorso: String?
    @State private var errore: String?
    @State private var chiediAvvio = false
    @State private var conTask = false
    @State private var testoScheda: String?
    @State private var testoRitorno: String?

    @State private var risposteAperte: Bool?
    @State private var pianoAperto = false
    @State private var vecchieAperte = false


    @State private var campo = ""

    @State private var raddrizzando = false
    @State private var sceltaStrada = ""
    @State private var sceltaTipo = ""
    @State private var sceltaProgetto = ""
    @State private var sceltaArea = ""
    @State private var sceltaChi = ""

    @State private var rivisti: Set<String> = []
    @State private var altreAperte = false

    @State private var domandaAperta: String?

    @State private var paroleTutte = false

    var body: some View {
        Group {
            if let a = lavorazione.adessoFila {
                colonna(a, lavorazione, ispirazione)
            } else {
                corpoDiPrima
            }
        }
        .onChange(of: spunto.id) { _, _ in

            store.fermaEMandaRegistrazione("idea change")
            correggendo = false
            correggendoInFondo = false
            correzione = ""
            rispondendo = nil
            risposta = ""
            dettaglio = ""
            inCorso = nil
            errore = nil
            testoScheda = nil
            testoRitorno = nil
            risposteAperte = nil
            pianoAperto = false
            vecchieAperte = false
            campo = ""
            raddrizzando = false
            rivisti = []
            altreAperte = false
            domandaAperta = nil
            paroleTutte = false
        }
        .onDisappear {

            store.fermaEMandaRegistrazione("idea closed")
        }
    }


    @ViewBuilder
    private var corpoDiPrima: some View {
        let L = lavorazione
        let i = ispirazione
        VStack(alignment: .leading, spacing: Spazio.griglia) {


            if let passi = L.percorso, !passi.isEmpty {
                percorso(passi, L, i)
            } else {
                rigaStato(L, i)
            }
            if L.lavoro.ritorno != nil { ritorno(L, i) }
            if let e = errore ?? store.erroreGesto {
                fasciaErrore(e, i)
            }
            ParoleDiOwner(spunto: spunto, ispirazione: i)
            perche(L, i)
            doveVa(L, i)
            sessione(L, i)
            manca(L, i)

            passoDopo(L, i)
            if L.piano.c_e { piano(L.piano, i) }
            if L.scheda != nil || L.azioni.avvia { scheda(L, i) }
            if L.lavoro.avviato { lavoro(L, i) }
        }
    }



    @ViewBuilder
    private func percorso(_ passi: [PassoPercorso], _ L: Lavorazione, _ i: Inspiration) -> some View {
        let parole = L.percorso_parole ?? [:]
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(passi.enumerated()), id: \.element.id) { k, p in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 5) {
                            Self.segnoPasso(p.stato)
                            Text(p.nome)
                                .font(p.stato == "adesso" ? Testo.secondario.weight(.semibold) : Testo.secondario)
                                .foregroundStyle(p.stato == "adesso" ? Color.primary : Color.secondary)
                        }
                        if let q = p.quando, !q.isEmpty {
                            Text(q).font(Testo.minimo).foregroundStyle(.secondary).padding(.leading, 19)
                        }
                    }
                    .fixedSize()
                    .help((p.aiuto?.isEmpty == false ? p.aiuto! : parole[p.stato] ?? p.stato))
                    .accessibilityLabel("\(p.nome), \(parole[p.stato] ?? p.stato)")
                    if k < passi.count - 1 {
                        Rectangle().fill(Superficie.separatore).frame(height: 1).frame(maxWidth: .infinity)
                            .padding(.horizontal, 8).padding(.top, 8)
                    }
                }
            }
            .accessibilityLabel(parole["titolo"] ?? "The path")
            rigaStato(L, i)
            if let dopo = L.dopo_frase, !dopo.isEmpty {
                Text(dopo).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
    }


    @ViewBuilder
    private static func segnoPasso(_ stato: String) -> some View {
        switch stato {
        case "fatto": Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.secondary)
        case "adesso": Image(systemName: "circle.fill").foregroundStyle(Color.accentColor)
        case "avviso": Image(systemName: Salute.attenzione.simbolo).foregroundStyle(Salute.attenzione.colore)
        default: Image(systemName: "circle").foregroundStyle(Color.secondary)
        }
    }



    @ViewBuilder
    private func rigaStato(_ L: Lavorazione, _ i: Inspiration) -> some View {

        let frase = (L.stato_riquadro?.isEmpty == false) ? L.stato_riquadro! : L.tocca_frase
        let aTe = L.tocca == "te"

        if !frase.isEmpty || L.azioni.avvia || L.azioni.capisci == true {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                if !frase.isEmpty {


                    let occhio = L.fase == "da_capire" && !spunto.visto
                    let capitoVisto = L.fase == "da_capire" && spunto.visto
                    Label(frase, systemImage: aTe ? "hand.raised.fill" : (occhio ? "eye.slash" : (capitoVisto ? "gearshape.2" : (L.rilettura?.aperta == true ? "doc.text.magnifyingglass" : (L.tocca.isEmpty ? "checkmark.circle" : "gearshape.2")))))
                        .font(Testo.secondario.weight(.semibold))
                        .foregroundStyle(aTe ? Color.accentColor : Color.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                if L.azioni.capisci == true {






                    let aspettaLui = aTe || spunto.segno?.tipo == "tocca_te"
                    pulsante("capisci", aspettaLui ? i.t("capisci") : i.t("capisci_minore", o: i.t("capisci")),
                             prominente: aspettaLui, minore: !aspettaLui, aiuto: i.t("aiuto_capisci")) {
                        Task { await fai(["capisci", spunto.id], "capisci") }
                    }
                } else if L.azioni.vai_comprensione == true {
                    pulsante("vai", i.t("vai_comprensione"), aiuto: i.t("aiuto_vai")) {
                        Task { await fai(["vai", spunto.id], "vai") }
                    }
                } else if L.azioni.avvia {
                    pulsante("avvia", i.t("avvia"), prominente: true, aiuto: i.t("aiuto_avvia")) {
                        conTask = false
                        chiediAvvio = true
                    }
                } else if L.tocca == "sessione", L.azioni.vai_sessione {
                    pulsante("vai", i.t("vai_sessione"), aiuto: i.t("aiuto_vai")) { Task { await fai(["vai", spunto.id], "vai") } }
                } else if L.tocca == "agente", L.azioni.vai_lavoro {
                    pulsante("vai", i.t("vai_lavoro"), aiuto: i.t("aiuto_vai")) { Task { await fai(["vai", spunto.id, "--lavoro"], "vai") } }
                } else if L.azioni.ci_lavoriamo, L.percorso != nil || !L.azioni.conferma, !L.sessione.aperta {
                    pulsante("ci-lavoriamo", i.t("ci_lavoriamo"), prominente: aTe && !L.azioni.conferma, aiuto: i.t("aiuto_ci_lavoriamo")) {
                        Task { await fai(["ci-lavoriamo", spunto.id], "ci-lavoriamo") }
                    }
                }
            }
        }
    }


    @ViewBuilder
    private func pulsante(_ chiave: String, _ titolo: String, prominente: Bool = false, minore: Bool = false, aiuto: String,
                          azione: @escaping () -> Void) -> some View {
        let i = ispirazione
        HStack(spacing: 6) {
            if prominente {
                Button(titolo, action: azione).buttonStyle(.borderedProminent).help(aiuto)
            } else if minore {

                Button(titolo, action: azione).buttonStyle(.link).help(aiuto).fixedSize()
            } else {
                Button(titolo, action: azione).help(aiuto)
            }
            if inCorso == chiave {
                ProgressView().controlSize(.small)
                Text(i.t("un_attimo")).font(Testo.minimo).foregroundStyle(.secondary)
            }
        }
        .disabled(inCorso == chiave)
    }


    @ViewBuilder
    private func fasciaErrore(_ e: String, _ i: Inspiration) -> some View {
        let (titolo, resto) = Self.spezza(e)

        let avviso = EsitoAzione.eAvviso(e)
        HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
            Image(systemName: avviso ? "info.circle" : Salute.attenzione.simbolo)
                .foregroundStyle(avviso ? Color.secondary : Salute.attenzione.colore)
            VStack(alignment: .leading, spacing: 2) {
                Text(titolo).font(Testo.nome).fixedSize(horizontal: false, vertical: true)
                if !resto.isEmpty {
                    Text(resto).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Spazio.fratelli)
            Button(i.t("chiudi")) {
                errore = nil
                store.erroreGesto = nil
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(avviso ? AnyShapeStyle(Superficie.riquadro) : AnyShapeStyle(Salute.attenzione.colore.opacity(0.12)),
                    in: RoundedRectangle(cornerRadius: Raggio.riquadro))
    }

    static func spezza(_ frase: String) -> (String, String) {
        let t = frase.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let r = t.range(of: ". ") else { return (t.hasSuffix(".") ? String(t.dropLast()) : t, "") }
        return (String(t[..<r.lowerBound]), String(t[r.upperBound...]))
    }



    @ViewBuilder
    private func perche(_ L: Lavorazione, _ i: Inspiration) -> some View {
        let p = L.perche
        let correggi = L.azioni.conferma || (L.azioni.correggi ?? false)
        if p.c_e || p.confermato || p.eCorretto {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text(i.t("ho_capito")).font(Testo.titoloGruppo)
                    if !p.esito_parole.isEmpty {
                        Text(p.esito_parole)
                            .font(Testo.minimo.weight(.semibold))
                            .padding(.horizontal, 8).padding(.vertical, 2)
                            .background(Superficie.riquadro, in: Capsule())
                            .help(i.t("aiuto_esito"))
                    }
                    Spacer(minLength: 0)

                    let verde = p.confermato && !p.eCorretto
                    if let sf = p.stato_frase, !sf.isEmpty {
                        Label(sf, systemImage: verde ? "checkmark.circle.fill" : "pencil")
                            .font(Testo.minimo).foregroundStyle(verde ? Salute.ok.colore : Color.secondary)
                    } else if p.confermato {
                        Label(i.t("confermato", ["quando": p.confermato_quando]), systemImage: verde ? "checkmark.circle.fill" : "pencil")
                            .font(Testo.minimo).foregroundStyle(verde ? Salute.ok.colore : Color.secondary)
                    }
                }
                if let proposto = p.esito_proposto_parole, !proposto.isEmpty {
                    Text(i.t("avevo_detto", ["esito": proposto])).font(Testo.minimo).foregroundStyle(.secondary)
                }
                if p.eCorretto {

                    VStack(alignment: .leading, spacing: 4) {
                        Text(i.t("corretto_da_te")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                        if !p.correzione.isEmpty {
                            Text("«\(p.correzione)»").italic().fixedSize(horizontal: false, vertical: true)
                        }
                        if let f = p.correzione_frase, !f.isEmpty {
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Label(f, systemImage: "waveform").font(Testo.secondario)
                                    .foregroundStyle(p.inArrivo && (p.correzione_stato ?? "") != "da_verificare" && !["non_riuscita", "senza_parlato"].contains(p.correzione_stato ?? "")
                                                     ? Color.accentColor : Salute.attenzione.colore)
                                    .fixedSize(horizontal: false, vertical: true)
                                if let a = p.fileCorrezione { LettoreAudio(file: a, ispirazione: i) }
                            }
                        } else if p.correzione_in_trascrizione, p.correzione.isEmpty {
                            HStack(spacing: 10) {
                                Label(i.t("in_trascrizione"), systemImage: "waveform").font(Testo.secondario).foregroundStyle(Color.accentColor)
                                if let a = p.fileCorrezione { LettoreAudio(file: a, ispirazione: i) }
                            }
                        } else if let a = p.fileCorrezione {
                            HStack(spacing: 10) {
                                if let d = p.correzione_durata, !d.isEmpty {
                                    Text(i.t("audio_trascritta", ["durata": d])).font(Testo.minimo).foregroundStyle(.secondary)
                                }
                                LettoreAudio(file: a, ispirazione: i)
                            }
                        }
                    }
                    if !p.testo.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(i.t("prima_avevo_capito")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                            Text(p.testo).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                } else if !p.testo.isEmpty {
                    Text(p.testo).fixedSize(horizontal: false, vertical: true)
                }
                if !p.dove_arrivare.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(i.t("dove_arrivare")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                        Text(p.dove_arrivare).fixedSize(horizontal: false, vertical: true)
                    }
                }
                if !p.confermato, !p.inArrivo {
                    let poggia = p.su_cosa_poggia_frase ?? Self.poggiaDiPrima(p)
                    if !poggia.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(i.t("su_cosa_poggia")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                            Text(poggia).font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }

                    if p.riletto == true, let prima = p.prima_dicevo, !prima.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(i.t("prima_dicevo", o: "I used to say")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                            Text(prima).font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                if correggi && !correggendo {
                    HStack(spacing: 8) {
                        if L.azioni.conferma {
                            pulsante("conferma", i.t("giusto"), prominente: true, aiuto: i.t("aiuto_giusto")) {
                                Task { await fai(["conferma", spunto.id], "conferma") }
                            }
                        }
                        Button(i.t("correggi")) {
                            esito = p.esito
                            correggendo = true
                        }
                        .help(i.t("aiuto_correggi"))

                        if L.percorso == nil, L.azioni.conferma && L.azioni.ci_lavoriamo {
                            pulsante("ci-lavoriamo", i.t("ci_lavoriamo"), aiuto: i.t("aiuto_ci_lavoriamo")) {
                                Task { await fai(["ci-lavoriamo", spunto.id], "ci-lavoriamo") }
                            }
                        }
                    }
                }
                if correggendo {
                    VStack(alignment: .leading, spacing: 8) {
                        Picker(i.t("esito"), selection: $esito) {
                            ForEach(i.esiti ?? []) { e in Text(e.parole).tag(e.id) }
                        }
                        .pickerStyle(.menu)
                        .fixedSize()
                        CampoRisposta(testo: $correzione, segnaposto: i.t("correzione_segnaposto"), voce: spunto.id, chiave: "perche",
                                      cosa: i.t("registrando_perche"), esito: esito, cartella: L.cartella,
                                      cartellaRegistro: L.cartellaRegistro, ispirazione: i, inCorso: inCorso == "perche",
                                      invia: { testo in
                                          var a = ["conferma", spunto.id, "--correzione", testo]
                                          if !esito.isEmpty { a += ["--esito", esito] }
                                          await fai(a, "perche")
                                          correggendo = false
                                          correzione = ""
                                      },
                                      dopoAudio: { correggendo = false },
                                      chiudi: { correggendo = false })
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        }
    }





    @ViewBuilder
    private func doveVa(_ L: Lavorazione, _ i: Inspiration) -> some View {
        if let sm = L.smistamento, sm.c_e {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text(sm.t("titolo", "Where it goes")).font(Testo.titoloGruppo)
                    Spacer(minLength: 0)
                    if sm.confermato {
                        Label(sm.riga_esito ?? "", systemImage: "checkmark.circle.fill")
                            .font(Testo.minimo).foregroundStyle(Salute.ok.colore)
                    }
                }
                if !sm.confermato, let e = sm.riga_esito, !e.isEmpty {
                    Text(e).font(Testo.secondario.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                }
                if let d = sm.riga_dove, !d.isEmpty {
                    Label(d, systemImage: sm.confermato ? "arrow.up.right.square" : "tray.and.arrow.down")
                        .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                }
                if let n = sm.riga_nota, !n.isEmpty {
                    Label(n, systemImage: "info.circle")
                        .font(Testo.minimo).foregroundStyle(Salute.attenzione.colore).fixedSize(horizontal: false, vertical: true)
                }
                if let m = sm.riga_motivo, !m.isEmpty {
                    Text(m).font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    if sm.azioni.si {
                        pulsante("smista", sm.t("si", "Yes"), prominente: true, aiuto: sm.t("aiuto_si", "")) {
                            Task { await fai(["smista", spunto.id, "--si"], "smista") }
                        }
                    }
                    if sm.azioni.cambia, let esiti = sm.esiti, !esiti.isEmpty {
                        Menu(sm.t("cambia", "Change")) {
                            ForEach(esiti) { e in
                                Button(e.parole) { Task { await fai(["smista", spunto.id, "--esito", e.id], "smista") } }
                            }
                        }
                        .menuStyle(.borderlessButton)
                        .fixedSize()
                        .help(sm.t("aiuto_cambia", ""))
                        .disabled(inCorso == "smista")
                    }
                    if sm.confermato, let t = sm.task, !t.isEmpty, let u = URL(string: t) {
                        Button(sm.t("apri_task", "Open the task")) { NSWorkspace.shared.open(u) }
                    }
                    if sm.azioni.rimetti {
                        pulsante("rimetti", sm.t("rimetti", "Put back"), aiuto: sm.t("aiuto_rimetti", "")) {
                            Task { await fai(["smista", spunto.id, "--rimetti"], "rimetti") }
                        }
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        }
    }


    static func poggiaDiPrima(_ p: PercheSpunto) -> String {
        let pezzi = [p.sicurezza, p.su_cosa_poggia].filter { !$0.isEmpty }
            .map { $0.trimmingCharacters(in: CharacterSet(charactersIn: ". ")) }
        return pezzi.isEmpty ? "" : pezzi.joined(separator: ". ") + "."
    }



    @ViewBuilder
    private func sessione(_ L: Lavorazione, _ i: Inspiration) -> some View {
        if L.sessione.aperta, L.tocca != "sessione" {
            if L.lavoro.avviato {

                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Label(i.t("sessione_ha_scritto"), systemImage: "terminal")
                        .font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    if L.azioni.vai_sessione {
                        Button(i.t("vai_sessione")) { Task { await fai(["vai", spunto.id], "vai-sessione") } }
                            .buttonStyle(.borderless).font(Testo.minimo).help(i.t("aiuto_vai"))
                    }
                }
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Label(i.t("sessione_aperta", ["quando": L.sessione.quando]), systemImage: "terminal")
                        .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    if L.azioni.vai_sessione {
                        pulsante("vai-sessione", i.t("vai_sessione"), aiuto: i.t("aiuto_vai")) {
                            Task { await fai(["vai", spunto.id], "vai-sessione") }
                        }
                    }
                }
            }
        } else if !L.sessione.aperta, let q = L.sessione.chiusa_quando, !q.isEmpty, ["perche", "lavorazione"].contains(L.fase) {
            Label(i.t("sessione_chiusa", ["quando": q]), systemImage: "terminal")
                .font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }



    @ViewBuilder
    private func manca(_ L: Lavorazione, _ i: Inspiration) -> some View {

        let visibili = L.domande.filter { !$0.dalSistema }

        let vecchie = L.lavoro.avviato ? visibili.filter { !$0.dallaSessioneDiLavoro } : []
        let attuali = L.lavoro.avviato ? visibili.filter { $0.dallaSessioneDiLavoro } : visibili
        let aperte = attuali.filter { !$0.chiusa }
        let chiuse = attuali.filter { $0.chiusa }
        let oggi = chiuse.contains { ($0.quando_risposta ?? "").hasPrefix("oggi") }
        let mostraChiuse = risposteAperte ?? oggi

        let gruppi = Self.gruppiInsieme(attuali)
        let gruppoVisibile = gruppi.values.contains { g in g.first.map { !$0.chiusa || mostraChiuse } ?? false }

        let daRispondere = aperte.filter { !$0.inViaggio && Self.chiaveInsieme($0) == nil }
        if L.azioni.rispondi && (!visibili.isEmpty || L.perche.c_e) {
            VStack(alignment: .leading, spacing: 10) {
                Text(i.t("cosa_mi_manca")).font(Testo.titoloGruppo)
                if aperte.isEmpty {

                    Text(chiuse.isEmpty ? i.t("niente_mi_manca") : i.t("risposto_a_tutto", o: i.t("niente_mi_manca")))
                        .foregroundStyle(.secondary)
                } else {
                    Text(i.t("cosa_mi_manca_frase")).font(Testo.secondario).foregroundStyle(.secondary)
                }

                ForEach(attuali) { d in
                    if let g = Self.chiaveInsieme(d), let membri = gruppi[g] {
                        if membri.first?.id == d.id, !d.chiusa || mostraChiuse {
                            rispostaInsieme(membri, L, i)
                        }
                    } else if !d.chiusa {
                        domanda(d, L, i)
                    } else if mostraChiuse {
                        rispostaData(d, L, i)
                    }
                }
                if daRispondere.count >= 2 || (rispondendo == "tutte" && !gruppoVisibile) {
                    if rispondendo == "tutte" && !gruppoVisibile {
                        VStack(alignment: .leading, spacing: 6) {
                            Label(i.t("rispondi_a_tutte", o: "Answer all together"), systemImage: "mic.fill")
                                .font(Testo.secondario.weight(.semibold))
                            campoTutte(L, i)
                        }
                        .padding(10)
                        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
                    } else if rispondendo != "tutte" {
                        Button {
                            rispondendo = "tutte"
                            risposta = ""
                        } label: {
                            Label(i.t("rispondi_a_tutte", o: "Answer all together"), systemImage: "mic.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(Registratore.condiviso.occupato || inCorso != nil)
                        .help(i.t("aiuto_rispondi_a_tutte", o: "A single answer, written or spoken, for all open questions"))
                    }
                }
                if !chiuse.isEmpty {
                    Button {
                        risposteAperte = !mostraChiuse
                    } label: {
                        Label("\(i.t("risposte_date")) \(chiuse.count)", systemImage: mostraChiuse ? "chevron.down" : "chevron.right")
                            .font(Testo.secondario.weight(.semibold))
                    }
                    .buttonStyle(.plain)
                }
                if !vecchie.isEmpty {
                    DisclosureGroup(isExpanded: $vecchieAperte) {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(vecchie) { d in
                                if d.chiusa {
                                    rispostaData(d, L, i)
                                } else {
                                    Text(d.testo).font(Testo.secondario).foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        .padding(.top, 6)
                    } label: {
                        Text(i.t("non_servono_piu")).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    }
                }

                if rispondendo == "dettaglio" {
                    CampoRisposta(testo: $dettaglio, segnaposto: i.t("dettaglio_segnaposto"), voce: spunto.id, chiave: "dettaglio",
                                  cosa: i.t("registrando_dettaglio"), esito: "", cartella: L.cartella,
                                  cartellaRegistro: L.cartellaRegistro, ispirazione: i, inCorso: inCorso == "dettaglio",
                                  invia: { testo in
                                      await fai(["rispondi", spunto.id, "--testo", testo], "dettaglio")
                                      dettaglio = ""
                                      rispondendo = nil
                                  },
                                  dopoAudio: { rispondendo = nil },
                                  chiudi: { rispondendo = nil })
                } else {
                    Button {
                        rispondendo = "dettaglio"
                        dettaglio = ""
                    } label: {
                        Label(i.t("dettaglio"), systemImage: "plus.bubble")
                    }
                    .buttonStyle(.borderless)
                    .font(Testo.secondario)
                }
            }
        }
    }


    static func chiaveInsieme(_ d: DomandaSpunto) -> String? {
        guard d.insiemeAltre else { return nil }
        return d.fileAudio ?? "testo \(d.quando_risposta ?? "")"
    }

    static func gruppiInsieme(_ ds: [DomandaSpunto]) -> [String: [DomandaSpunto]] {
        var out: [String: [DomandaSpunto]] = [:]
        for d in ds {
            if let k = chiaveInsieme(d) { out[k, default: []].append(d) }
        }
        return out
    }

    @ViewBuilder
    private func domanda(_ d: DomandaSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "questionmark.bubble").foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text(d.testo).fixedSize(horizontal: false, vertical: true)
                    if !d.serve_per.isEmpty {
                        Text(d.serve_per).font(Testo.minimo).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)


                if !d.inViaggio && rispondendo != d.id && d.statoAudio != "da_verificare" {
                    Button(i.t("rispondi")) {
                        rispondendo = d.id
                        risposta = ""
                    }
                }
            }

            if let sf = d.stato_frase, !sf.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Label(sf, systemImage: "waveform").font(Testo.secondario)
                        .foregroundStyle(d.inViaggio ? Color.accentColor : Salute.attenzione.colore)
                        .fixedSize(horizontal: false, vertical: true)
                    if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                }
            } else if d.in_trascrizione {
                HStack(spacing: 10) {
                    Label(i.t("in_trascrizione"), systemImage: "waveform").font(Testo.secondario).foregroundStyle(Color.accentColor)
                    if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                }
            }
            if rispondendo != d.id, !d.inViaggio { pulsantiVerifica(d, d.id, i) }
            if rispondendo == d.id { campoDomanda(d, L, i) }
        }
        .padding(10)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }



    @ViewBuilder
    private func pulsantiVerifica(_ d: DomandaSpunto, _ chiave: String, _ i: Inspiration) -> some View {
        let st = d.statoAudio
        if st == "da_verificare" || st == "non_riuscita" || st == "senza_parlato" {
            HStack(spacing: 8) {
                if st == "da_verificare" {
                    pulsante("giusta-\(chiave)", i.t("e_giusto", o: "It's right"), prominente: true,
                             aiuto: i.t("aiuto_e_giusto", o: "The words I heard become your answer")) {
                        Task { await fai(["risposta-giusta", spunto.id, "--domanda", chiave], "giusta-\(chiave)") }
                    }
                    Button(i.t("correggi")) {
                        rispondendo = chiave
                        risposta = d.paroleSentite
                    }
                    .help(i.t("aiuto_cambia", o: "Rewrite the answer, or record it again"))
                }
                pulsanteTogli(chiave, i)
            }
        }
    }


    @ViewBuilder
    private func pulsanteTogli(_ chiave: String, _ i: Inspiration, piccolo: Bool = false) -> some View {
        let k = "togli-\(chiave)"
        let aiuto = i.t("aiuto_togli", o: "I remove the answer and the question reopens. The audio stays on the Mac")
        if piccolo {
            HStack(spacing: 6) {
                Button(i.t("togli", o: "Remove")) { Task { await fai(["togli-risposta", spunto.id, "--domanda", chiave], k) } }
                    .buttonStyle(.borderless).font(Testo.minimo).help(aiuto)
                if inCorso == k { ProgressView().controlSize(.small) }
            }
            .disabled(inCorso == k)
        } else {
            pulsante(k, i.t("togli", o: "Remove"), aiuto: aiuto) {
                Task { await fai(["togli-risposta", spunto.id, "--domanda", chiave], k) }
            }
        }
    }


    private func campoDomanda(_ d: DomandaSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        CampoRisposta(testo: $risposta, segnaposto: i.t("risposta_segnaposto"), voce: spunto.id, chiave: d.id,
                      cosa: Self.taglia(d.testo), esito: "", cartella: L.cartella, cartellaRegistro: L.cartellaRegistro,
                      ispirazione: i, inCorso: inCorso == d.id,
                      invia: { testo in
                          await fai(["rispondi", spunto.id, "--domanda", d.id, "--testo", testo], d.id)
                          rispondendo = nil
                          risposta = ""
                      },
                      dopoAudio: { rispondendo = nil },
                      chiudi: { rispondendo = nil })
    }



    private func campoTutte(_ L: Lavorazione, _ i: Inspiration) -> some View {
        CampoRisposta(testo: $risposta, segnaposto: i.t("risposta_a_tutte_segnaposto", o: "Answer them all, one after another"),
                      voce: spunto.id, chiave: "tutte", cosa: i.t("registrando_tutte", o: "all the questions"), esito: "",
                      cartella: L.cartella, cartellaRegistro: L.cartellaRegistro, ispirazione: i, inCorso: inCorso == "tutte",
                      invia: { testo in
                          await fai(["rispondi", spunto.id, "--domanda", "tutte", "--testo", testo], "tutte")
                          rispondendo = nil
                          risposta = ""
                      },
                      dopoAudio: { rispondendo = nil },
                      chiudi: { rispondendo = nil })
    }

    private func metaRisposta(_ d: DomandaSpunto, _ i: Inspiration) -> String {
        [
            (d.quando_risposta?.isEmpty == false) ? i.t("risposta_data", ["quando": d.quando_risposta ?? ""]) : "",
            (d.durata?.isEmpty == false && d.fileAudio != nil) ? i.t("audio_trascritta", ["durata": d.durata ?? ""]) : "",
        ].filter { !$0.isEmpty }.joined(separator: " · ")
    }



    @ViewBuilder
    private func rispostaData(_ d: DomandaSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "checkmark.bubble").foregroundStyle(.secondary)
                Text(d.testo).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                if !d.risposta.isEmpty {
                    Text("«\(d.risposta)»").fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
            }
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                let meta = metaRisposta(d, i)
                if !meta.isEmpty {
                    Text(meta).font(Testo.minimo).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                if L.azioni.rispondi, rispondendo != d.id {
                    Button(i.t("cambia", o: "Change")) {
                        rispondendo = d.id
                        risposta = d.risposta
                    }
                    .buttonStyle(.borderless).font(Testo.minimo)
                    .help(i.t("aiuto_cambia", o: "Rewrite the answer, or record it again"))
                    pulsanteTogli(d.id, i, piccolo: true)
                }
            }
            if rispondendo == d.id { campoDomanda(d, L, i) }
        }
        .padding(10)
        .background(Superficie.riquadro.opacity(0.6), in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }



    @ViewBuilder
    private func rispostaInsieme(_ ds: [DomandaSpunto], _ L: Lavorazione, _ i: Inspiration) -> some View {
        if let d = ds.first {
            VStack(alignment: .leading, spacing: 6) {
                Label(i.t("risposta_a_tutte", ["n": "\(ds.count)"], o: "Your answer to all \(ds.count) together"),
                      systemImage: d.chiusa ? "checkmark.bubble" : "questionmark.bubble")
                    .font(Testo.secondario.weight(.semibold))
                    .foregroundStyle(d.chiusa ? Color.secondary : Color.accentColor)
                ForEach(ds) { x in
                    Text(x.testo).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                if d.chiusa {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        if !d.risposta.isEmpty {
                            Text("«\(d.risposta)»").fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                        if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        let meta = metaRisposta(d, i)
                        if !meta.isEmpty {
                            Text(meta).font(Testo.minimo).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 0)
                        if L.azioni.rispondi, rispondendo != "tutte" {
                            Button(i.t("cambia", o: "Change")) {
                                rispondendo = "tutte"
                                risposta = d.risposta
                            }
                            .buttonStyle(.borderless).font(Testo.minimo)
                            .help(i.t("aiuto_cambia", o: "Rewrite the answer, or record it again"))
                            pulsanteTogli("tutte", i, piccolo: true)
                        }
                    }
                } else {
                    if let sf = d.stato_frase, !sf.isEmpty {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Label(sf, systemImage: "waveform").font(Testo.secondario)
                                .foregroundStyle(d.inViaggio ? Color.accentColor : Salute.attenzione.colore)
                                .fixedSize(horizontal: false, vertical: true)
                            if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                        }
                    } else if d.in_trascrizione {
                        HStack(spacing: 10) {
                            Label(i.t("in_trascrizione"), systemImage: "waveform").font(Testo.secondario).foregroundStyle(Color.accentColor)
                            if let a = d.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                        }
                    }
                    if rispondendo != "tutte", !d.inViaggio { pulsantiVerifica(d, "tutte", i) }
                }
                if rispondendo == "tutte" { campoTutte(L, i) }
            }
            .padding(10)
            .background(Superficie.riquadro.opacity(d.chiusa ? 0.6 : 1), in: RoundedRectangle(cornerRadius: Raggio.piccolo))
        }
    }

    static func taglia(_ testo: String, _ max: Int = 48) -> String {
        let t = testo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count > max else { return t }
        return String(t.prefix(max - 1)).trimmingCharacters(in: .whitespaces) + "…"
    }





    @ViewBuilder
    private func passoDopo(_ L: Lavorazione, _ i: Inspiration) -> some View {
        if let pd = L.passo_dopo, pd.c_e, !pd.frase.isEmpty {
            let rileggo = pd.stato == "rileggo"
            let fermo = pd.stato == "fermo"
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(pd.titolo).font(Testo.titoloGruppo)
                    if let q = pd.quando, !q.isEmpty {
                        Text(q).font(Testo.minimo).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    if rileggo { ProgressView().controlSize(.small) }
                }
                Label(pd.frase, systemImage: rileggo ? "doc.text.magnifyingglass" : (fermo ? Salute.attenzione.simbolo : "hand.raised.fill"))
                    .font(Testo.secondario.weight(.semibold))
                    .foregroundStyle(rileggo ? Color.secondary : (fermo ? Salute.attenzione.colore : Color.accentColor))
                    .fixedSize(horizontal: false, vertical: true)
                if pd.stato == "riletto" {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(i.t("ho_capito")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                            if let e = pd.esito_parole, !e.isEmpty {
                                Text(e).font(Testo.minimo.weight(.semibold))
                                    .padding(.horizontal, 8).padding(.vertical, 2)
                                    .background(Superficie.riquadro, in: Capsule())
                            }
                        }
                        if let t = pd.perche_breve, !t.isEmpty {
                            Text(t).fixedSize(horizontal: false, vertical: true)
                        }
                        if let d = pd.dove_arrivare, !d.isEmpty {
                            Text(i.t("dove_arrivare")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 2)
                            Text(d).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                if let az = pd.azioni, !correggendoInFondo, az.conferma || az.correggi || az.ci_lavoriamo || az.vai_sessione {
                    HStack(spacing: 8) {
                        if az.conferma {
                            pulsante("conferma", i.t("giusto"), prominente: true, aiuto: i.t("aiuto_giusto")) {
                                Task { await fai(["conferma", spunto.id], "conferma") }
                            }
                        }
                        if az.correggi {
                            Button(i.t("correggi")) {
                                esito = L.perche.esito
                                correggendoInFondo = true
                            }
                            .help(i.t("aiuto_correggi"))
                        }
                        if az.ci_lavoriamo {
                            pulsante("ci-lavoriamo", i.t("ci_lavoriamo"), prominente: !az.conferma, aiuto: i.t("aiuto_ci_lavoriamo")) {
                                Task { await fai(["ci-lavoriamo", spunto.id], "ci-lavoriamo") }
                            }
                        }
                        if az.vai_sessione {
                            pulsante("vai-sessione", i.t("vai_sessione"), aiuto: i.t("aiuto_vai")) {
                                Task { await fai(["vai", spunto.id], "vai-sessione") }
                            }
                        }
                    }
                }
                if correggendoInFondo {
                    VStack(alignment: .leading, spacing: 8) {
                        Picker(i.t("esito"), selection: $esito) {
                            ForEach(i.esiti ?? []) { e in Text(e.parole).tag(e.id) }
                        }
                        .pickerStyle(.menu)
                        .fixedSize()
                        CampoRisposta(testo: $correzione, segnaposto: i.t("correzione_segnaposto"), voce: spunto.id, chiave: "perche",
                                      cosa: i.t("registrando_perche"), esito: esito, cartella: L.cartella,
                                      cartellaRegistro: L.cartellaRegistro, ispirazione: i, inCorso: inCorso == "perche",
                                      invia: { testo in
                                          var a = ["conferma", spunto.id, "--correzione", testo]
                                          if !esito.isEmpty { a += ["--esito", esito] }
                                          await fai(a, "perche")
                                          correggendoInFondo = false
                                          correzione = ""
                                      },
                                      dopoAudio: { correggendoInFondo = false },
                                      chiudi: { correggendoInFondo = false })
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(rileggo ? 0.05 : 0.08), in: RoundedRectangle(cornerRadius: Raggio.riquadro))
            .accessibilityElement(children: .contain)
            .accessibilityLabel(pd.titolo)
        }
    }



    @ViewBuilder
    private func piano(_ p: PianoSpunto, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {

            if !p.punto_di_arrivo.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(i.t("punto_di_arrivo")).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                    Text(p.punto_di_arrivo).fixedSize(horizontal: false, vertical: true)
                }
            }
            DisclosureGroup(isExpanded: $pianoAperto) {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(p.passi.enumerated()), id: \.offset) { n, passo in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text("\(n + 1).").monospacedDigit().foregroundStyle(.secondary)
                            Text(passo).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    elenco(i.t("dati_che_servono"), p.dati)
                    elenco(i.t("cosa_non_fare"), p.cosa_non_fare)
                    if !p.permessi.isEmpty {
                        Text(p.permessi).font(Testo.minimo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.top, 6)
            } label: {
                Text("\(i.t("il_piano")) \(p.passi.count)").font(Testo.titoloGruppo)
            }
        }
    }

    @ViewBuilder
    private func elenco(_ titolo: String, _ righe: [String]) -> some View {
        if !righe.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text(titolo).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(righe, id: \.self) { r in
                    Text("· \(r)").fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    @ViewBuilder
    private func scheda(_ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(i.t("la_scheda")).font(Testo.titoloGruppo)
            HStack(spacing: 8) {
                if let f = L.scheda {
                    Button(testoScheda == nil ? i.t("leggi_scheda") : i.t("nascondi")) {
                        testoScheda = testoScheda == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                    }
                }

                if L.percorso == nil, L.azioni.avvia {
                    pulsante("avvia", i.t("avvia"), prominente: true, aiuto: i.t("aiuto_avvia")) {
                        conTask = false
                        chiediAvvio = true
                    }
                }
            }
            if let t = testoScheda {
                Testolungo(testo: t)
            }
        }
        .sheet(isPresented: $chiediAvvio) { foglioAvvio(L, i) }
    }



    @ViewBuilder
    private func foglioAvvio(_ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(i.t("avvia_conferma_titolo")).font(.title3.weight(.semibold))
            Text(spunto.titolo).font(Testo.nome)
            Text(i.t("avvia_conferma_testo", ["permessi": L.piano.permessi]))
                .fixedSize(horizontal: false, vertical: true)

            if L.azioni.avvia_task?.v ?? true {
                Toggle(i.t("avvia_task"), isOn: $conTask).help(i.t("aiuto_avvia_task"))
            }
            HStack {
                Spacer()
                Button(i.t("chiudi")) { chiediAvvio = false }
                    .keyboardShortcut(.cancelAction)
                Button(i.t("avvia")) {
                    chiediAvvio = false
                    let conLaTask = conTask && (L.azioni.avvia_task?.v ?? true)
                    Task { await fai(["avvia", spunto.id] + (conLaTask ? ["--task"] : []), "avvia") }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(22)
        .frame(width: 460)
    }

    @ViewBuilder
    private func lavoro(_ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                if let fine = L.lavoro.finito_quando, !fine.isEmpty {
                    Label(i.t("lavoro_finito", ["quando": fine]), systemImage: "hammer")
                        .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                } else {
                    Label(i.t("lavoro_avviato", ["quando": L.lavoro.quando, "permessi": L.lavoro.permessi]), systemImage: "hammer")
                        .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                if L.azioni.vai_lavoro, L.tocca != "agente" {
                    pulsante("vai", i.t("vai_lavoro"), aiuto: i.t("aiuto_vai")) { Task { await fai(["vai", spunto.id, "--lavoro"], "vai") } }
                }
            }
            taskDelLavoro(L.lavoro, i)

            if L.lavoro.ritorno == nil, let f = L.lavoro.ritorno_parziale {
                Text(i.t("ritorno_parziale")).font(Testo.titoloGruppo)
                Button(testoRitorno == nil ? i.t("leggi_ritorno") : i.t("nascondi")) {
                    testoRitorno = testoRitorno == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                }
                if let t = testoRitorno { Testolungo(testo: t) }
            }
        }
    }


    @ViewBuilder
    private func ritorno(_ L: Lavorazione, _ i: Inspiration) -> some View {
        if let f = L.lavoro.ritorno {
            VStack(alignment: .leading, spacing: 8) {
                Text(i.t("il_ritorno")).font(Testo.titoloGruppo)
                HStack(spacing: 8) {
                    Button(testoRitorno == nil ? i.t("leggi_ritorno") : i.t("nascondi")) {
                        testoRitorno = testoRitorno == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                    }
                    if L.azioni.ritorno_letto, testoRitorno != nil {
                        pulsante("letto", i.t("ho_letto"), prominente: true, aiuto: "") {
                            Task { await fai(["ritorno-letto", spunto.id], "letto") }
                        }
                    }
                }
                if let t = testoRitorno { Testolungo(testo: t) }
            }
        }
    }




    private func fai(_ argomenti: [String], _ chiave: String) async {
        inCorso = chiave
        errore = nil
        defer { inCorso = nil }
        if let messaggio = await store.azioneInspiration(argomenti) {
            errore = messaggio
        }
    }
}








extension RiquadroLavorazione {

    func parola(_ chiave: String, _ valori: [String: String] = [:]) -> String? {
        guard var t = ispirazione.testi[chiave], !t.isEmpty else { return nil }
        for (k, v) in valori { t = t.replacingOccurrences(of: "{\(k)}", with: v) }
        return t
    }

    @ViewBuilder
    func colonna(_ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        let passi = L.passiFila

        let capireDaRivedere = L.fattoFila.contains { $0.passo == "capire" && $0.rivedi }
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            if !passi.isEmpty { striscia(passi) }


            if let c = L.cambioFila, c.da_decidere { pannelloCambio(c, a, i) }

            if raddrizzando, !Self.scopeInAdesso(L), let s = L.scopeFila { raddrizzaDaFatto(s, a, L, i) }
            if !capireDaRivedere { ParoleDiOwner(spunto: spunto, ispirazione: i) }
            if let u = L.uscitaFila {
                riquadroUscita(u, a, L, i)
            } else {
                riquadroAdesso(a, L, i)
            }
            fattoLista(L, i)
            dopoLista(L, i)
        }
        .sheet(isPresented: $chiediAvvio) { foglioAvvio(L, i) }
        .onAppear { pronteIstantanea(L) }


        .onChange(of: L.scopeFila?.versione) { _, _ in
            if raddrizzando { apriRaddrizza(lavorazione) }
        }
    }



    static func scopeInAdesso(_ L: Lavorazione) -> Bool {
        L.passoAcceso == "scope" && L.task_manca?.v != true && L.scopeFila?.aspetta_task != true
    }




    @ViewBuilder
    func esitoNelRiquadro(_ i: Inspiration) -> some View {
        if let e = errore ?? store.erroreGesto { fasciaErrore(e, i) }
    }



    func pronteIstantanea(_ L: Lavorazione) {
        guard store.modoIstantanea else { return }
        let env = ProcessInfo.processInfo.environment
        if env["SB_RADDRIZZA"] == "1" { apriRaddrizza(L) }
        if let r = env["SB_RIVEDI"] { rivisti = Set(r.split(separator: ",").map(String.init)) }
        if env["SB_ALTRE"] == "1" { altreAperte = true }
        if let t = env["SB_CAMPO"] { campo = t }
        if let d = env["SB_DOMANDA"] { domandaAperta = d }
        if env["SB_PAROLE_TUTTE"] == "1" { paroleTutte = true }

        if let e = env["SB_ESITO"] {
            if env["SB_ESITO_AVVISO"] == "1" { EsitoAzione.avvisi.insert(e) }
            errore = e
        }
    }

    func apriRaddrizza(_ L: Lavorazione) {
        let s = L.scopeFila
        sceltaStrada = s?.strada ?? ""
        sceltaTipo = s?.tipo ?? ""
        sceltaProgetto = s?.progetto ?? ""
        sceltaArea = s?.area ?? ""
        sceltaChi = s?.chi ?? ""
        raddrizzando = true
    }




    @ViewBuilder
    func striscia(_ passi: [PassoFila]) -> some View {
        ViewThatFits(in: .horizontal) {
            strisciaLunga(passi)
            strisciaCorta(passi)
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    func strisciaLunga(_ passi: [PassoFila]) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(passi.enumerated()), id: \.offset) { k, p in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 5) {
                        Self.segnoFila(p.stato)
                        Text(p.nome)
                            .font(p.stato == "adesso" ? Testo.secondario.weight(.semibold) : Testo.secondario)
                            .foregroundStyle(p.stato == "adesso" ? Color.primary : Color.secondary)
                            .strikethrough(p.stato == "saltato")
                    }
                    if !p.quando.isEmpty {
                        Text(p.quando).font(Testo.minimo).foregroundStyle(.secondary).padding(.leading, 19)
                    }
                }
                .fixedSize()
                .help(p.riassunto)
                .accessibilityLabel(p.riassunto.isEmpty ? p.nome : "\(p.nome), \(p.riassunto)")
                if k < passi.count - 1 {

                    Rectangle().fill(Superficie.separatore)
                        .frame(minWidth: 14, maxWidth: 140, minHeight: 1, maxHeight: 1)
                        .padding(.horizontal, 6).padding(.top, 8)
                }
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    func strisciaCorta(_ passi: [PassoFila]) -> some View {
        let k = passi.firstIndex { $0.stato == "adesso" } ?? passi.firstIndex { $0.stato == "rifare" }
        let acceso = k.map { passi[$0] }
        let nome = acceso?.nome ?? ""

        let etichetta = k.flatMap { j in parola("passo_corto", ["k": "\(j + 1)", "n": "\(passi.count)"]) }
            .map { nome.isEmpty ? $0 : "\($0) · \(nome)" } ?? nome

        HStack(spacing: 6) {
            Self.segnoFila(acceso?.stato ?? "")
            Menu {
                ForEach(Array(passi.enumerated()), id: \.offset) { _, p in
                    Button {} label: {
                        Label(p.quando.isEmpty ? p.nome : "\(p.nome) · \(p.quando)", systemImage: Self.simboloFila(p.stato))
                    }
                    .help(p.riassunto)
                }
            } label: {
                Text(etichetta).font(Testo.secondario.weight(.semibold))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .help(parola("aiuto_passo_corto") ?? (acceso?.riassunto ?? ""))
    }

    static func simboloFila(_ stato: String) -> String {
        switch stato {
        case "fatto": "checkmark.circle.fill"
        case "adesso": "circle.fill"
        case "rifare": "arrow.clockwise.circle"
        case "saltato": "minus.circle"
        default: "circle"
        }
    }



    @ViewBuilder
    static func segnoFila(_ stato: String) -> some View {
        Image(systemName: simboloFila(stato))
            .foregroundStyle(stato == "adesso" ? Color.accentColor
                : (stato == "saltato" ? Color(nsColor: .tertiaryLabelColor) : Color.secondary))
    }



    @ViewBuilder
    func riquadroAdesso(_ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        let aTe = a.chi == "te"
        let allo = a.passo.isEmpty ? L.passoAcceso : a.passo

        let scope = allo == "scope" && Self.scopeInAdesso(L) ? L.scopeFila.flatMap { $0.pieno ? $0 : nil } : nil
        VStack(alignment: .leading, spacing: 10) {

            let testata = [parola("adesso_titolo"), a.titolo.isEmpty ? nil : a.titolo].compactMap { $0 }
            if !testata.isEmpty {
                Text(testata.joined(separator: " · "))
                    .font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
            }
            if !a.frase.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    segnoAdesso(a)
                    Text(a.frase)
                        .font(Testo.corpo.weight(.medium))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if !(raddrizzando && scope == nil) { esitoNelRiquadro(i) }
            if !a.avanzamento.isEmpty {
                Text(a.avanzamento).font(Testo.minimo).foregroundStyle(.secondary)
            }


            if let pr = L.scopeFila?.proposta_in_attesa {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath").foregroundStyle(.secondary)
                    Text(pr.frase).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let s = scope {
                bloccoScope(s, L, i)
                if raddrizzando { bloccoRaddrizza(s, i) }
            } else if !a.domande.isEmpty || !a.altre_domande.isEmpty {

                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(a.domande.enumerated()), id: \.offset) { k, d in
                        domandaScope(k + 1, d, L, i)
                    }
                    altreDomande(a.altre_domande, a.altre_domande_frase, dopo: a.domande.count, L, i)
                }
            }
            letture(a, L, i)

            if (a.campo != nil && !(raddrizzando && scope == nil)) || (raddrizzando && scope != nil) {
                campoUnico(a.campo, a, L, i, chiave: chiaveCampo(a, scope != nil))
            }
            if !a.poi.isEmpty {
                Text(a.poi).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            rigaGesti(a, L, i)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(aTe ? AnyShapeStyle(Color.accentColor.opacity(0.08)) : AnyShapeStyle(Superficie.riquadro),
                    in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        .accessibilityElement(children: .contain)
    }



    @ViewBuilder
    func segnoAdesso(_ a: AdessoSpunto) -> some View {
        if a.salute == "attenzione" {
            Image(systemName: Salute.attenzione.simbolo).foregroundStyle(Salute.attenzione.colore)
        } else if a.chi == "te" {
            Image(systemName: "hand.raised.fill").foregroundStyle(Color.accentColor)
        } else if spunto.segno?.tipo == "agente_aperto" {


            EmptyView()
        } else if a.chi == "sistema" || a.chi == "sessione" {
            ProgressView().controlSize(.mini)
        }
    }




    func chiaveCampo(_ a: AdessoSpunto, _ allo: Bool) -> String {
        if allo { return raddrizzando ? "scope" : (chiaveDomandeScope(lavorazione) ?? "scope") }
        return chiaveDomande(a)
    }

    func chiaveDomande(_ a: AdessoSpunto) -> String {
        let aperte = a.domande.filter { d in !(lavorazione.domande.first { $0.id == d.id }?.chiusa ?? false) }
        if aperte.count == 1 { return aperte[0].id }
        return aperte.isEmpty ? "dettaglio" : "tutte"
    }


    func chiaveDomandeScope(_ L: Lavorazione) -> String? {
        let aperte = (L.scopeFila?.domande ?? []).filter { d in !(L.domande.first { $0.id == d.id }?.chiusa ?? false) }
        if aperte.isEmpty { return nil }
        return aperte.count == 1 ? aperte[0].id : "tutte"
    }



    @ViewBuilder
    func rigaGesti(_ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        let minori = a.secondari.filter { !Self.letturaGiaInVista($0.verbo, L) }
        let pienoRaddrizza = a.pulsante?.verbo == "raddrizza"
        if !minori.isEmpty || a.pulsante != nil {
            HStack(alignment: .firstTextBaseline, spacing: 14) {


                let raddrizzaQui = raddrizzando && Self.scopeInAdesso(L)
                ForEach(Array(minori.enumerated()), id: \.offset) { _, g in
                    if g.verbo == "raddrizza" && raddrizzando {
                        if !raddrizzaQui { chiudiEMandaRaddrizza(L, i, aiuto: g.aiuto, pieno: false) }
                    } else {
                        pulsante("minore-\(g.verbo)", parolaLettura(g, L), minore: true, aiuto: g.aiuto) {
                            Task { await gesto(g, conCampo: false, a, L) }
                        }
                    }
                }
                Spacer(minLength: 0)
                if raddrizzaQui, !pienoRaddrizza, let g = minori.first(where: { $0.verbo == "raddrizza" }) {
                    chiudiEMandaRaddrizza(L, i, aiuto: g.aiuto, pieno: true)
                }
                if let p = a.pulsante, !(raddrizzaQui && !pienoRaddrizza) {
                    if pienoRaddrizza && raddrizzando {
                        chiudiEMandaRaddrizza(L, i, aiuto: p.aiuto, pieno: true)
                    } else {
                        let conTesto = !campo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sceltaCambiata(L)

                        let raddrizzaSopra = raddrizzando && !Self.scopeInAdesso(L)
                        let col = conTesto && !raddrizzaSopra
                        pulsante("pieno", col && !p.parola_con_testo.isEmpty ? p.parola_con_testo : p.parola,
                                 prominente: true, aiuto: col && !p.aiuto_con_testo.isEmpty ? p.aiuto_con_testo : p.aiuto) {
                            Task { await gesto(p, conCampo: true, a, L) }
                        }

                        .disabled(raddrizzaSopra
                            || (p.verbo == "rispondi" && campo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                    }
                }
            }
        }
    }



    @ViewBuilder
    func chiudiEMandaRaddrizza(_ L: Lavorazione, _ i: Inspiration, aiuto: String, pieno: Bool) -> some View {
        Button(parola("raddrizza_chiudi") ?? i.t("chiudi")) { raddrizzando = false }
            .buttonStyle(.link).fixedSize()
        if let m = parola("invia_campo") ?? parola("manda") {
            pulsante("raddrizza", m, prominente: pieno, aiuto: aiuto) {
                Task { await mandaRaddrizza() }
            }
            .disabled(argomentiRaddrizza(L).isEmpty)
        }
    }


    func parolaLettura(_ g: PulsanteFila, _ L: Lavorazione) -> String {
        if g.verbo == "leggi_scheda", testoScheda != nil { return ispirazione.t("nascondi") }
        if g.verbo == "leggi_ritorno", testoRitorno != nil { return ispirazione.t("nascondi") }
        return g.parola
    }


    static func letturaGiaInVista(_ verbo: String, _ L: Lavorazione) -> Bool {
        if verbo == "leggi_scheda" { return (L.scheda ?? "").isEmpty }
        if verbo == "leggi_ritorno" { return (L.lavoro.ritorno ?? L.lavoro.ritorno_parziale ?? "").isEmpty }
        return false
    }


    func sceltaCambiata(_ L: Lavorazione) -> Bool {
        guard raddrizzando, let s = L.scopeFila else { return false }
        return sceltaStrada != s.strada || sceltaTipo != s.tipo || sceltaProgetto != s.progetto || sceltaArea != s.area
            || sceltaChi != s.chi
    }


    func argomentiRaddrizza(_ L: Lavorazione) -> [String] {
        var a: [String] = []
        if raddrizzando, let s = L.scopeFila {
            if sceltaStrada != s.strada, !sceltaStrada.isEmpty { a += ["--strada", sceltaStrada] }
            if sceltaTipo != s.tipo, !sceltaTipo.isEmpty, ["studio", "sviluppo"].contains(sceltaStrada) { a += ["--tipo", sceltaTipo] }
            if sceltaProgetto != s.progetto, !sceltaProgetto.isEmpty { a += ["--progetto", sceltaProgetto] }
            if sceltaArea != s.area, !sceltaArea.isEmpty { a += ["--area", sceltaArea] }
            if sceltaChi != s.chi, !sceltaChi.isEmpty, sceltaStrada == "cosa_da_fare" { a += ["--chi", sceltaChi] }
        }
        let t = campo.trimmingCharacters(in: .whitespacesAndNewlines)
        if !t.isEmpty { a += ["--testo", t] }
        return a
    }




    func argomentiGiusto(_ L: Lavorazione) -> [String] {
        if raddrizzando { return argomentiRaddrizza(L) }
        let t = campo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return [] }
        if let d = chiaveDomandeScope(L) { return ["--domanda", d, "--testo", t] }
        return ["--testo", t]
    }


    func mandaRaddrizza() async {
        let extra = argomentiRaddrizza(lavorazione)
        guard !extra.isEmpty else { return }
        await fai(comandoRaddrizza(lavorazione) + extra, "raddrizza")
        if errore == nil {
            campo = ""
            raddrizzando = false
        }
    }



    func gestoRaddrizza(_ L: Lavorazione) -> PulsanteFila? {
        guard let a = L.adessoFila else { return nil }
        return ([a.pulsante].compactMap { $0 } + a.secondari).first { $0.verbo == "raddrizza" && !$0.riga.isEmpty }
    }




    func versioneDaMandare(_ L: Lavorazione) -> String? {
        let righe = ([L.adessoFila?.pulsante].compactMap { $0 } + (L.adessoFila?.secondari ?? [])).map(\.riga)
            + [L.rigaRaddrizzaFatto].compactMap { $0 }
        for r in righe {
            let parti = r.split(separator: " ").map(String.init)
            if let k = parti.firstIndex(of: "--versione"), k + 1 < parti.count { return parti[k + 1] }
        }
        return nil
    }



    func esitoCampo(_ chiave: String, _ L: Lavorazione) -> String {
        if chiave == "scope" { return versioneDaMandare(L) ?? "" }
        guard L.passoAcceso == "scope", chiave != "dettaglio" else { return "" }
        return ([Registrazione.alloScope] + [versioneDaMandare(L)].compactMap { $0 }).joined(separator: " ")
    }



    func comandoRaddrizza(_ L: Lavorazione) -> [String] {
        if let g = gestoRaddrizza(L), let a = Self.argomenti(g, spunto.id) { return a }
        if let r = L.rigaRaddrizzaFatto, !r.isEmpty {
            let parti = r.split(separator: " ").map(String.init)
            if let primo = parti.first { return [primo, spunto.id] + parti.dropFirst() }
        }
        return ["scope", spunto.id] + (versioneDaMandare(L).map { ["--versione", $0] } ?? [])
    }



    static let righeDiRiserva: [String: String] = [
        "giusto": "scope --giusto", "rispondi": "rispondi", "capisci": "capisci", "ci_lavoriamo": "ci-lavoriamo",
        "vai": "vai", "vai_lavoro": "vai --lavoro", "letto": "ritorno-letto", "riapri": "riapri", "rifai": "scope --rifai",
        "tieni": "scope --tieni", "crea_task": "crea-task", "prendi_proposta": "scope --prendi-proposta",
        "letto_studio": "letto",
    ]




    static func argomenti(_ g: PulsanteFila, _ id: String, conTesto: Bool = false, strada: String = "") -> [String]? {
        var riga = g.riga.isEmpty ? (righeDiRiserva[g.verbo] ?? "") : g.riga
        if conTesto {
            if !g.riga_con_testo.isEmpty {
                riga = g.riga_con_testo
            } else if g.riga.isEmpty, g.verbo == "giusto", ["riferimento", "non_serve", "cosa_da_fare"].contains(strada) {
                riga = "scope"
            }
        }
        let parti = riga.split(separator: " ").map(String.init)
        guard let primo = parti.first else { return nil }
        return [primo, id] + parti.dropFirst()
    }




    func gesto(_ g: PulsanteFila, conCampo: Bool, _ a: AdessoSpunto, _ L: Lavorazione) async {
        let testo = campo.trimmingCharacters(in: .whitespacesAndNewlines)
        switch g.verbo {
        case "raddrizza":
            apriRaddrizza(L)
            return
        case "avvia":
            conTask = false
            chiediAvvio = true
            return
        case "leggi_scheda":
            if let f = L.scheda { testoScheda = testoScheda == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil }
            return
        case "leggi_ritorno":
            if let f = L.lavoro.ritorno ?? L.lavoro.ritorno_parziale {
                testoRitorno = testoRitorno == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
            }
            return
        default:
            break
        }

        let conTesto = conCampo && (!testo.isEmpty || sceltaCambiata(L))
        guard var args = Self.argomenti(g, spunto.id, conTesto: conTesto, strada: L.scopeFila?.strada ?? "") else { return }
        if g.verbo == "giusto", conCampo { args += argomentiGiusto(L) }


        if g.verbo == "rispondi" || (conTesto && args.first == "rispondi") {
            guard !testo.isEmpty else { return }
            args += ["--domanda", chiaveDomande(a), "--testo", testo]
        }
        await fai(args, conCampo ? "pieno" : "minore-\(g.verbo)")
        if errore == nil, conCampo {
            campo = ""
            raddrizzando = false
        }
    }



    @ViewBuilder
    func voceScope(_ etichetta: String?, _ valore: String) -> some View {
        if !valore.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                if let etichetta {
                    Text(etichetta).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                }
                Text(valore).fixedSize(horizontal: false, vertical: true)
            }
        }
    }




    @ViewBuilder
    func tueParole(_ tp: TueParole, _ i: Inspiration) -> some View {

        let audioQui = spunto.dettaglio.audio_owner ?? []
        let gesto = !tp.tutte_parola.isEmpty && (!tp.altre.isEmpty || !tp.audio_voci.isEmpty || (tp.audio && !audioQui.isEmpty))
        VStack(alignment: .leading, spacing: 4) {
            if let t = parola("scope_le_tue_parole") ?? parola("scope_parole_di_owner") {
                Text(t).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
            }
            if !tp.prima.isEmpty {
                Text("«\(tp.prima)»").italic()
                    .lineLimit(gesto && !paroleTutte ? 4 : nil)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if paroleTutte {
                ForEach(Array(tp.altre.enumerated()), id: \.offset) { _, a in
                    Text("«\(a)»").italic().foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                ForEach(Array(tp.audio_voci.enumerated()), id: \.offset) { _, a in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {

                        if !a.frase.isEmpty {
                            Label(a.frase, systemImage: "waveform").foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        } else if !a.trascrizione.isEmpty {
                            Text("«\(a.trascrizione)»").italic().foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                        if !a.file.isEmpty { LettoreAudio(file: a.file, ispirazione: i) }
                    }
                }
                if tp.audio_voci.isEmpty, tp.audio {
                    ForEach(audioQui, id: \.self) { a in RigaAudio(audio: a, ispirazione: i) }
                }
            }
            if gesto {
                Button(paroleTutte ? i.t("nascondi") : tp.tutte_parola) { paroleTutte.toggle() }
                    .buttonStyle(.link).fixedSize()
            }
        }
        .padding(.leading, 10)
        .overlay(alignment: .leading) { Rectangle().fill(Color.accentColor.opacity(0.5)).frame(width: 2) }
    }

    @ViewBuilder
    func bloccoScope(_ s: ScopeSpunto, _ L: Lavorazione, _ i: Inspiration, soloLettura: Bool = false) -> some View {

        let giaSopra = Set(soloLettura ? [] : [s.le_tue_parole?.prima ?? ""] + (s.le_tue_parole?.altre ?? []))
        let accanto = s.parole_di_owner_accanto.filter { !giaSopra.contains($0.testo) }
        VStack(alignment: .leading, spacing: 8) {

            if !soloLettura, let tp = s.le_tue_parole { tueParole(tp, i) }
            voceScope(parola("scope_cosa_intendi"), s.cosa_intendi)
            voceScope(parola("scope_cosa_attivo"), s.strada_frase)

            if !accanto.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    if let t = parola("scope_le_tue_parole") {
                        Text(t).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    ForEach(Array(accanto.enumerated()), id: \.offset) { _, r in
                        VStack(alignment: .leading, spacing: 1) {
                            Text("«\(r.testo)»").italic().fixedSize(horizontal: false, vertical: true)
                            if !r.quando.isEmpty { Text(r.quando).font(Testo.minimo).foregroundStyle(.secondary) }
                        }
                    }
                }
                .padding(.leading, 10)
                .overlay(alignment: .leading) { Rectangle().fill(Color.accentColor.opacity(0.5)).frame(width: 2) }
            }
            let dove = s.dove_va_frase.isEmpty ? [s.progetto, s.area].filter { !$0.isEmpty }.joined(separator: " · ") : s.dove_va_frase
            voceScope(parola("scope_dove_va"), dove)
            voceScope(parola("scope_dove_arrivare"), s.dove_arrivare)
            if !s.info_chiave.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    if let t = parola("scope_info_chiave") {
                        Text(t).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    ForEach(Array(s.info_chiave.enumerated()), id: \.offset) { _, r in
                        Text("· \(r.testo)").fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            if s.confermato, !s.confermato_frase.isEmpty {
                Label(s.confermato_frase, systemImage: "checkmark.circle.fill")
                    .font(Testo.minimo).foregroundStyle(Salute.ok.colore)
            }
            if soloLettura {

                let date = L.domande.filter { $0.chiusa && !$0.dalSistema }
                let gruppi = Self.gruppiInsieme(date)
                ForEach(date) { d in
                    if let g = Self.chiaveInsieme(d), let membri = gruppi[g] {
                        if membri.first?.id == d.id { rispostaInsieme(membri, L, i) }
                    } else {
                        rispostaData(d, L, i)
                    }
                }
            } else if !s.domande.isEmpty || !s.altre_domande.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(s.domande.enumerated()), id: \.offset) { k, d in
                        domandaScope(k + 1, d, L, i)
                    }
                    altreDomande(s.altre_domande, s.altre_domande_frase, dopo: s.domande.count, L, i)
                }
                .padding(.top, 2)
            }
        }
    }


    @ViewBuilder
    func altreDomande(_ altre: [DomandaFila], _ frase: String, dopo: Int, _ L: Lavorazione, _ i: Inspiration) -> some View {
        if !altre.isEmpty {
            let n = altre.count
            DisclosureGroup(isExpanded: $altreAperte) {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(altre.enumerated()), id: \.offset) { k, d in
                        domandaScope(dopo + k + 1, d, L, i)
                    }
                }
                .padding(.top, 6)
            } label: {
                Text(!frase.isEmpty ? frase
                    : (n == 1 ? parola("scope_altra_domanda") : parola("scope_altre_domande", ["n": "\(n)"])) ?? "+\(n)")
                    .font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            }
        }
    }



    @ViewBuilder
    func domandaScope(_ n: Int, _ d: DomandaFila, _ L: Lavorazione, _ i: Inspiration) -> some View {
        let ds = L.domande.first { $0.id == d.id }
        if let ds, ds.chiusa {
            rispostaData(ds, L, i)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Button("\(n)") { domandaAperta = domandaAperta == d.id ? nil : d.id }
                        .buttonStyle(.borderless)
                        .font(Testo.secondario.weight(.semibold).monospacedDigit())
                        .help(i.t("rispondi"))
                        .disabled(ds?.inViaggio ?? false)
                    Text(d.testo).fixedSize(horizontal: false, vertical: true)
                }
                if !d.risposta.isEmpty {
                    Text("«\(d.risposta)»").font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true).padding(.leading, 18)
                }
                if let ds, let sf = ds.stato_frase, !sf.isEmpty {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Label(sf, systemImage: "waveform").font(Testo.secondario)
                            .foregroundStyle(ds.inViaggio ? Color.accentColor : Salute.attenzione.colore)
                            .fixedSize(horizontal: false, vertical: true)
                        if let a = ds.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                    }
                    .padding(.leading, 18)
                }
                if let ds, domandaAperta != d.id, !ds.inViaggio { pulsantiVerifica(ds, ds.id, i) }
                if domandaAperta == d.id {
                    CampoRisposta(testo: $risposta, segnaposto: i.t("risposta_segnaposto"), voce: spunto.id, chiave: d.id,
                                  cosa: Self.taglia(d.testo), esito: esitoCampo(d.id, L), cartella: L.cartella,
                                  cartellaRegistro: L.cartellaRegistro, ispirazione: i, inCorso: inCorso == d.id,
                                  invia: { testo in

                                      let args = L.passoAcceso == "scope"
                                          ? comandoRaddrizza(L) + ["--domanda", d.id, "--testo", testo]
                                          : ["rispondi", spunto.id, "--domanda", d.id, "--testo", testo]
                                      await fai(args, d.id)
                                      domandaAperta = nil
                                      risposta = ""
                                  },
                                  dopoAudio: { domandaAperta = nil },
                                  chiudi: { domandaAperta = nil })
                }
            }
        }
    }



    @ViewBuilder
    func bloccoRaddrizza(_ s: ScopeSpunto, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let sc = s.scelte, !sc.vuote {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 12) { menuScelte(sc) }
                    VStack(alignment: .leading, spacing: 6) { menuScelte(sc) }
                }
            }
            voceScope(parola("scope_su_cosa_poggia"), s.su_cosa_poggia_frase)
            if !s.prima_dicevo.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    if let t = parola("scope_prima_dicevo") {
                        Text(t).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
                    }
                    ForEach(Array(s.prima_dicevo.enumerated()), id: \.offset) { _, r in
                        Text(r.quando.isEmpty ? r.testo : "\(r.quando) · \(r.testo)")
                            .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }

    @ViewBuilder
    func menuScelte(_ sc: ScelteScope) -> some View {
        sceltaMenu(parola("scope_cosa_attivo"), sc.strade, $sceltaStrada)

        if ["studio", "sviluppo"].contains(sceltaStrada) { sceltaMenu(parola("scope_tipo"), sc.tipi, $sceltaTipo) }
        if sceltaStrada == "cosa_da_fare" { sceltaMenu(nil, sc.chi, $sceltaChi) }
        sceltaMenu(parola("scope_progetto"), sc.progetti, $sceltaProgetto)
        sceltaMenu(parola("scope_area"), sc.aree, $sceltaArea)
    }

    @ViewBuilder
    func sceltaMenu(_ etichetta: String?, _ scelte: [SceltaFila], _ valore: Binding<String>) -> some View {
        if !scelte.isEmpty {
            HStack(spacing: 4) {
                if let etichetta { Text(etichetta).font(Testo.minimo).foregroundStyle(.secondary) }
                Picker(etichetta ?? "", selection: valore) {

                    if !valore.wrappedValue.isEmpty, !scelte.contains(where: { $0.id == valore.wrappedValue }) {
                        Text(valore.wrappedValue).tag(valore.wrappedValue)
                    }
                    if valore.wrappedValue.isEmpty { Text("").tag("") }
                    ForEach(scelte) { c in Text(c.parola).tag(c.id) }
                }
                .pickerStyle(.menu)
                .labelsHidden()
                .fixedSize()
            }
        }
    }



    @ViewBuilder
    func campoUnico(_ c: CampoFila?, _ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration, chiave: String) -> some View {
        CampoRisposta(testo: $campo, segnaposto: c?.segnaposto ?? (parola("campo_scope") ?? ""), voce: spunto.id,
                      chiave: chiave, cosa: cosaDelCampo(chiave, a, L, i),
                      esito: esitoCampo(chiave, L), cartella: L.cartella,
                      cartellaRegistro: L.cartellaRegistro, ispirazione: i,
                      inCorso: inCorso == "campo",
                      invia: { testo in
                          let allo = L.passoAcceso == "scope"
                          let verbo = chiave == "scope" ? comandoRaddrizza(L) + argomentiRaddrizza(L)
                              : (allo && chiave != "dettaglio"
                                  ? comandoRaddrizza(L) + ["--domanda", chiave, "--testo", testo]
                                  : ["rispondi", spunto.id, "--domanda", chiave == "dettaglio" ? "tutte" : chiave, "--testo", testo])
                          await fai(verbo, "campo")
                          if errore == nil {
                              campo = ""
                              raddrizzando = false
                          }
                      },
                      dopoAudio: {},
                      chiudi: nil,
                      conInvia: a.pulsante == nil && !raddrizzando,
                      conMicrofono: c?.audio ?? true)
    }


    func cosaDelCampo(_ chiave: String, _ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> String {
        switch chiave {
        case "scope": return parola("passo_scope") ?? ""
        case "tutte": return i.t("registrando_tutte")
        case "dettaglio": return i.t("registrando_dettaglio")
        default:
            let d = (L.scopeFila?.domande ?? []) + a.domande
            return d.first { $0.id == chiave }.map { Self.taglia($0.testo) } ?? i.t("registrando_dettaglio")
        }
    }



    @ViewBuilder
    func letture(_ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        let scheda = L.scheda.flatMap { $0.isEmpty ? nil : $0 }
        let ritorno = L.lavoro.ritorno ?? L.lavoro.ritorno_parziale
        let passoTardo = ["implementazione", "test"].contains(a.passo)
        let linkScheda = passoTardo && scheda != nil && !a.ha("leggi_scheda")
        let linkRitorno = passoTardo && ritorno != nil && !a.ha("leggi_ritorno")
        if linkScheda || linkRitorno {
          HStack(spacing: 14) {
            if linkScheda, let f = scheda {
                Button(testoScheda == nil ? i.t("leggi_scheda") : i.t("nascondi")) {
                    testoScheda = testoScheda == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                }
                .buttonStyle(.link).fixedSize()
            }
            if linkRitorno, let f = ritorno {
                Button(testoRitorno == nil ? i.t("leggi_ritorno") : i.t("nascondi")) {
                    testoRitorno = testoRitorno == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                }
                .buttonStyle(.link).fixedSize()
            }
          }
        }
        if let t = testoScheda { Testolungo(testo: t) }
        if let t = testoRitorno { Testolungo(testo: t) }
    }



    @ViewBuilder
    func riquadroUscita(_ u: UscitaSpunto, _ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if !a.titolo.isEmpty {
                Text(a.titolo).font(Testo.minimo.weight(.semibold)).foregroundStyle(.secondary)
            }
            Label(u.frase, systemImage: Self.simboloUscita(u.tipo))
                .font(Testo.corpo.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            if !raddrizzando { esitoNelRiquadro(i) }
            if let t = u.task {
                if t.stato == "eliminata" {


                    HStack(spacing: 10) {
                        Label(t.dove_frase, systemImage: "arrow.turn.down.right")
                            .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        if let g = t.rifai {
                            pulsante("uscita-rifai", g.parola, minore: true, aiuto: g.aiuto) {
                                Task { if let args = Self.argomenti(g, spunto.id) { await fai(args, "uscita-rifai") } }
                            }
                        }
                    }
                } else if let link = URL(string: t.id), t.id.hasPrefix("http") {
                    Link(destination: link) { Label(t.dove_frase, systemImage: "arrow.up.right.square") }
                        .font(Testo.secondario)
                } else if let id = idInAttivita(t.id) {

                    Button { Task { await store.apriTaskInAttivita(id) } } label: {
                        Label(t.dove_frase, systemImage: "arrow.turn.down.right")
                    }
                    .buttonStyle(.link)
                    .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                } else {
                    Label(t.dove_frase, systemImage: "arrow.turn.down.right")
                        .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if !a.poi.isEmpty, a.poi != u.frase {
                Text(a.poi).font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Spacer(minLength: 0)
                ForEach(Array(a.secondari.enumerated()), id: \.offset) { _, g in
                    pulsante("minore-\(g.verbo)", g.parola, minore: true, aiuto: g.aiuto) {
                        Task { await gesto(g, conCampo: false, a, L) }
                    }
                }

                if let c = u.crea_task, !a.ha(c.verbo) {
                    pulsante("minore-\(c.verbo)", c.parola, minore: true, aiuto: c.aiuto) {
                        Task { await gesto(c, conCampo: false, a, L) }
                    }
                }
                if !a.ha("riapri"), !u.riapri_parola.isEmpty {
                    pulsante("riapri", u.riapri_parola, minore: true, aiuto: u.riapri_aiuto) {
                        Task { await fai(["riapri", spunto.id], "riapri") }
                    }
                }
                if let p = a.pulsante {
                    pulsante("pieno", p.parola, prominente: true, aiuto: p.aiuto) {
                        Task { await gesto(p, conCampo: false, a, L) }
                    }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
    }




    func idInAttivita(_ id: String) -> String? {
        guard !id.isEmpty, !id.hasPrefix("http") else { return nil }
        let nudo = id.hasPrefix("attivita:") ? String(id.dropFirst("attivita:".count)) : id
        return store.coseIndice[nudo] != nil ? nudo : nil
    }





    @ViewBuilder
    func taskDelLavoro(_ lavoro: LavoroSpunto, _ i: Inspiration) -> some View {
        let task = lavoro.task
        let parola = i.t("uscita_task_attivita", o: "In your tasks")
        if lavoro.task_stato?.v == "eliminata" {

            HStack(spacing: 10) {

                Label(i.t("uscita_task_attivita_eliminata", o: "Removed from Tasks"), systemImage: "arrow.turn.down.right")
                    .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if let g = lavoro.task_rifai, !g.parola.isEmpty, !g.verbo.isEmpty {
                    pulsante("lavoro-rifai", g.parola, minore: true, aiuto: g.aiuto) {
                        Task { if let args = Self.argomenti(g, spunto.id) { await fai(args, "lavoro-rifai") } }
                    }
                }
            }
        } else if task.hasPrefix("http"), let u = URL(string: task) {
            Link("ClickUp", destination: u).font(Testo.secondario)
        } else if let id = idInAttivita(task) {
            Button { Task { await store.apriTaskInAttivita(id) } } label: {
                Label(parola, systemImage: "arrow.turn.down.right")
            }
            .buttonStyle(.link)
            .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
        } else if task.hasPrefix("attivita:") {
            Label(parola, systemImage: "arrow.turn.down.right")
                .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }

    static func simboloUscita(_ tipo: String) -> String {
        switch tipo {
        case "riferimento": "bookmark"
        case "cosa_da_fare": "checklist"
        case "non_serve": "xmark.circle"
        case "letto": "checkmark.circle"
        default: "arrow.turn.down.right"
        }
    }


    @ViewBuilder
    func infoCambio(_ c: CambioScope) -> some View {
        if !c.adesso_e.isEmpty {
            voceScope(parola("cambio_adesso_e"), c.adesso_e)
        }
        if !c.rifa.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(c.rifa.enumerated()), id: \.offset) { _, r in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "arrow.clockwise").foregroundStyle(.secondary)
                        if !r.nome.isEmpty { Text(r.nome).font(Testo.secondario.weight(.semibold)).fixedSize() }
                        Text(r.frase.isEmpty ? r.quando_frase : r.frase).font(Testo.secondario)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        if !c.resta_frase.isEmpty {
            Label(c.resta_frase, systemImage: "checkmark").font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }



    @ViewBuilder
    func pannelloCambio(_ c: CambioScope, _ a: AdessoSpunto, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let t = parola("cambio_titolo") {
                Text(t).font(Testo.titoloGruppo)
            }
            infoCambio(c)
            let tieni = !c.pulsante_tieni.isEmpty && !a.ha("tieni")
            let rifai = !c.pulsante_rifai.isEmpty && !a.ha("rifai")
            if tieni || rifai {
                HStack(spacing: 10) {
                    Spacer(minLength: 0)
                    if tieni {
                        pulsante("tieni", c.pulsante_tieni, aiuto: c.aiuto_tieni) {
                            Task { await fai(["scope", spunto.id, "--tieni"], "tieni") }
                        }
                    }
                    if rifai {
                        pulsante("rifai", c.pulsante_rifai, prominente: a.pulsante == nil, aiuto: c.aiuto_rifai) {
                            Task { await fai(["scope", spunto.id, "--rifai"], "rifai") }
                        }
                    }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        .overlay(RoundedRectangle(cornerRadius: Raggio.riquadro).strokeBorder(Color.accentColor.opacity(0.45), lineWidth: 1))
    }



    @ViewBuilder
    func raddrizzaDaFatto(_ s: ScopeSpunto, _ a: AdessoSpunto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let t = parola("cambio_titolo") { Text(t).font(Testo.titoloGruppo) }
            if let c = L.cambioFila, !c.da_decidere { infoCambio(c) }
            esitoNelRiquadro(i)
            bloccoRaddrizza(s, i)
            campoUnico(nil, a, L, i, chiave: "scope")
            HStack(spacing: 14) {
                Spacer(minLength: 0)
                chiudiEMandaRaddrizza(L, i, aiuto: parola("aiuto_raddrizza") ?? "", pieno: false)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        .overlay(RoundedRectangle(cornerRadius: Raggio.riquadro).strokeBorder(Color.accentColor.opacity(0.45), lineWidth: 1))
    }

    @ViewBuilder
    func fattoLista(_ L: Lavorazione, _ i: Inspiration) -> some View {
        let righe = L.fattoFila
        if !righe.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                if let t = parola("fatto_titolo") {
                    Text(t).font(Testo.titoloGruppo)
                }
                ForEach(Array(righe.enumerated()), id: \.offset) { _, f in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.secondary)
                            Text(f.nome).font(Testo.secondario.weight(.semibold)).fixedSize()
                            Text([f.quando_frase, f.riassunto].filter { !$0.isEmpty }.joined(separator: " · "))
                                .font(Testo.secondario).foregroundStyle(.secondary)
                                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 6)
                            if f.rivedi, let r = parola("rivedi") {
                                Button(r) {
                                    if rivisti.contains(f.passo) { rivisti.remove(f.passo) } else { rivisti.insert(f.passo) }
                                }
                                .buttonStyle(.link).fixedSize()
                            }
                            if f.raddrizza, !raddrizzando, let r = parola("raddrizza") {
                                Button(r) { apriRaddrizza(L) }
                                    .buttonStyle(.link).fixedSize()
                                    .help(parola("aiuto_raddrizza") ?? "")
                            }


                            if let g = f.riapri {
                                pulsante("fatto-riapri", g.parola, minore: true, aiuto: g.aiuto) {
                                    Task {
                                        if let args = Self.argomenti(g, spunto.id) { await fai(args, "fatto-riapri") }
                                    }
                                }
                            }
                        }
                        if rivisti.contains(f.passo) {
                            rivedi(f, L, i).padding(.leading, 22)
                        }
                    }
                }
            }
        }
    }



    @ViewBuilder
    func rivedi(_ f: PassoFatto, _ L: Lavorazione, _ i: Inspiration) -> some View {
        switch f.passo {
        case "capire":
            ParoleDiOwner(spunto: spunto, ispirazione: i)
        case "scope":
            if let s = L.scopeFila { bloccoScope(s, L, i, soloLettura: true) }
        case "contesto":
            if L.piano.c_e { piano(L.piano, i) }
        case "ricerca":
            if let f = L.scheda, !f.isEmpty {
                Button(testoScheda == nil ? i.t("leggi_scheda") : i.t("nascondi")) {
                    testoScheda = testoScheda == nil ? (try? String(contentsOfFile: f, encoding: .utf8)) ?? "" : nil
                }
                .buttonStyle(.link).fixedSize()
                if let t = testoScheda { Testolungo(testo: t) }
            }
        case "implementazione", "test":
            if L.lavoro.avviato { lavoro(L, i) }
            if L.lavoro.ritorno != nil { ritorno(L, i) }
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    func dopoLista(_ L: Lavorazione, _ i: Inspiration) -> some View {
        let righe = L.dopoFila
        if !righe.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                if let t = parola("dopo_titolo") {
                    Text(t).font(Testo.titoloGruppo)
                }
                ForEach(Array(righe.enumerated()), id: \.offset) { _, d in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "circle").foregroundStyle(.secondary)
                        Text(d.nome).font(Testo.secondario).fixedSize()
                        if !d.frase.isEmpty {
                            Text(d.frase).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
    }
}




struct CampoRisposta: View {
    @Binding var testo: String
    let segnaposto: String
    let voce: String
    let chiave: String
    let cosa: String
    let esito: String
    let cartella: String
    let cartellaRegistro: String
    let ispirazione: Inspiration
    let inCorso: Bool
    let invia: (String) async -> Void
    let dopoAudio: () -> Void
    let chiudi: (() -> Void)?

    var conInvia = true

    var conMicrofono = true
    @Environment(Store.self) private var store
    private var reg: Registratore { Registratore.condiviso }

    var body: some View {
        let i = ispirazione
        let mia = reg.e(voce, chiave)
        VStack(alignment: .leading, spacing: 6) {
            if mia && reg.stato == .registra {
                HStack(spacing: 10) {
                    Image(systemName: "record.circle.fill").foregroundStyle(.red)
                        .symbolEffect(.pulse, options: .repeating)
                    Text(i.t("registrando", ["secondi": Registratore.durata(reg.secondi)])).monospacedDigit()
                    BarraLivello(livello: reg.livello, bassa: reg.bassa, ispirazione: i)
                    Spacer(minLength: 0)
                    Button(i.t("annulla")) { reg.annulla() }
                    Button(i.t("ferma")) {
                        if let r = reg.ferma() {
                            dopoAudio()
                            Task { _ = await store.mandaRegistrazione(r) }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.return, modifiers: .command)
                }
                if reg.bassa { AvvisoLivello(ispirazione: i) }
            } else if mia && reg.stato == .chiedo {
                Label(i.t("chiedo_permesso"), systemImage: "mic").font(Testo.secondario).foregroundStyle(.secondary)
            } else if mia && reg.stato == .invio {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(i.t("invio_audio")).font(Testo.secondario).foregroundStyle(.secondary)
                }
            } else {
                TextField(segnaposto, text: $testo, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...6)
                    .disabled(inCorso)
                if conMicrofono || conInvia || chiudi != nil || inCorso {
                    HStack(spacing: 8) {
                        if conMicrofono {
                            Button {
                                Task {
                                    await reg.comincia(voce: voce, chiave: chiave, cosa: cosa, esito: esito, cartella: cartella,
                                                       cartellaRegistro: cartellaRegistro, testi: { i.t($0) })
                                }
                            } label: {
                                Label(i.t("registra"), systemImage: "mic.fill")
                            }
                            .disabled(reg.occupato || store.modoIstantanea || inCorso)
                            .help(reg.occupato && !mia ? i.t("aiuto_registra_occupato") : i.t("aiuto_registra"))
                            if reg.occupato && !mia {
                                Text(i.t("aiuto_registra_occupato")).font(Testo.minimo).foregroundStyle(.secondary)
                            }
                        }
                        Spacer(minLength: 0)
                        if inCorso {
                            ProgressView().controlSize(.small)
                            Text(i.t("un_attimo")).font(Testo.minimo).foregroundStyle(.secondary)
                        }
                        if let chiudi {
                            Button(i.t("chiudi"), action: chiudi).disabled(inCorso)
                        }
                        if conInvia {
                            Button(i.t("invia")) {
                                let t = testo.trimmingCharacters(in: .whitespacesAndNewlines)
                                guard !t.isEmpty else { return }
                                Task { await invia(t) }
                            }
                            .disabled(testo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || inCorso)
                            .keyboardShortcut(.return, modifiers: .command)
                        }
                    }
                }
            }

            if reg.problemaPer == chiave, mia || reg.voce == nil || reg.voce == voce, let p = reg.problema {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(p).font(Testo.minimo).foregroundStyle(Salute.attenzione.colore)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    if reg.negato {
                        Button(i.t("apri_impostazioni")) { Registratore.apriImpostazioni() }
                    }
                    Button(i.t("chiudi")) { reg.chiudiProblema() }
                }
            }
        }
    }
}




struct StrisciaRegistrazione: View {
    let ispirazione: Inspiration
    @Environment(Store.self) private var store
    private var reg: Registratore { Registratore.condiviso }

    var body: some View {
        let i = ispirazione
        Group {
            switch reg.stato {
            case .registra:
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 10) {
                        Image(systemName: "record.circle.fill").foregroundStyle(.red)
                            .symbolEffect(.pulse, options: .repeating)
                        Text(i.t("registrando_per", ["secondi": Registratore.durata(reg.secondi), "cosa": reg.cosa]))
                            .monospacedDigit().fixedSize(horizontal: false, vertical: true)
                        BarraLivello(livello: reg.livello, bassa: reg.bassa, ispirazione: i)
                        Spacer(minLength: Spazio.fratelli)
                        Button(i.t("annulla")) { reg.annulla() }
                        Button(i.t("ferma")) {
                            if let r = reg.ferma() { Task { _ = await store.mandaRegistrazione(r) } }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    if reg.bassa { AvvisoLivello(ispirazione: i) }
                }
            case .chiedo:
                Label(i.t("chiedo_permesso"), systemImage: "mic").foregroundStyle(.secondary)
            case .invio:
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(i.t("invio_audio")).foregroundStyle(.secondary)
                }
            case .annullata, .corta:
                if let d = reg.daParte {
                    HStack(spacing: 10) {
                        Image(systemName: "waveform").foregroundStyle(.secondary)
                        Text(d.corta ? i.t("registrazione_corta")
                            : i.t("registrazione_annullata", ["durata": Registratore.durata(d.registrazione.secondi)]))
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: Spazio.fratelli)
                        if !d.corta {
                            Button(i.t("mandala")) {
                                if let r = reg.riprendiDaParte() { Task { _ = await store.mandaRegistrazione(r) } }
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        Button(i.t("chiudi")) { reg.lasciaDaParte() }
                    }
                }
            case .fermo, .negato:
                EmptyView()
            }
        }
        .font(Testo.corpo)
        .padding(.horizontal, Spazio.margine)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(reg.stato == .registra ? Color.red.opacity(0.10) : Superficie.riquadro)
    }


    static var visibile: Bool {
        let r = Registratore.condiviso
        let s = r.stato

        if s == .annullata || s == .corta, r.daParte?.registrazione.perAttivita == true { return false }
        return s == .registra || s == .chiedo || s == .invio || s == .annullata || s == .corta
    }
}



struct BarraLivello: View {
    let livello: Double
    let bassa: Bool
    let ispirazione: Inspiration

    var body: some View {
        ProgressView(value: livello)
            .progressViewStyle(.linear)
            .tint(bassa ? Salute.attenzione.colore : (livello > 0.55 ? Salute.ok.colore : Color.accentColor))
            .frame(width: 64)
            .help(ispirazione.t("aiuto_livello", o: "How well I hear you"))
    }
}


struct AvvisoLivello: View {
    let ispirazione: Inspiration

    var body: some View {
        Label(ispirazione.t("livello_basso", o: "I don't hear you yet"),
              systemImage: "mic.badge.xmark")
            .font(Testo.minimo).foregroundStyle(Salute.attenzione.colore)
            .fixedSize(horizontal: false, vertical: true)
    }
}


struct Testolungo: View {
    let testo: String

    var body: some View {
        ScrollView {
            Text(testo)
                .font(Testo.secondario)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
        }
        .frame(maxHeight: 420)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }
}
