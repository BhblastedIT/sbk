import Foundation
import Observation






@MainActor
@Observable
final class PlaudStore {
    static let condiviso = PlaudStore()

    var dati: Plaud?

    var testiSenzaDati: [String: String] = [:]
    var errore: String?
    var inLettura = false

    var modulo = "quadro"
    var cerca = ""
    var soloIndizi = false

    var mostrate = PlaudStore.passo
    static let passo = 50

    @ObservationIgnored private var lettoAlle: Date?

    func t(_ chiave: String) -> String { dati?.testi[chiave] ?? testiSenzaDati[chiave] ?? chiave }



    func carica(_ store: Store, forza: Bool = false) async {
        if dati == nil { caricaCache() }
        guard !inLettura else { return }
        if !forza, dati != nil, let l = lettoAlle, Date().timeIntervalSince(l) < 60 { return }
        inLettura = true
        defer { inLettura = false }
        let r = await store.motore.chiedi(["plaud"], scadenza: 60)
        if let testa = try? JSONDecoder().decode(PlaudTesta.self, from: r.dati) {
            if testa.ok, let nuovo = (try? JSONDecoder().decode(Plaud.self, from: r.dati)) {
                dati = nuovo
                errore = nil
                lettoAlle = Date()
                if !store.modoIstantanea && !Store.senzaCache { salvaCache(r.dati) }
                return
            }
            testiSenzaDati = testa.testi ?? [:]
            errore = testa.errore

            if !r.errori.isEmpty { FileHandle.standardError.write("plaud: \(r.errori.suffix(400))\n".data(using: .utf8)!) }
        }
        if errore == nil && dati == nil {
            errore = "The Plaud measurements cannot be read. The engine did not respond as it should."
            FileHandle.standardError.write("plaud: \(r.errori.suffix(400))\n".data(using: .utf8)!)
        }
    }



    private var fileCache: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("local.sbk.secondbrain", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("ultimo-plaud.json")
    }

    private func caricaCache() {
        guard !Store.senzaCache, let d = try? Data(contentsOf: fileCache),
              let vecchio = try? JSONDecoder().decode(Plaud.self, from: d), vecchio.ok else { return }
        dati = vecchio
    }

    private func salvaCache(_ d: Data) {
        try? d.write(to: fileCache, options: .atomic)
    }


    var righeFiltrate: [RegistrazionePlaud] {
        guard let righe = dati?.da_nominare.righe else { return [] }
        let q = cerca.trimmingCharacters(in: .whitespaces)
        return righe.filter { r in
            (!soloIndizi || r.con_indizi)
                && (q.isEmpty || r.titolo.localizedStandardContains(q) || r.contesto.localizedStandardContains(q)
                    || r.indizi.localizedStandardContains(q) || r.data.localizedStandardContains(q))
        }
    }
}




struct PlaudTesta: Codable {
    let ok: Bool
    let errore: String?
    let testi: [String: String]?
}

struct Plaud: Codable, Hashable {
    let ok: Bool
    let generato: String
    let letto: String
    let obiettivo: ObiettivoPlaud
    let moduli: [ModuloPlaud]
    let numeri: [NumeroPlaud]
    let livelli: [LivelloPlaud]

    let indizi: [IndizioPlaud]?
    let fiducia: [FasciaFiduciaPlaud]?
    let mesi: [MesePlaud]
    let storia: [GiroPlaud]

    let storia_giri: Int?
    let storia_altri: String?
    let da_nominare: DaNominarePlaud
    let fuori: FuoriPlaud
    let perche: PerchePlaud

    let metodo: MetodoPlaud?
    let attivita: [AttivitaPlaud]
    let testi: [String: String]

    func t(_ chiave: String) -> String { testi[chiave] ?? chiave }
}

struct ObiettivoPlaud: Codable, Hashable {
    let frase: String
    let parole_di_owner: String
    let metodo: String
}

struct ModuloPlaud: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let conteggio: String
    let aiuto: String
}

struct NumeroPlaud: Codable, Hashable, Identifiable {
    let id: String
    let cifra: String
    let parola: String
    let aiuto: String

    let segnale: Bool?
}

struct LivelloPlaud: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let minuti: Int
    let voci: Int
    let frazione: Double
    let cifre: String
    let pct: String
    let aiuto: String
}

struct IndizioPlaud: Codable, Hashable, Identifiable {
    let id: String
    let indizio: String
    let perche: String
    let partenza: String
    let giusti: String
    let sbagliati: String
    let peso: String
    let valore: Double
    let verificato: Bool
}

struct FasciaFiduciaPlaud: Codable, Hashable, Identifiable {
    let id: String
    let fascia: String
    let speaker: String
    let frazione: Double

    let livello: Int
}

struct MesePlaud: Codable, Hashable, Identifiable {
    let id: String
    let etichetta: String
    let pct_senza_nome: Double
    let pct_solidi: Double
    let aiuto: String
}

struct GiroPlaud: Codable, Hashable, Identifiable {
    let id: String
    let quando: String
    let senza_nome: String
    let solidi: String
    let sospetti: String
    let verificate: String
    let fuori: String
    let confronto: String
}

struct RegistrazionePlaud: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let data: String
    let durata: String
    let numeri: String
    let contesto: String

    let indizi: String
    let con_indizi: Bool
    let fonte: String
    let link: String

    let una_voce_sola: Bool

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        titolo = try c.decode(String.self, forKey: .titolo)
        data = try c.decode(String.self, forKey: .data)
        durata = try c.decode(String.self, forKey: .durata)
        numeri = try c.decode(String.self, forKey: .numeri)
        contesto = try c.decode(String.self, forKey: .contesto)
        link = try c.decode(String.self, forKey: .link)

        indizi = try c.decodeIfPresent(String.self, forKey: .indizi) ?? ""
        con_indizi = try c.decodeIfPresent(Bool.self, forKey: .con_indizi) ?? false
        fonte = try c.decodeIfPresent(String.self, forKey: .fonte) ?? ""
        una_voce_sola = try c.decodeIfPresent(Bool.self, forKey: .una_voce_sola) ?? false
    }
}


struct GruppoPianoPlaud: Codable, Hashable, Identifiable {
    let id: String
    let gruppo: String
    let come: String
    let voci: String
    let ore: String
}

struct TotalePianoPlaud: Codable, Hashable {
    let voci: String
    let ore: String
}

struct DaNominarePlaud: Codable, Hashable {

    let piano: [GruppoPianoPlaud]?
    let piano_totale: TotalePianoPlaud?
    let totale: Int
    let con_indizi: Int
    let frase: String
    let contesto: String
    let righe: [RegistrazionePlaud]
}

struct FuoriPlaud: Codable, Hashable {
    let numeri: [NumeroPlaud]
    let frase: String
    let righe: [RegistrazionePlaud]
}

struct FattoPlaud: Codable, Hashable {
    let cosa: String
    let prova: String
}

struct PerchePlaud: Codable, Hashable {
    let aggiornato: String
    let in_breve: String
    let fatti: [FattoPlaud]
    let aperto: [String]
    let conseguenza: String
}

struct PassoMetodoPlaud: Codable, Hashable, Identifiable {
    let id: String
    let n: Int
    let passo: String
    let parole: String
    let quando: String
}

struct MetodoPlaud: Codable, Hashable {
    let aggiornato: String
    let in_breve: String
    let passi: [PassoMetodoPlaud]
    let scoperte: [String]
}

struct AttivitaPlaud: Codable, Hashable, Identifiable {
    let id: String
    let n: Int
    let cosa: String
    let stato: String
    let tinta: String
    let quando: String
    let esito: String
}
