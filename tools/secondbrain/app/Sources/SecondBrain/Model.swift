import Foundation




let contrattoAtteso = 2

struct Stato: Codable {
    let contratto: Int?
    let impronta: Impronta?
    let generato: String
    let verdetto: Verdetto
    let da_sistemare: [RigaDaSistemare]
    let altri_da_sistemare: Int?
    let fasi: [Fase]
    let stadi: [Stadio]
    let fonti: [Fonte]
    let gruppi_fonti: [GruppoFonti]
    let run_app: Run?
    let da_fuori: DaFuori
    let ultimo_full_run: Giro?

    let codice_cambiato: CodiceCambiato?
    let runs: [Run]
    let azioni: Azioni
    let sonno: Sonno?
    let memoria: Memoria?
    let tempo_ms: Int?

    let chiavi: [Chiave]?

    let stima: Stima?

    let fuori_stima: [String]?

    let copie: Copie?

    let lavori: Lavori?

    let disco: Disco?

    let scarichi_soli: [Run]?

    let vocabolario: [String: [String: VoceStato]]?

    let guida: Guida?

    let da_sola: [String: DaSolo]?

    let ripresa: Ripresa?

    let lotti_in_sospeso: [LottoSospeso]?

    let verifiche: RiassuntoVerifiche?

    let capsula: CapsulaMotore?

    let completa: [String: String]?



    func c(_ chiave: String, _ valori: [String: String] = [:]) -> String {
        var t = completa?[chiave] ?? chiave
        for (k, v) in valori { t = t.replacingOccurrences(of: "{\(k)}", with: v) }
        return t
    }
}


struct CapsulaMotore: Codable, Hashable {
    let simbolo: String?
    let salute: String
    let frase: String
    let aiuto: String
    let aiuto_run: String?
    let aiuto_terminale: String?
    let da_terminale: String?
}



struct ComandiRun: Codable, Hashable {
    struct Pausa: Codable, Hashable {
        let possibile: Bool
        let perche: String?
        let frase: String?
        let richiesta: Bool?
        let in_pausa: Bool?
    }

    struct Continua: Codable, Hashable {
        let possibile: Bool
    }

    struct Ferma: Codable, Hashable {
        let frase: String
    }


    let fase: String
    let pausa: Pausa
    let continua: Continua
    let ferma: Ferma

    let frase: String
}


struct Ripresa: Codable, Hashable {
    let cartella: String
    let modo: String
    let spende: Bool
    let spesa: String?
    let salta: [String]
    let rifa: [String]
    let possibile: Bool
    let perche: String
    let frase: String
    let azione: Azione
}


struct LottoSospeso: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let leggibile: Bool
    let lotti: Int?
    let inviati: String?

    let dati_nuovi_dopo: Bool?
}

struct Chiave: Codable, Hashable, Identifiable {
    let nome: String
    let origine: String?
    let presente: Bool?
    let di_turno: Bool?

    let paga: Bool?
    let ultimo_uso: Double?
    let errore: String?
    let errore_quando: Double?
    var id: String { nome }
}


struct Rilascio: Codable, Hashable, Identifiable {
    let versione: String?
    let data: String?
    let commit: String?
    let canale: String?
    let novita: [String]?
    var id: String { (versione ?? "") + "@" + (data ?? "") }
}

struct Impronta: Codable, Hashable {
    let motore: String?
    let app: String?

    let contenuto: String?

    let versione: String?
    let storia: [Rilascio]?
}

struct Verdetto: Codable, Hashable {
    let livello: String
    let titolo: String
    let frase: String
    let orologi: String

    let scaricate: String?
    let nel_cervello: String?
    let azione: Azione?
    let oggetto: Oggetto?
}

struct Azione: Codable, Hashable {
    let tipo: String
    let arg: String?
    let etichetta: String

    var lungo: Bool? = nil
    var nome: String? = nil
    var frase: String? = nil
    var step: String? = nil
}

struct Oggetto: Codable, Hashable {
    let tipo: String
    let id: String
}

struct RigaDaSistemare: Codable, Hashable, Identifiable {
    let livello: String
    let titolo: String
    let frase: String
    let oggetto: Oggetto
    let azione: Azione?
    var id: String { oggetto.tipo + ":" + oggetto.id + ":" + titolo }
}

struct Fase: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let etichetta: String
    let descrizione: String
    let pagata: Bool
    let stadi: [String]
    let salute: String
    let frase: String
    let quando: String?
    let data: String

    let stato: String?
    let perche: String?
    let azione: Azione?

    let aiuto: String?
}

struct Ultimo: Codable, Hashable {
    let quando: String?
    let esito: String
    let durata_s: Double?
    let fonte: String
    let nota: String?
    let membri: [String: String?]?
}

struct DaSolo: Codable, Hashable {
    let possibile: Bool
    let perche: String

    let frase: String?
    let azione: Azione?
}

struct Stadio: Codable, Hashable, Identifiable {
    let id: String
    let numero: Int
    let nome: String
    let nome_tecnico: String
    let frase: String
    let strato: String
    let tipo: String
    let pagato: Bool
    let ultimo: Ultimo
    let salute: String
    let parola: String



    let parola_breve: String?
    let stato: String?
    let data: String?
    let perche: String?


    let da_quanto: String?
    let aiuto: String?
    let gira_con: [String]
    let da_solo: DaSolo
}

struct Tentativo: Codable, Hashable {
    let quando: String?
    let esito: String?
    let passo: String?
}

struct RifStadio: Codable, Hashable {
    let id: String
    let nome: String
}

struct Fonte: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let descrizione: String
    let gruppo: String
    let natura: String
    let salute: String
    let parola: String
    let motivo: String

    let vuota: Bool?
    let dato_del: String?
    let giorni: Double?
    let scaricata: String?
    let passi_senza_traccia: [String]?
    let ultimo_tentativo: Tentativo?
    let lettura: String?
    let soglia: String
    let ritmo_giorni: Int?

    let aiuto: String?
    let come_si_aggiorna: String
    let passi_a_mano: String?
    let entra_in: RifStadio?
    let azione: Azione?

    let import_whatsapp: ImportWhatsApp?

    let diagnosi: Diagnosi?
}




struct Diagnosi: Codable, Hashable {
    let id: String
    let passo: String?
    let sorgente: String?
    let causa: String
    let rimedio: String
    let azione: Azione?

    let chi: String?
    let ritenta: Bool?

    let gravita: String?
    let riga: String?
    let rc: Int?
    let nota: String?
    let log: String?

    let stadio: String?
}

struct DiagnosiStadio: Codable, Hashable {
    let stadio: String
    let diagnosi: Diagnosi
}

struct ImportWhatsApp: Codable, Hashable {
    struct Completo: Codable, Hashable {
        let quando: String?
        let dati_fino_al: String?
        let chat: Int?
    }

    struct Carico: Codable, Hashable {
        let quando: String?
        let chat: Int?
        let giri: Int?
        let dopo_il_completo: Bool?
    }

    let completo: Completo?
    let chat: Carico?
    let ultimo_import: String?
    let da_dove: String?
}

struct GruppoFonti: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let nota: String
    let chiuso: Bool
}

struct Corrente: Codable, Hashable {
    let id: String
    let nome: String

    let corsia: String?
    let dalle: String?
    let di_solito_s: Double?
    let tetto_s: Double?
    let tentativo: Int?
    let ultimo_segno_s: Int?

    let al_lavoro: String?
    let pagato: Bool?
    let lotti_salvati: Bool?

    let partito: String?
    let da_s: Double?

    let come_va: String?
}

struct PassoRun: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let stato: String
    let nota: String?
    let durata_s: Double?
    let tentativo: Int?
    let tentativi: Int?
    let sorgente: String?
    let pagato: Bool?

    let diagnosi: Diagnosi?
    let avvisi: [Diagnosi]?

    let ripreso: Bool?


    let fase: String?
}

struct Custode: Codable, Hashable {
    let battito_s: Int?
    let dormito_s: Int?
}

struct Avanzamento: Codable, Hashable {
    let tipo: String
    let passi: [PassoRun]
    let denominatore: String
    let corrente: Corrente?
    let eventi: [String]?
    let esito: String?
    let fine: String?

    let dentro: [Avanzamento]?
    let custode: Custode?

    let corsie: [CorsiaRun]?
    let correnti: [Corrente]?
    let corsie_non_partite: [String]?

    let previsione: Previsione?

    let diagnosi_run: [DiagnosiStadio]?
}

struct CorsiaRun: Codable, Hashable, Identifiable {
    let nome: String
    let passi: [String]
    let fatti: Int
    let totale: Int
    let corrente: String?
    var id: String { nome }
}

struct Previsione: Codable, Hashable {
    let scarico_s: Double?
    let rilettura_s: Double?
    let restano_s: Double?
    let fine_prevista: String?
    let senza_stima: [String]?
    let come: String?

    let frase: String?

    let frazione_tempo: Double?

    let fasi: [FaseRestante]?
}

struct FaseRestante: Codable, Hashable {
    let fase: String
    let restano_s: Double?
}

struct Run: Codable, Hashable, Identifiable {
    let run_id: String
    let etichetta: String?
    let nome: String?
    let comando: String?
    let pid: Int?
    let log: String
    let cartella: String?
    let inizio: String
    let fine: String?
    let esito: String?
    let frase: String?

    let racconto: String?
    let rc: Int?
    let fermato: String?
    let motivo: String?
    let dormito_s: Int?
    let rimasti: [Int]?
    let vivo: Bool
    let avanzamento: Avanzamento?

    let riga: String?

    let chiave: String?
    let spesa: [String]?

    let sorgente: String?

    let comandi: ComandiRun?
    var id: String { run_id }
}

struct Processo: Codable, Hashable {
    let pid: Int
    let etime: String
    let script: String
}

struct DaFuori: Codable, Hashable {
    let attivo: Bool
    let processi: [Processo]
    let giro: Avanzamento?
    let frase: String
}

struct Giro: Codable, Hashable {
    let cartella: String
    let inizio: String?
    let fine: String?
    let non_chiusi: String?

    let fermato: Bool?
    let passo_in_corso: String?
    let ultimo_segno_s: Int?
    let vivo: Bool?


    let nome: String?
    let esito: String?
    let salute: String?
    let parola: String?
    let frase: String?
    let titolo: String?
    let nota: String?
}

struct VoceMenu: Codable, Hashable, Identifiable {
    let id: String
    let tipo: String
    let arg: String
    let nome: String
    let frase: String
    let step: String
    let spesa: Bool
}

struct PassoConferma: Codable, Hashable {
    let titolo: String
    let frase: String
}

struct ConfermaFull: Codable, Hashable {
    let passi: [PassoConferma]
    let fuori: [String]
    let ultima_volta: String
}

struct Azioni: Codable, Hashable {
    let possibile: Bool
    let perche: String
    let menu: [VoceMenu]
    let conferma_full: ConfermaFull
}

struct Sonno: Codable, Hashable {
    let coperchio: String
    let alimentazione: String
    let carica: Int?
}

struct Memoria: Codable, Hashable {
    let livello: String?

    let pressione_pct: Int?
    let disco_libero_gb: Int?
    let disco_totale_gb: Int?
}


struct Esito: Codable {
    let ok: Bool?
    let errore: String?
    let run_id: String?
    let log: String?
    let cartella: String?
    let righe: [String]?
    let vivo: Bool?
    let run: Run?
    let avanzamento: Avanzamento?
    let comandi: ComandiRun?
    let richiesto: Bool?
    let rimasti: [Int]?
    let riga: String?
}

struct StadioStima: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let dollari: Double?
    let documenti: Int?
    let errore: String?

    let nota: String?
}

struct Stima: Codable, Hashable {
    let quando: String
    let stadi: [StadioStima]
    let totale: Double?
    let come: String?

    let fuori: [String]?

    let margine_tetto_pct: Int?
}

struct EsitoStima: Codable {
    let ok: Bool?
    let errore: String?
    let stima: Stima?
}



enum Quando {
    static let parser: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()




    static let formatoreOra24: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f
    }()

    static func ora24(_ d: Date) -> String { formatoreOra24.string(from: d) }

    static let mesi = ["January", "February", "March", "April", "May", "June", "July", "August",
                       "September", "October", "November", "December"]

    static func data(_ ts: String?) -> Date? {
        guard let ts, ts.count >= 19 else { return nil }
        return parser.date(from: String(ts.prefix(19)))
    }

    static func adesso() -> String { parser.string(from: Date()) }


    static func frase(_ ts: String?, adesso: Date = Date()) -> String {
        guard let d = data(ts) else { return "never" }
        let cal = Calendar.current
        let giorni = cal.dateComponents([.day], from: cal.startOfDay(for: d), to: cal.startOfDay(for: adesso)).day ?? 0
        let ora = ora24(d)
        if giorni == 0 { return "today at \(ora)" }
        if giorni == 1 { return "yesterday at \(ora)" }
        let c = cal.dateComponents([.day, .month, .year], from: d)

        let base = "\(mesi[(c.month ?? 1) - 1]) \(c.day ?? 0)"
        return c.year == cal.component(.year, from: adesso) ? base : "\(base) \(c.year ?? 0)"
    }


    static func breve(_ ts: String?, adesso: Date = Date()) -> String {
        guard let d = data(ts) else { return "never" }
        let cal = Calendar.current
        let giorni = cal.dateComponents([.day], from: cal.startOfDay(for: d), to: cal.startOfDay(for: adesso)).day ?? 0
        if giorni == 0 { return "today " + ora24(d) }
        if giorni == 1 { return "yesterday" }
        let c = cal.dateComponents([.day, .month, .year], from: d)
        let base = "\(mesi[(c.month ?? 1) - 1].prefix(3)) \(c.day ?? 0)"
        return c.year == cal.component(.year, from: adesso) ? base : "\(base) \(c.year ?? 0)"
    }


    static func durata(_ secondi: Double?) -> String {
        guard let secondi else { return "" }
        let s = Int(secondi)
        if s < 60 { return "\(s) s" }
        if s < 3600 { return "\(s / 60) min" }
        let h = s / 3600, m = s % 3600 / 60
        if s < 2 * 86400 { return m > 0 ? "\(h) h \(m) min" : "\(h) h" }
        return "\(s / 86400) days"
    }

    static func ora(_ ts: String?) -> String {
        guard let d = data(ts) else { return "" }
        return ora24(d)
    }
}



struct LivelloCopia: Codable, Hashable {
    let tipo: String
    let nome: String
    let quando: String
    let giorni: Double
}

struct GiroCopie: Codable, Hashable {
    let esito: Int?
    let frase: String
    let quando: String?
}

struct Copie: Codable, Hashable {
    let livelli: [LivelloCopia]
    let giro_settimanale: GiroCopie
    let fuori_dal_mac: Bool
    let soglia_giorni: Int
    let salute: String
    let frase: String
}



struct AvvisoLavoro: Codable, Hashable {
    let titolo: String
    let testo: String
}


struct VoceLavoro: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let tipo: String
    let salute: String
    let titolo: String
    let dettaglio: String
    let frase: String

    let chiave_avviso: String
    let avviso: AvvisoLavoro?
    let oggetto: Oggetto
    let azione: Azione?
}

struct Lavori: Codable, Hashable {

    let letto: Bool
    let salute: String
    let frase: String
    let da_guardare: [VoceLavoro]
    let non_collegati: [String]?

    var errori: [VoceLavoro] { da_guardare.filter { $0.salute == "errore" } }
}



struct RisultatoDati: Codable, Hashable {
    let fonte: String
    let nome_fonte: String
    let data: String
    let punteggio: Double
    let contesto: String
    let testo: String
}

struct EsitoCerca: Codable {
    let ok: Bool?
    let risultati: [RisultatoDati]?
    let secondi: Int?
    let errore: String?
}



struct CommitCambiato: Codable, Hashable {
    let hash: String
    let quando: String?
    let messaggio: String
}

struct FileCambiato: Codable, Hashable {
    let file: String
    let quando: String
}

struct CodiceCambiato: Codable, Hashable {
    let commit: [CommitCambiato]
    let file: [FileCambiato]
    let ultimo: String
}




struct Soglia: Codable, Hashable, Identifiable {
    let sezione: String
    let chiave: String

    let tipo: String
    let nome: String
    let unita: String
    let valore: ValoreSoglia
    let partenza: ValoreSoglia
    let minimo: Int?
    let massimo: Int?
    let spiegazione: String
    let cambiata: Bool
    var id: String { "\(sezione).\(chiave)" }

    private enum CodingKeys: String, CodingKey {
        case sezione, chiave, tipo, nome, unita, valore, partenza, minimo, massimo, spiegazione, cambiata
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sezione = try c.decode(String.self, forKey: .sezione)
        chiave = try c.decode(String.self, forKey: .chiave)
        tipo = try c.decode(String.self, forKey: .tipo)
        nome = try c.decode(String.self, forKey: .nome)
        unita = try c.decode(String.self, forKey: .unita)
        if tipo == "acceso" {
            valore = .acceso(try c.decode(Bool.self, forKey: .valore))
            partenza = .acceso(try c.decode(Bool.self, forKey: .partenza))
        } else {
            valore = .numero(try c.decode(Int.self, forKey: .valore))
            partenza = .numero(try c.decode(Int.self, forKey: .partenza))
        }
        minimo = try c.decodeIfPresent(Int.self, forKey: .minimo)
        massimo = try c.decodeIfPresent(Int.self, forKey: .massimo)
        spiegazione = try c.decode(String.self, forKey: .spiegazione)
        cambiata = try c.decode(Bool.self, forKey: .cambiata)
    }
}

enum ValoreSoglia: Codable, Hashable {
    case numero(Int)
    case acceso(Bool)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { self = .acceso(b) } else { self = .numero(try c.decode(Int.self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .numero(let n): try c.encode(n)
        case .acceso(let b): try c.encode(b)
        }
    }

    var numero: Int? { if case .numero(let n) = self { n } else { nil } }
    var acceso: Bool? { if case .acceso(let b) = self { b } else { nil } }

    var testo: String {
        switch self {
        case .numero(let n): String(n)
        case .acceso(let b): b ? "true" : "false"
        }
    }
}

struct EsitoSoglie: Codable {
    let ok: Bool
    let errore: String?
    let soglie: [Soglia]?
}


struct AvanzamentoDrive: Codable, Hashable {
    let tentativo: Int
    let dalle: String
    let casella: String?
    let caselle_prima: Int
    let caselle_tot: Int
    let sezione: String?
    let cartella: String?
    let cartella_n: Int
    let cartelle_tot: Int?
    let file_i: Int?
    let file_n: Int?
    let scaricati: Int
    let invariati: Int
    let saltati: Int
    let indice: Int?
    let vivo: Bool?
    let ultimo_segno_s: Int?
}

struct SchedaDriveDati: Codable, Hashable {
    let ok: Bool
    let soglie: [Soglia]
    let frase: String
    let tentativi: Int
    let caselle: [String]
    let incrementale: String
    let cosa_salta: [String]
    let avanzamento: AvanzamentoDrive?
}

struct PressioneMac: Codable, Hashable {
    let pct: Int?
    let livello: String
    let grado: String?
}

struct SogliaPressione: Codable, Hashable, Identifiable {
    let nome: String
    let pct: Int
    let cosa: String
    var id: String { nome }
}

struct BudgetLavori: Codable, Hashable {
    let job_gb: Double
    let lavori: Int
    let pool_pct: Int
}

struct InterventoGuardiano: Codable, Hashable {
    let quando: String?
    let step: String?
    let perche: String
}

struct Guardiano: Codable, Hashable {
    let pressione: PressioneMac
    let soglie: [SogliaPressione]
    let budget: BudgetLavori?
    let regole: [String]
    let numeri_letti: Bool
    let interventi: [InterventoGuardiano]
    let per_quota: Int
    let per_pericolo: Int
    let proposta: String

    let deciso: Bool?
}

struct Automatismo: Codable, Hashable, Identifiable {
    let nome: String
    let cosa: String
    let quando: String
    let caricato: Bool
    let gira_adesso: Bool
    let ultimo_esito: Int?

    let registro: String?
    let spento_il: String?
    var id: String { nome }
}

struct Strumenti: Codable, Hashable {
    let ok: Bool
    let guardiano: Guardiano
    let automatismi: [Automatismo]
}


struct Disco: Codable, Hashable {
    let libero_gb: Int
    let totale_gb: Int
    let ritmo_gb_ora: Double?
    let ore_alla_fine: Double?
    let salute: String
    let frase: String
}


struct RiassuntoVerifiche: Codable, Hashable {
    let totale: Int
    let con_peso: Int
    let quando: String?
    let frase: String
}


struct Verifiche: Codable, Hashable {
    let ok: Bool
    var totale: Int
    let con_peso: Int?
    var casi: [CasoVerifica]
    let quando: String?
    let frase: String?
}

struct CasoVerifica: Codable, Hashable, Identifiable {
    let id: String
    let fonte: String
    let nome_fonte: String
    let chiave: String
    let nome: String
    let candidati: [CandidatoVerifica]
    let altri_candidati: Int?
    let motivo: String

    let dettagli: String
    let peso: Int
}

struct CandidatoVerifica: Codable, Hashable {
    let email: String
    let nome: String
}



struct VoceStato: Codable, Hashable {
    let parola: String
    let salute: String?
    let simbolo: String?
    let aiuto: String?

    let titolo: String?
}

struct VoceGuida: Codable, Hashable {
    let parola: String
    let salute: String
    let simbolo: String?
    let frase: String
}

struct Guida: Codable, Hashable {
    let titolo: String
    let sottotitolo: String
    let legenda: [VoceGuida]
    let sezioni: String
    let run: String
    let nota: String
}
