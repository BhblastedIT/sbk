import AppKit
import AVFoundation
import ImageIO
import SwiftUI












struct PaginaInspiration: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            if let i = store.inspiration, StrisciaRegistrazione.visibile {
                StrisciaRegistrazione(ispirazione: i)
                Divider()
            }
            Group {
                if let i = store.inspiration {
                    if let id = store.spuntoAperto, let s = (i.voci + i.a_parte).first(where: { $0.id == id }) {
                        SpuntoAperto(ispirazione: i, spunto: s)
                    } else {
                        Bacheca(stato: stato, ispirazione: i)
                    }
                } else if let e = store.erroreInspiration {

                    VStack {
                        Fascia(salute: .attenzione, testo: e, dettaglio: nil) {
                            Button("Retry") { Task { await store.caricaInspiration() } }
                        }
                        .frame(maxWidth: 720)
                        Spacer()
                    }
                    .padding(Spazio.margine)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {

                    SchedeVuote()
                }
            }
        }
        .task { await store.apriInspiration() }
        .task { await store.seguiInspiration() }
        .onDisappear {

            store.fermaEMandaRegistrazione("sezione cambiata")
        }
    }
}



struct Inspiration: Codable, Hashable {
    let ok: Bool
    let fonte: String
    let file: String?
    let cartella: String?
    let aggiornato: String

    let ultima_rilettura: String?
    let scheda_iniziale: String
    let schede: [SchedaInspiration]
    let tipi: [TipoInspiration]
    let progetti: [ProgettoInspiration]

    private let progetti_a_vista: Tollera<[ProgettoInspiration]>?
    var progettiVista: [ProgettoInspiration] { progetti_a_vista?.v ?? progetti }
    let parti: [ParteInspiration]
    let voci: [Spunto]
    let a_parte: [Spunto]
    let domande: [DomandaInspiration]
    let testi: [String: String]

    let fasi: [FaseInspiration]?


    private let passi_menu_motore: Tollera<[PassoMenu]>?
    var passiMenu: [PassoMenu]? { passi_menu_motore?.v.flatMap { $0.isEmpty ? nil : $0 } }



    private let filtri_motore: Tollera<FiltriBacheca>?
    var filtriMotore: FiltriBacheca? { filtri_motore?.v.flatMap { $0.dimensioni.isEmpty ? nil : $0 } }
    private let filtri_pronti_motore: Tollera<[FiltroConNome]>?
    var filtriProntiMotore: [FiltroConNome]? { filtri_pronti_motore?.v }
    private let filtri_salvati_motore: Tollera<[FiltroConNome]>?
    var filtriSalvatiMotore: [FiltroConNome]? { filtri_salvati_motore?.v }


    private let ordina_motore: Tollera<[SceltaFiltri]>?
    var ordinaMotore: [SceltaFiltri]? { ordina_motore?.v.map { $0.filter { !$0.id.isEmpty } }.flatMap { $0.isEmpty ? nil : $0 } }
    private let raggruppa_motore: Tollera<[SceltaFiltri]>?
    var raggruppaMotore: [SceltaFiltri]? {
        raggruppa_motore?.v.map { $0.filter { !$0.id.isEmpty } }.flatMap { $0.isEmpty ? nil : $0 }
    }
    private let filtri_salvati_si_legge: Tollera<Bool>?
    var filtriSalvatiSiLegge: Bool { filtri_salvati_si_legge?.v ?? true }
    let esiti: [EsitoInspiration]?

    let aspettano_te: Int?


    private let aspettano_te_nuovi_motore: Tollera<Int>?
    var aspettano_te_nuovi: Int? { aspettano_te_nuovi_motore?.v }

    let da_capire_visti: Int?

    let ritmo: RitmoInspiration?


    private let testa_motore: TestaInspiration?

    var testa: TestaInspiration? { testa_motore.flatMap { $0.frase.isEmpty ? nil : $0 } }


    private let spunti_frase_motore: Tollera<String>?
    var spuntiFrase: String? { spunti_frase_motore?.v.flatMap { $0.isEmpty ? nil : $0 } }



    private let impostazioni_motore: Tollera<ImpostazioniInspiration>?
    var impostazioni: ImpostazioniInspiration? { impostazioni_motore?.v.flatMap { $0.voci.isEmpty ? nil : $0 } }

    enum CodingKeys: String, CodingKey {
        case ok, fonte, file, cartella, aggiornato, ultima_rilettura, scheda_iniziale, schede, tipi, progetti, progetti_a_vista, parti, voci,
             a_parte, domande, testi, fasi, esiti, aspettano_te, da_capire_visti, ritmo
        case aspettano_te_nuovi_motore = "aspettano_te_nuovi"
        case passi_menu_motore = "passi_menu"
        case filtri_motore = "filtri", filtri_pronti_motore = "filtri_pronti", filtri_salvati_motore = "filtri_salvati"
        case ordina_motore = "ordina", raggruppa_motore = "raggruppa", filtri_salvati_si_legge
        case testa_motore = "testa"
        case spunti_frase_motore = "spunti_frase"
        case impostazioni_motore = "impostazioni"
    }


    func t(_ chiave: String, _ valori: [String: String] = [:], o altrimenti: String? = nil) -> String {
        var testo = testi[chiave] ?? altrimenti ?? chiave
        for (k, v) in valori { testo = testo.replacingOccurrences(of: "{\(k)}", with: v) }
        return testo
    }
}



struct PassoMenu: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let n: Int
    let per_te: Int
    let frase: String
    let vuota: String
    let staccata: Bool


    let per_te_frase: String
    let etichetta: String

    enum CodingKeys: String, CodingKey { case id, nome, n, per_te, frase, vuota, staccata, per_te_frase, etichetta }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        nome = p.testo(.nome)
        n = p.numero(.n) ?? 0
        per_te = p.numero(.per_te) ?? 0
        frase = p.testo(.frase)
        vuota = p.testo(.vuota)
        staccata = p.si(.staccata)
        per_te_frase = p.testo(.per_te_frase)
        etichetta = p.testo(.etichetta)
    }
}

struct SchedaInspiration: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let n: Int
    let aiuto: String
    let vuota: String
}

struct TipoInspiration: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let simbolo: String
    let n: Int

    let plurale: String?
}

struct ProgettoInspiration: Codable, Hashable {
    let nome: String
    let id: String
    let n: Int
}

struct ParteInspiration: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let frase: String
}

struct Spunto: Codable, Hashable, Identifiable {
    let id: String
    let tipo: String
    let nome_tipo: String
    let simbolo: String

    let forma: String
    let piattaforma: String
    let titolo: String
    let sotto: String
    let quando: String
    let progetto: String
    let scheda: String

    let parte: String
    let visto: Bool
    let badge: SegnoSpunto?
    let frase_owner: String

    let frase_audio: String?
    let copertina: String?
    let video: String?
    let trascrizione: String?
    let url: String
    let permalink: String
    let ricerca: String
    let dettaglio: DettaglioSpunto
    let a_parte: Bool?

    let fase: String?
    let tocca: String?
    let lavorazione: Lavorazione?


    let segno: SegnoScheda?

    let contenuto_salute: String?

    let titolo_sono_parole: Bool?


    let progetto_a_vista: Tollera<String>?
    var progettoVista: String { progetto_a_vista?.v ?? progetto }

    let passo: Tollera<String>?
    let per_te: Tollera<Bool>?


    let passo_menu: Tollera<String>?
    var passoVoce: String { passo_menu?.v ?? passo?.v ?? lavorazione?.passoAcceso ?? "" }



    let anteprima_titolo: Tollera<String>?
    let anteprima_autore: Tollera<String>?
    var anteprimaTitolo: String { (anteprima_titolo?.v ?? "").trimmingCharacters(in: .whitespacesAndNewlines) }
    var haAnteprima: Bool { !anteprimaTitolo.isEmpty }



    let faccette: ScelteFiltri?
    let filtro: ScelteFiltri?
    var faccetteMotore: [String: [String]] { faccette?.v ?? filtro?.v ?? [:] }



    let proposto_quando: Tollera<String>?
    let ultimo_gesto_quando: Tollera<String>?
    let autore: Tollera<String>?
    var propostoQuando: String { proposto_quando?.v ?? "" }
    var ultimoGestoQuando: String { ultimo_gesto_quando?.v ?? "" }
}


struct TestaInspiration: Codable, Hashable {
    let frase: String

    let salute: String?

    let avanzamento: String?

    let pulsante: String?

    let pulsante_verbo: String?
    let pulsante_aiuto: String?
    let dettagli: [GruppoDettagli]?
    let dettagli_parola: String?
    let rileggi_parola: String?


    let righe: [RigaTesta]



    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        frase = (try? c?.decodeIfPresent(String.self, forKey: .frase)) ?? ""
        salute = try? c?.decodeIfPresent(String.self, forKey: .salute)
        avanzamento = try? c?.decodeIfPresent(String.self, forKey: .avanzamento)
        pulsante = try? c?.decodeIfPresent(String.self, forKey: .pulsante)
        pulsante_verbo = try? c?.decodeIfPresent(String.self, forKey: .pulsante_verbo)
        pulsante_aiuto = try? c?.decodeIfPresent(String.self, forKey: .pulsante_aiuto)
        dettagli = try? c?.decodeIfPresent([GruppoDettagli].self, forKey: .dettagli)
        dettagli_parola = try? c?.decodeIfPresent(String.self, forKey: .dettagli_parola)
        rileggi_parola = try? c?.decodeIfPresent(String.self, forKey: .rileggi_parola)
        righe = (try? c?.decodeIfPresent([RigaTesta].self, forKey: .righe)) ?? []
    }


    var righeTesta: [RigaTesta]? {
        var viste = Set<String>()
        let buone = righe.filter { !$0.frase.isEmpty && viste.insert($0.id).inserted }
        return buone.isEmpty ? nil : buone
    }
}






struct RigaTesta: Codable, Hashable, Identifiable {
    let id: String
    let frase: String
    let pulsante: String
    let pulsante_verbo: String
    let pulsante_aiuto: String
    let vista: String
    let gettone: String
    let sotto: String
    let ids: [String]
    let avanzamento: String

    enum CodingKeys: String, CodingKey {
        case id, frase, pulsante, pulsante_verbo, pulsante_aiuto, vista, gettone, sotto, ids, avanzamento
    }

    init(from decoder: Decoder) throws {
        let p = Pezzi(decoder, CodingKeys.self)
        id = p.testo(.id)
        frase = p.testo(.frase)
        pulsante = p.testo(.pulsante)
        pulsante_verbo = p.testo(.pulsante_verbo)
        pulsante_aiuto = p.testo(.pulsante_aiuto)
        vista = p.testo(.vista)
        gettone = p.testo(.gettone)
        sotto = p.testo(.sotto)
        ids = (p.elenco(.ids) as [String]).filter { !$0.isEmpty }
        avanzamento = p.testo(.avanzamento)
    }


    var alMotore: Bool { vista.isEmpty && !pulsante.isEmpty && !pulsante_verbo.isEmpty }

    var eVista: Bool { !vista.isEmpty && !pulsante.isEmpty }
}

struct GruppoDettagli: Codable, Hashable {
    let titolo: String
    let righe: [String]

    let pulsante: String?
    let pulsante_verbo: String?
    let pulsante_aiuto: String?

    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        titolo = (try? c?.decodeIfPresent(String.self, forKey: .titolo)) ?? ""
        righe = (try? c?.decodeIfPresent([String].self, forKey: .righe)) ?? []
        pulsante = try? c?.decodeIfPresent(String.self, forKey: .pulsante)
        pulsante_verbo = try? c?.decodeIfPresent(String.self, forKey: .pulsante_verbo)
        pulsante_aiuto = try? c?.decodeIfPresent(String.self, forKey: .pulsante_aiuto)
    }
}


struct SegnoScheda: Codable, Hashable {
    let tipo: String
    let parola: String
    let aiuto: String?

    let salute: String?
    let passo: Int?
    let passi: Int?
    let posto_in_fila: Int?



    let domanda: String
    let domanda_corta: String
    let accanto: String


    var aVista: Bool { !tipo.isEmpty && !parola.isEmpty }


    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        tipo = (try? c?.decodeIfPresent(String.self, forKey: .tipo)) ?? ""
        parola = (try? c?.decodeIfPresent(String.self, forKey: .parola)) ?? ""
        aiuto = try? c?.decodeIfPresent(String.self, forKey: .aiuto)
        salute = try? c?.decodeIfPresent(String.self, forKey: .salute)
        passo = try? c?.decodeIfPresent(Int.self, forKey: .passo)
        passi = try? c?.decodeIfPresent(Int.self, forKey: .passi)
        posto_in_fila = try? c?.decodeIfPresent(Int.self, forKey: .posto_in_fila)
        domanda = (try? c?.decodeIfPresent(String.self, forKey: .domanda)) ?? ""
        domanda_corta = (try? c?.decodeIfPresent(String.self, forKey: .domanda_corta)) ?? ""
        accanto = (try? c?.decodeIfPresent(String.self, forKey: .accanto)) ?? ""
    }
}



struct RitmoInspiration: Codable, Hashable {
    let acceso: Bool
    let frase: String
    let righe: [String]?
    let in_corso: [String]?
    let fermi: [String]?


    let pulsante: String?
    let pulsante_aiuto: String?
}

struct SegnoSpunto: Codable, Hashable {
    let parola: String
    let salute: String
    let aiuto: String
}

struct DettaglioSpunto: Codable, Hashable {
    let testa: String
    let destinazione: String
    let contenuto: String
    let online: String
    let parole_owner: [ParolaDiOwner]

    let audio_owner: [AudioDiOwner]?
    let promette: String
    let realizzato: String
    let simili: [CosaSimile]
    let dalla_didascalia: Bool
    let domande: [String]
    let storia: [PassoStoria]

    let nessuna_parola_vale: Bool?
}

struct ParolaDiOwner: Codable, Hashable {
    let testo: String
    let quando: String

    let audio: String?

    var fileAudio: String? { (audio?.isEmpty == false) ? audio : nil }
}

struct AudioDiOwner: Codable, Hashable {
    let frase: String
    let quando: String
    let permalink: String
    let audio: String?
}

struct CosaSimile: Codable, Hashable {
    let nome: String
    let url: String
    let perche: String
}

struct PassoStoria: Codable, Hashable {
    let quando: String
    let cosa: String
}

struct DomandaInspiration: Codable, Hashable {
    let testo: String
    let voci: [String]
}



struct Bacheca: View {
    let stato: Stato
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        let i = ispirazione
        let scheda = Self.selezione(i, store: store)



        let quadro = QuadroFiltri.di(i)
        let base = Self.base(i.voci, store: store, scheda: scheda, ispirazione: i)
        let scelti = Self.inFila(base, store: store, ispirazione: i, quadro: quadro)


        let righe = i.testa?.righeTesta
        let env = ProcessInfo.processInfo.environment
        ScrollViewReader { lente in
            ScrollView {
                VStack(alignment: .leading, spacing: Spazio.griglia) {
                    Fasce(stato: stato)
                    if let testa = i.testa, let righe {




                        TitoloBacheca(testa: testa, righe: righe, ispirazione: i)
                        let altre = righe.filter { !$0.voceCorta }
                        if !altre.isEmpty || store.erroreGesto != nil {
                            RigheTesta(righe: altre, ispirazione: i)
                        }
                    } else {

                    HStack(alignment: .firstTextBaseline, spacing: 10) {

                        Text(i.t("titolo")).font(.system(size: 26, weight: .bold))
                            .fixedSize(horizontal: i.testa != nil, vertical: false)

                        Text(i.spuntiFrase ?? "\(i.voci.count)").font(.title2).foregroundStyle(.secondary).monospacedDigit()
                            .fixedSize(horizontal: i.testa != nil, vertical: false)
                        if let testa = i.testa {


                            RigaStatoBacheca(testa: testa, ispirazione: i)
                                .padding(.leading, 14)

                                .layoutPriority(1)
                            Spacer(minLength: Spazio.fratelli)
                        } else {
                            Spacer(minLength: Spazio.fratelli)

                            let righe = [i.aggiornato, i.ultima_rilettura ?? ""].filter { !$0.isEmpty }
                            if !righe.isEmpty {
                                Text(righe.joined(separator: " · ")).font(Testo.minimo).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                        if store.inspirationInLettura || store.riletturaInCorso {
                            ProgressView().controlSize(.small)
                                .help(store.riletturaInCorso ? i.t("rilettura_in_corso") : "")
                        }
                        if i.testa == nil {

                            Button(i.t("rileggi")) { Task { await store.rileggiInspiration() } }
                                .disabled(store.riletturaInCorso)
                                .help(i.t("aiuto_rileggi"))
                        }
                        TextField(i.t("cerca"), text: $store.cercaInspiration)
                            .textFieldStyle(.roundedBorder)
                            .frame(minWidth: i.testa == nil ? nil : 150, maxWidth: 240)
                        MenuPaginaOnline(ispirazione: i)
                    }
                    }

                    if store.modoIstantanea, let testa = i.testa, env["SB_DETTAGLI"] == "1" {
                        PopoverDettagli(testa: testa, ispirazione: i, verbiInRighe: righe.map(Self.verbi))
                            .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
                    }

                    if i.testa == nil, let e = store.erroreGesto {
                        RigaErroreGesto(errore: e, ispirazione: i)
                    }
                    if store.inspirationNonRiletta {
                        FasciaRilettura(ispirazione: i)
                    }


                    if let esito = store.riletturaInspiration, i.testa == nil || !esito.ok {
                        FasciaRiletturaDM(ispirazione: i, esito: esito)
                    }



                    if let r = i.ritmo, i.testa == nil {
                        RigaRitmo(ritmo: r)
                    }




                    BarraFiltri(ispirazione: i, scheda: scheda, quadro: quadro, base: base, conRicerca: i.testa != nil && righe != nil)
                        .padding(.top, 4)
                    if Self.filtriAccesi(store) {
                        GettoniFiltri(ispirazione: i, quadro: quadro, restano: scelti.count)
                    }


                    if store.modoIstantanea, env["SB_MENU_FILTRI"] == "1" {
                        MenuFiltriInPagina(ispirazione: i, quadro: quadro, base: base)
                    }
                    if store.modoIstantanea, store.chiediNomeFiltroInspiration {
                        FoglioSalvaFiltro(ispirazione: i, quadro: quadro, nellaPagina: true)
                            .background(Superficie.scheda, in: RoundedRectangle(cornerRadius: Raggio.riquadro))
                            .overlay(RoundedRectangle(cornerRadius: Raggio.riquadro).strokeBorder(Superficie.separatore))
                    }

                    if let passi = i.passiMenu {
                        if scheda != "tutti", let p = passi.first(where: { $0.id == scheda }), !p.frase.isEmpty {
                            Text(p.frase).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    } else if scheda != "tutti", let f = i.fasi?.first(where: { $0.id == scheda }) {
                        Text(f.frase ?? f.aiuto).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    } else if scheda != "tutti", i.fasi == nil, let s = i.schede.first(where: { $0.id == scheda }) {
                        Text(s.aiuto).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    contenuto(i, scheda: scheda, scelti: scelti, quadro: quadro)
                }
                .padding(.horizontal, 28)
                .padding(.top, 18)
                .padding(.bottom, 28)
                .frame(maxWidth: 1400, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onAppear {
                if store.modoIstantanea { Self.filtriDaIstantanea(store, i) }

                if store.modoIstantanea, let e = env["SB_ERRORE_GESTO"] {
                    if env["SB_ERRORE_AVVISO"] == "1" { EsitoAzione.avvisi.insert(e) }
                    store.erroreGesto = e
                }


                if store.modoIstantanea, let v = env["SB_VISTA_SPUNTI"] {
                    store.vistaInspiration = v
                }
                store.notiziaDaIstantanea()

                if let id = store.ultimoSpuntoChiuso {
                    store.ultimoSpuntoChiuso = nil
                    DispatchQueue.main.async { lente.scrollTo(id, anchor: .center) }
                }
            }
        }

        .sheet(isPresented: Binding(get: { store.chiediNomeFiltroInspiration && !store.modoIstantanea },
                                    set: { store.chiediNomeFiltroInspiration = $0 })) {
            FoglioSalvaFiltro(ispirazione: i, quadro: quadro)
                .environment(store)
        }
    }





    static func filtriDaIstantanea(_ store: Store, _ i: Inspiration) {
        let env = ProcessInfo.processInfo.environment
        if let id = env["SB_FILTRO_PRONTO"], let p = QuadroFiltri.di(i).pronti.first(where: { $0.id == id }) {
            store.applicaFiltroInspiration(p.filtro)
        }
        if let p = env["SB_PASSO"] { store.faseInspiration = p }
        if let o = env["SB_ORDINE"] { store.ordineInspiration = o }
        if let fs = env["SB_FILTRI"] {
            for pezzo in fs.split(separator: ";") {
                let kv = pezzo.split(separator: "=", maxSplits: 1).map(String.init)
                if kv.count == 2 { store.filtroInspiration.scelte[kv[0]] = kv[1].split(separator: ",").map(String.init) }
            }
        }
        if let g = env["SB_GRUPPO"] { store.filtroInspiration.gruppo = g }
        if let a = env["SB_PANNELLO_FILTRI"] { store.pannelloFiltriInspiration = a == "1" }
        if let q = env["SB_CERCA_SPUNTI"] { store.cercaInspiration = q }

        if env["SB_TOGLI_FILTRI"] == "1" { store.togliFiltriInspiration() }
        if env["SB_SALVA_FILTRO"] == "1" { store.chiediNomeFiltroInspiration = true }


        if let n = env["SB_SALVA_FILTRO_NOME"] { Task { await store.salvaFiltroInspiration(n) } }
        if let n = env["SB_TOGLI_FILTRO_NOME"] { Task { await store.togliFiltroSalvatoInspiration(n) } }
    }


    static func filtriAccesi(_ store: Store) -> Bool {
        store.vistaInspiration != nil || !store.filtroInspiration.senzaScelte
            || !store.cercaInspiration.trimmingCharacters(in: .whitespaces).isEmpty
    }


    static func testoPillola(_ f: FaseInspiration, _ i: Inspiration) -> String {
        var testo = f.nome
        if f.n > 0 { testo += " \(f.n)" }
        if f.aspettano_te > 0, f.aspettano_te != f.n {
            testo += " · " + i.t("per_te", ["n": "\(f.aspettano_te)"], o: i.t("aspettano_te", ["n": "\(f.aspettano_te)"]))
        }
        return testo
    }

    @ViewBuilder
    private func contenuto(_ i: Inspiration, scheda: String, scelti: [Spunto], quadro: QuadroFiltri) -> some View {
        let f = store.filtroInspiration

        let altri = !f.dimensioniScelte.filter(quadro.conosce).isEmpty || Self.idsVista(i, store: store) != nil
            || !store.cercaInspiration.trimmingCharacters(in: .whitespaces).isEmpty
        let gruppi = f.gruppo == FiltroSpunti.gruppoPartenza ? [] : quadro.raggruppa(scelti, f.gruppo, i)
        if i.voci.isEmpty {
            VStack(spacing: 10) {
                Image(systemName: Sezione.inspiration.simbolo).font(.system(size: 44)).foregroundStyle(.secondary)
                Text(i.t("vuota")).font(.title3.weight(.semibold))
                Text(i.t("vuota_come")).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 60)
        } else if scelti.isEmpty && altri {
            VStack(spacing: 10) {
                Text(i.t("nessuno_coi_filtri")).foregroundStyle(.secondary)

                Button(i.t("togli_filtri")) { store.togliFiltriInspiration() }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 40)
        } else if scelti.isEmpty {


            VStack(spacing: 10) {
                Text(i.passiMenu.flatMap { ps in ps.first { $0.id == scheda }?.vuota }
                    ?? i.schede.first { $0.id == scheda }?.vuota
                    ?? i.fasi?.first { $0.id == scheda }.map { $0.vuota ?? $0.aiuto } ?? "")
                    .foregroundStyle(.secondary)
                if scheda != "tutti" {
                    Button(i.t("togli_filtri")) { store.togliFiltriInspiration() }
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 40)
        } else if !gruppi.isEmpty {


            VStack(alignment: .leading, spacing: 12) {
                ForEach(gruppi, id: \.id) { g in
                    Text("\(g.nome)  \(g.voci.count)").font(Testo.titoloGruppo).foregroundStyle(.secondary)
                        .padding(.top, 6)
                    GrigliaSpunti(voci: g.voci, ispirazione: i)
                }
            }
            .padding(.top, 4)
        } else {
            GrigliaSpunti(voci: scelti, ispirazione: i)
                .padding(.top, 4)
        }

        if scheda == "tutti", !i.a_parte.isEmpty, !altri {
            @Bindable var store = store
            DisclosureGroup(isExpanded: $store.aParteAperta) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(i.t("a_parte_frase")).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    GrigliaSpunti(voci: i.a_parte, ispirazione: i)
                }
                .padding(.top, 8)
            } label: {
                TitoloGruppo(titolo: i.t("a_parte"), conteggio: "\(i.a_parte.count)")
            }
            .padding(.top, 12)
        }
    }



    static func selezione(_ i: Inspiration, store: Store) -> String {


        if let passi = i.passiMenu {
            let f = store.faseInspiration ?? "tutti"
            return passi.contains { $0.id == f } ? f : "tutti"
        }
        if i.fasi != nil {
            return store.faseInspiration ?? "tutti"
        }
        return store.schedaInspiration ?? "tutti"
    }



    static func base(_ voci: [Spunto], store: Store, scheda: String, ispirazione: Inspiration) -> [Spunto] {
        let q = store.cercaInspiration.trimmingCharacters(in: .whitespaces)
        let perFase = ispirazione.fasi != nil
        let perPasso = ispirazione.passiMenu != nil

        let vista = idsVista(ispirazione, store: store)
        return voci.filter { s in
            (vista.map { $0.contains(s.id) } ?? true)
                && (perPasso || scheda == "tutti" || (perFase ? s.fase == scheda : s.scheda == scheda))
                && (q.isEmpty || s.ricerca.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil)
        }
    }



    static func inFila(_ base: [Spunto], store: Store, ispirazione i: Inspiration, quadro: QuadroFiltri) -> [Spunto] {
        let f = store.filtroInspiration

        let tranne: String? = i.passiMenu == nil ? FiltroSpunti.passo : nil

        let ordinati = quadro.ordina(base.filter { quadro.passa($0, f, tranne: tranne) }, f.ordine)
        if f.gruppo != FiltroSpunti.gruppoPartenza {
            let g = quadro.raggruppa(ordinati, f.gruppo, i)
            if !g.isEmpty { return g.flatMap(\.voci) }
        }
        return ordinati
    }


    static func filtra(_ voci: [Spunto], store: Store, scheda: String, ispirazione: Inspiration) -> [Spunto] {
        inFila(base(voci, store: store, scheda: scheda, ispirazione: ispirazione), store: store, ispirazione: ispirazione,
               quadro: QuadroFiltri.di(ispirazione))
    }



    static func idsVista(_ i: Inspiration, store: Store) -> Set<String>? {
        guard let v = store.vistaInspiration, !v.isEmpty,
              let r = i.testa?.righeTesta?.first(where: { $0.vista == v }) else { return nil }
        return Set(r.ids)
    }


    static func verbi(_ righe: [RigaTesta]) -> Set<String> {
        Set(righe.filter(\.alMotore).map(\.pulsante_verbo))
    }
}


struct FasciaRilettura: View {
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        Fascia(salute: .attenzione,
               testo: store.oraInspiration.map { i.t("errore", ["ora": $0]) } ?? i.t("errore_senza_ora"),
               dettaglio: nil) {
            Button(i.t("riprova")) { Task { await store.caricaInspiration() } }
        }
    }
}



struct RigaRitmo: View {
    let ritmo: RitmoInspiration
    @Environment(Store.self) private var store

    var body: some View {
        let righe = (ritmo.righe ?? []).filter { !$0.isEmpty }
        HStack(alignment: .top, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: ritmo.acceso ? "clock.arrow.2.circlepath" : "clock.badge.xmark")
                    .foregroundStyle(ritmo.acceso ? Color.accentColor : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(ritmo.frase)
                    ForEach(righe, id: \.self) { r in
                        Text(r)
                    }
                }
            }
            .font(Testo.minimo)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .combine)

            if let p = ritmo.pulsante, !p.isEmpty {
                Spacer(minLength: 0)
                Button(p) {
                    Task {
                        if let e = await store.azioneInspiration(["capisci", "tutte"]) { store.erroreGesto = e }
                    }
                }
                .buttonStyle(.borderedProminent)
                .help(ritmo.pulsante_aiuto ?? "")
            }
        }
    }
}




struct RigaStatoBacheca: View {
    let testa: TestaInspiration
    let ispirazione: Inspiration
    @Environment(Store.self) private var store
    @State private var dettagliAperti = false
    @State private var inCorso = false

    var body: some View {
        let t = testa
        let salute = t.salute ?? "ok"
        HStack(alignment: .center, spacing: 8) {
            if salute == "attenzione" {
                Image(systemName: Salute.attenzione.simbolo).foregroundStyle(Salute.attenzione.colore)
            } else if salute == "in_corso" {
                ProgressView().controlSize(.mini)
            }


            if let e = store.erroreGesto {
                RigaErroreGesto(errore: e, ispirazione: ispirazione)
            } else {

                Text(t.frase)
                    .font(Testo.corpo)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let p = t.pulsante, !p.isEmpty {
                Button(p) { Task { await premi() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(inCorso || store.riletturaInCorso)
                    .help(t.pulsante_aiuto ?? "")
                    .fixedSize()
            }
            Button {
                dettagliAperti.toggle()
            } label: {
                Label(t.dettagli_parola ?? ispirazione.t("dettagli"), systemImage: "chevron.right")
                    .labelStyle(TitoloPoiSimbolo())
            }
            .buttonStyle(.link)
            .fixedSize()
            .popover(isPresented: $dettagliAperti, arrowEdge: .bottom) {
                PopoverDettagli(testa: t, ispirazione: ispirazione)
            }
        }
    }


    private func premi() async {
        let verbo = (testa.pulsante_verbo ?? "").split(separator: " ").map(String.init)
        inCorso = true
        defer { inCorso = false }
        if verbo == ["rileggi"] {
            await store.rileggiInspiration()
        } else if !verbo.isEmpty {
            if let e = await store.azioneInspiration(verbo) { store.erroreGesto = e }
        }
    }
}




struct TitoloBacheca: View {
    let testa: TestaInspiration
    let righe: [RigaTesta]
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {
        let viste = righe.filter(\.voceCorta)
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                titolo
                if !viste.isEmpty { VociVista(righe: viste, ispirazione: ispirazione).padding(.leading, 6) }
                Spacer(minLength: Spazio.fratelli)
                coda
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    titolo
                    Spacer(minLength: Spazio.fratelli)
                    coda
                }
                if !viste.isEmpty { VociVista(righe: viste, ispirazione: ispirazione) }
            }
        }
    }

    @ViewBuilder
    private var titolo: some View {
        let i = ispirazione
        Text(i.t("titolo")).font(.system(size: 26, weight: .bold)).fixedSize()

        Text(i.spuntiFrase ?? "\(i.voci.count)").font(.title2).foregroundStyle(.secondary).monospacedDigit().fixedSize()

        LinkDettagli(testa: testa, ispirazione: i, verbiInRighe: Bacheca.verbi(righe))
            .padding(.leading, 8)
    }

    @ViewBuilder
    private var coda: some View {


        let legge = store.inspirationInLettura || store.riletturaInCorso
        ProgressView().controlSize(.small)
            .opacity(legge ? 1 : 0)
            .accessibilityHidden(!legge)
            .help(store.riletturaInCorso ? ispirazione.t("rilettura_in_corso") : "")
        MenuPaginaOnline(ispirazione: ispirazione)
    }
}




struct VociVista: View {
    let righe: [RigaTesta]
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {

        let conNuovi = righe.contains { $0.vista == "nuovi" }
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            ForEach(Array(righe.enumerated()), id: \.element.id) { k, r in
                if k > 0 { Text("·").foregroundStyle(.secondary) }
                let accesa = store.vistaInspiration == r.vista
                Button {
                    if accesa {
                        store.vistaInspiration = nil
                    } else {
                        store.vistaInspiration = r.vista
                        store.faseInspiration = nil
                    }
                } label: {
                    Text(Self.etichetta(ispirazione, r, conNuovi: conNuovi)).fontWeight(accesa ? .semibold : .regular)
                }
                .buttonStyle(.link)
                .fixedSize()
                .help(aiuto(r, accesa: accesa))
            }
        }
    }

    private func aiuto(_ r: RigaTesta, accesa: Bool) -> String {
        let torna = ispirazione.testi["testa_mostra_tutti"].flatMap { $0.isEmpty ? nil : $0 } ?? "Show them all"
        return [r.frase, accesa ? torna : r.pulsante_aiuto].filter { !$0.isEmpty }.joined(separator: ". ")
    }






    static func etichetta(_ i: Inspiration, _ r: RigaTesta, conNuovi: Bool = true) -> String {
        let n = r.ids.count
        let (chiave, ripiego): (String, String)
        switch r.vista {
        case "nuovi": (chiave, ripiego) = n == 1 ? ("testa_voce_nuovi_uno", "{n} new to confirm") : ("testa_voce_nuovi", "{n} new to confirm")
        case "di_prima" where conNuovi:
            (chiave, ripiego) = n == 1 ? ("testa_voce_di_prima_uno", "one more proposed earlier") : ("testa_voce_di_prima", "{n} more proposed earlier")
        case "di_prima":
            (chiave, ripiego) = n == 1 ? ("testa_voce_di_prima_sola_uno", "{n} to confirm, proposed earlier")
                                       : ("testa_voce_di_prima_sola", "{n} to confirm, proposed earlier")
        default: return r.frase
        }
        let testo = i.testi[chiave].flatMap { $0.isEmpty ? nil : $0 } ?? ripiego
        return testo.replacingOccurrences(of: "{n}", with: "\(n)")
    }
}

extension RigaTesta {


    var voceCorta: Bool { eVista && sotto.isEmpty }
}





struct RigheTesta: View {
    let righe: [RigaTesta]
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {


        let pieno = righe.first(where: \.alMotore)?.id
        VStack(alignment: .leading, spacing: 8) {
            if let e = store.erroreGesto {
                RigaErroreGesto(errore: e, ispirazione: ispirazione)
            }
            ForEach(righe) { r in
                RigaTestaBacheca(riga: r, pieno: r.id == pieno, ispirazione: ispirazione)
            }
        }
    }
}




struct RigaTestaBacheca: View {
    let riga: RigaTesta
    let pieno: Bool
    let ispirazione: Inspiration
    @Environment(Store.self) private var store
    @State private var inCorso = false

    var body: some View {
        let r = riga
        let accesa = r.eVista && store.vistaInspiration == r.vista
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                segno


                Text(r.frase)
                    .font(accesa ? Testo.nome : Testo.corpo)
                    .fixedSize(horizontal: false, vertical: true)
                gesto(r, accesa: accesa)
            }
            if !r.sotto.isEmpty {
                Text(r.sotto)
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, conSegno ? Spazio.colonnaSimbolo + 8 : 0)
            }
        }
    }

    private var conSegno: Bool { riga.id == "dm" || riga.id == "moto" }

    @ViewBuilder
    private var segno: some View {
        switch riga.id {
        case "dm":
            Image(systemName: Salute.attenzione.simbolo).foregroundStyle(Salute.attenzione.colore)
                .frame(width: Spazio.colonnaSimbolo)
        case "moto":
            ProgressView().controlSize(.mini).frame(width: Spazio.colonnaSimbolo)
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private func gesto(_ r: RigaTesta, accesa: Bool) -> some View {
        if r.eVista {


            Button(accesa ? tornaATutti : r.pulsante) {
                if accesa {
                    store.vistaInspiration = nil
                } else {
                    store.vistaInspiration = r.vista
                    store.faseInspiration = nil
                }
            }
            .buttonStyle(.link)
            .fixedSize()
            .help(r.pulsante_aiuto)
        } else if r.alMotore {
            if pieno {
                Button(r.pulsante) { Task { await premi(r) } }
                    .buttonStyle(.borderedProminent)
                    .disabled(inCorso || store.riletturaInCorso)
                    .help(r.pulsante_aiuto)
                    .fixedSize()
            } else {
                Button(r.pulsante) { Task { await premi(r) } }
                    .disabled(inCorso || store.riletturaInCorso)
                    .help(r.pulsante_aiuto)
                    .fixedSize()
            }
        }
    }



    private var tornaATutti: String {
        ispirazione.testi["testa_mostra_tutti"].flatMap { $0.isEmpty ? nil : $0 } ?? "Show them all"
    }


    private func premi(_ r: RigaTesta) async {
        let verbo = r.pulsante_verbo.split(separator: " ").map(String.init)
        inCorso = true
        defer { inCorso = false }
        if verbo == ["rileggi"] {
            await store.rileggiInspiration()
        } else if !verbo.isEmpty {
            if let e = await store.azioneInspiration(verbo) { store.erroreGesto = e }
        }
    }
}



struct LinkDettagli: View {
    let testa: TestaInspiration
    let ispirazione: Inspiration
    let verbiInRighe: Set<String>
    @State private var aperti = false

    var body: some View {
        Button {
            aperti.toggle()
        } label: {
            Label(testa.dettagli_parola ?? ispirazione.t("dettagli"), systemImage: "chevron.right")
                .labelStyle(TitoloPoiSimbolo())
        }
        .buttonStyle(.link)
        .fixedSize()
        .popover(isPresented: $aperti, arrowEdge: .bottom) {
            PopoverDettagli(testa: testa, ispirazione: ispirazione, verbiInRighe: verbiInRighe)
        }
    }
}



struct RigaErroreGesto: View {
    let errore: String
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {
        let avviso = EsitoAzione.eAvviso(errore)
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: avviso ? "info.circle" : Salute.attenzione.simbolo)
                .foregroundStyle(avviso ? Color.secondary : Salute.attenzione.colore)
            Text(errore)
                .font(Testo.corpo)
                .foregroundStyle(avviso ? Color.secondary : Color.primary)
                .fixedSize(horizontal: false, vertical: true)
            Button(ispirazione.t("chiudi")) { store.erroreGesto = nil }
                .buttonStyle(.link)
                .fixedSize()
        }
    }
}


struct TitoloPoiSimbolo: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 3) {
            configuration.icon.font(.caption2.weight(.semibold))
            configuration.title
        }
    }
}



struct PopoverDettagli: View {
    let testa: TestaInspiration
    let ispirazione: Inspiration


    var verbiInRighe: Set<String>? = nil
    @Environment(Store.self) private var store


    private func giaInTesta(_ verbo: String) -> Bool {
        if let v = verbiInRighe { return v.contains(verbo) }
        return testa.pulsante?.isEmpty == false && testa.pulsante_verbo == verbo
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array((testa.dettagli ?? []).enumerated()), id: \.offset) { _, g in
                VStack(alignment: .leading, spacing: 3) {
                    if !g.titolo.isEmpty {
                        Text(g.titolo).font(Testo.titoloGruppo)
                    }
                    ForEach(Array(g.righe.enumerated()), id: \.offset) { _, r in
                        Text(r).font(Testo.secondario)
                            .foregroundStyle(g.titolo.isEmpty ? Color.secondary : Color.primary)
                            .fixedSize(horizontal: false, vertical: true)
                    }


                    if let p = g.pulsante, !p.isEmpty, let v = g.pulsante_verbo, !v.isEmpty, !giaInTesta(v) {
                        Button(p) {
                            Task {
                                let verbo = v.split(separator: " ").map(String.init)
                                if let e = await store.azioneInspiration(verbo) { store.erroreGesto = e }
                            }
                        }
                        .help(g.pulsante_aiuto ?? "")
                        .padding(.top, 4)
                    }
                }
            }


            if verbiInRighe.map({ !$0.contains("rileggi") }) ?? (testa.pulsante_verbo != "rileggi") {
                Divider()
                HStack(spacing: 8) {
                    Button(testa.rileggi_parola ?? ispirazione.t("rileggi")) { Task { await store.rileggiInspiration() } }
                        .disabled(store.riletturaInCorso)
                        .help(ispirazione.t("aiuto_rileggi"))
                    if store.riletturaInCorso {
                        ProgressView().controlSize(.small)
                    }
                }
            }
        }
        .padding(16)
        .frame(width: 480, alignment: .leading)
    }
}


struct Rilettura: Codable, Hashable {
    let ok: Bool
    let messaggio: String?
    let frase: String?
    let dettaglio: [String]?
}

struct FasciaRiletturaDM: View {
    let ispirazione: Inspiration
    let esito: Rilettura
    @Environment(Store.self) private var store

    var body: some View {
        let i = ispirazione
        let righe = esito.dettaglio ?? []
        Fascia(salute: esito.ok ? .ok : .attenzione,
               testo: esito.frase ?? esito.messaggio ?? i.t("errore_titolo"),
               dettaglio: righe.isEmpty ? nil : righe.joined(separator: "\n")) {

            if let n = i.da_capire_visti, n > 0 {

                let nome = (i.ritmo?.pulsante).flatMap { $0.isEmpty ? nil : $0 }
                Button(nome ?? (i.t("capisci_tutti") + " · " + i.t("da_capire_visti", ["n": "\(n)"]))) {
                    Task {
                        if let e = await store.azioneInspiration(["capisci", "tutte"]) { store.erroreGesto = e }
                    }
                }
                .buttonStyle(.borderedProminent)
                .help(i.t("aiuto_capisci_tutti"))
            }
            Button(i.t("chiudi")) { store.riletturaInspiration = nil }
        }
    }
}


struct GrigliaSpunti: View {
    let voci: [Spunto]
    let ispirazione: Inspiration

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 200, maximum: 300), spacing: 16, alignment: .top)],
                  alignment: .leading, spacing: 22) {
            ForEach(voci) { s in
                SchedaSpunto(spunto: s, ispirazione: ispirazione)
                    .id(s.id)
            }
        }
    }
}




struct SchedaSpunto: View {
    let spunto: Spunto
    let ispirazione: Inspiration
    @Environment(Store.self) private var store
    @State private var sopra = false


    static var oggi: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }

    var body: some View {
        let s = spunto
        let i = ispirazione
        let forma = RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous)

        let nuova = s.segno != nil
        VStack(alignment: .leading, spacing: 5) {
            CopertinaSpunto(spunto: s, lato: 560)
                .aspectRatio(s.forma == "verticale" ? 4.0 / 5.0 : 16.0 / 10.0, contentMode: .fit)
                .frame(maxWidth: .infinity)
                .clipShape(forma)
                .overlay(forma.strokeBorder(Superficie.separatore, lineWidth: 0.5))
                .overlay(alignment: .topLeading) {
                    HStack(spacing: 6) {
                        Image(systemName: s.simbolo)
                            .font(.caption.weight(.semibold))
                            .padding(6)
                            .background(.regularMaterial, in: Circle())
                            .help(s.nome_tipo)


                        if !nuova, s.quando.hasPrefix(Self.oggi) {
                            Text(i.t("nuovo"))
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(Color.accentColor, in: Capsule())
                                .help(i.t("aiuto_nuovo"))
                        }
                    }
                    .padding(8)
                }
                .overlay(alignment: .topTrailing) {
                    if !nuova, let b = s.badge {
                        Text(b.parola)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Salute(motore: b.salute) == .neutra ? Color.primary : Color.white)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Salute(motore: b.salute) == .neutra
                                        ? AnyShapeStyle(.regularMaterial) : AnyShapeStyle(Salute(motore: b.salute).colore),
                                        in: Capsule())
                            .padding(8)
                            .help(b.aiuto)
                    }
                }
                .overlay(alignment: .bottomTrailing) {
                    if sopra {
                        AzioniSpunto(spunto: s, ispirazione: ispirazione)
                            .padding(8)
                    }
                }
            Text(s.titolo).font(Testo.nome).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            Text(s.sotto).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)

            if let audio = s.frase_audio, !audio.isEmpty {
                Label(audio, systemImage: "waveform").font(Testo.secondario).foregroundStyle(Color.accentColor)
                    .lineLimit(2)
            } else if !s.frase_owner.isEmpty {
                Text("«\(s.frase_owner)»").font(Testo.secondario).italic().lineLimit(1)
            }
            if let segno = s.segno {
                RigaSegno(progetto: s.progettoVista, segno: segno, ispirazione: i)
            } else {
                righeDiPrima(s, i)
            }
        }
        .contentShape(Rectangle())
        .onHover { sopra = $0 }
        .onTapGesture { store.spuntoAperto = s.id }
        .contextMenu { MenuSpunto(spunto: s, ispirazione: ispirazione) }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }


    @ViewBuilder
    private func righeDiPrima(_ s: Spunto, _ i: Inspiration) -> some View {
            if !s.progetto.isEmpty {
                Text(s.progetto)
                    .font(Testo.minimo.weight(.medium))
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(Superficie.riquadro, in: Capsule())
            }


            if let p = s.lavorazione?.perche, !p.esito_parole.isEmpty {
                if p.confermato {
                    Label(p.esito_parole, systemImage: "checkmark")
                        .labelStyle(.titleAndIcon).font(Testo.minimo).foregroundStyle(.secondary).lineLimit(1)
                } else {
                    Text("\(p.esito_parole) · \(i.t("da_confermare"))")
                        .font(Testo.minimo).foregroundStyle(.secondary).lineLimit(1)
                }
            }

            if let L = s.lavorazione, let st = L.stato_scheda, !st.isEmpty {
                Label(st, systemImage: L.tocca == "te" ? "hand.raised.fill" : "circle.fill")
                    .labelStyle(.titleAndIcon)
                    .font(Testo.minimo.weight(.medium))
                    .foregroundStyle(L.tocca == "te" ? Color.accentColor : Color.secondary)
                    .lineLimit(1)
            }
    }
}



struct RigaSegno: View {
    let progetto: String
    let segno: SegnoScheda
    var ispirazione: Inspiration? = nil

    var body: some View {
        if !progetto.isEmpty || segno.aVista {
            let (lunga, corta) = Self.forme(segno, ispirazione)


            ViewThatFits(in: .horizontal) {
                riga(lunga, intera: true)
                if let corta { riga(corta, intera: true) }
                riga(corta ?? lunga, intera: false)
            }
        }
    }



    static func forme(_ s: SegnoScheda, _ i: Inspiration?) -> (String, String?) {
        guard !s.domanda.isEmpty else { return (s.parola, nil) }
        func con(_ d: String) -> String {
            guard !s.accanto.isEmpty else { return d }
            if let modello = i?.testi["segno_domanda_accanto"], !modello.isEmpty {
                return modello.replacingOccurrences(of: "{domanda}", with: d).replacingOccurrences(of: "{accanto}", with: s.accanto)
            }
            return d == s.domanda ? s.parola : "\(d) · \(s.accanto)"
        }
        let corta = s.domanda_corta.isEmpty || s.domanda_corta == s.domanda ? nil : con(s.domanda_corta)
        return (con(s.domanda), corta)
    }


    static let tettoProgetto: CGFloat = 72

    @ViewBuilder
    private func riga(_ parola: String, intera: Bool) -> some View {


        let taglio = !intera && segno.aVista
        HStack(spacing: 6) {
            if !progetto.isEmpty {
                Text(progetto).font(Testo.minimo.weight(.medium)).foregroundStyle(.secondary)
                    .lineLimit(1)
                    .fixedSize(horizontal: intera, vertical: false)
                    .frame(maxWidth: taglio ? Self.tettoProgetto : nil, alignment: .leading)
                    .fixedSize(horizontal: taglio, vertical: false)
                    .layoutPriority(1)
            }
            if !progetto.isEmpty && segno.aVista {
                Text("·").font(Testo.minimo).foregroundStyle(.tertiary)
            }
            if segno.aVista {
                HStack(spacing: 4) {
                    Self.simbolo(segno)
                    Text(parola).lineLimit(1)
                }
                .font(Testo.minimo.weight(.medium))
                .foregroundStyle(Self.colore(segno))
                .fixedSize(horizontal: intera, vertical: false)
                .help(segno.aiuto ?? "")
            }
        }
    }

    static func colore(_ s: SegnoScheda) -> Color {
        switch s.salute {
        case "accento": Color.accentColor
        case "attenzione": Salute.attenzione.colore
        default: Color.secondary
        }
    }


    @ViewBuilder
    static func simbolo(_ s: SegnoScheda) -> some View {
        switch s.tipo {
        case "scende": Image(systemName: "arrow.down")
        case "capisco", "lavora": ProgressView().controlSize(.mini)
        case "tocca_te": Image(systemName: "hand.raised.fill")
        case "fermo": Image(systemName: Salute.attenzione.simbolo)


        case "da_confermare", "da_far_partire", "domanda", "da_avviare", "ritorno", "da_scegliere", "task_da_creare",
             "da_leggere":
            if s.salute == "accento" { Image(systemName: "hand.raised.fill") } else { EmptyView() }


        case "agente_aperto": EmptyView()
        default: EmptyView()
        }
    }
}

struct AzioniSpunto: View {
    let spunto: Spunto
    let ispirazione: Inspiration

    var body: some View {
        HStack(spacing: 4) {
            if let u = URL(string: spunto.url), !spunto.url.isEmpty {
                Button { NSWorkspace.shared.open(u) } label: { Image(systemName: "arrow.up.right.square") }
                    .help(ispirazione.t("aiuto_apri_originale"))
            }
            if let u = URL(string: spunto.permalink), !spunto.permalink.isEmpty {
                Button { NSWorkspace.shared.open(u) } label: { Image(systemName: "bubble.left") }
                    .help(ispirazione.t("aiuto_rispondi_slack"))
            }
        }
        .buttonStyle(.borderless)
        .padding(5)
        .background(.regularMaterial, in: Capsule())
    }
}

struct MenuSpunto: View {
    let spunto: Spunto
    let ispirazione: Inspiration

    var conOriginale = true

    var body: some View {
        if let u = URL(string: spunto.url), !spunto.url.isEmpty {
            if conOriginale {
                Button(ispirazione.t("apri_originale")) { NSWorkspace.shared.open(u) }
            }
            Button(ispirazione.t("copia_link")) {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(spunto.url, forType: .string)
            }
        }
        if let u = URL(string: spunto.permalink), !spunto.permalink.isEmpty {
            Button(ispirazione.t("rispondi_slack")) { NSWorkspace.shared.open(u) }
        }
    }
}






struct MenuFase: View {
    let ispirazione: Inspiration
    let scheda: String
    var conti: [String: Int]? = nil
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        let i = ispirazione
        if let passi = i.passiMenu {

            let dentro = passi.filter { !$0.staccata }
            let fuori = passi.filter { $0.staccata }

            Picker(i.testi["passi_menu_titolo"] ?? i.t("fase"), selection: Binding(get: { scheda }, set: {
                store.faseInspiration = $0
                store.vistaInspiration = nil
            })) {
                ForEach(dentro) { p in Text(Self.testoPasso(p, i, conti)).tag(p.id) }
                if !fuori.isEmpty {
                    Divider()
                    ForEach(fuori) { p in Text(Self.testoPasso(p, i, conti)).tag(p.id) }
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .fixedSize()
            .tint(scheda == "tutti" ? nil : Color.accentColor)
            .help(i.testi["aiuto_passo_menu"] ?? i.t("aiuto_fase"))
        } else if let fasi = i.fasi {
            let ordinate = fasi.filter { $0.id == "tutti" } + fasi.filter { $0.id != "tutti" }
            Picker(i.t("fase"), selection: Binding(get: { scheda }, set: { store.faseInspiration = $0 })) {
                ForEach(ordinate) { f in
                    Text(Bacheca.testoPillola(f, i)).tag(f.id)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .fixedSize()
            .tint(scheda == "tutti" ? nil : Color.accentColor)
            .help(i.t("aiuto_fase"))
        } else {
            Picker(i.t("fase"), selection: Binding(get: { scheda }, set: { store.schedaInspiration = $0 })) {
                ForEach(i.schede) { s in
                    Text("\(s.nome) \(s.n)").tag(s.id)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .fixedSize()
            .help(i.t("aiuto_fase"))
        }
    }
}

extension MenuFase {



    static func testoPasso(_ p: PassoMenu, _ i: Inspiration, _ conti: [String: Int]? = nil) -> String {
        if let conti {
            let n = p.id == "tutti" ? conti.values.reduce(0, +) : (conti[p.id] ?? 0)
            return i.t("menu_etichetta", ["nome": p.nome, "n": "\(n)"], o: "\(p.nome) \(n)")
        }
        if !p.etichetta.isEmpty { return p.etichetta }
        var testo = p.nome
        if p.n > 0 { testo += " \(p.n)" }
        if p.per_te > 0, p.per_te != p.n {
            testo += " · " + i.t("per_te", ["n": "\(p.per_te)"], o: i.t("aspettano_te", ["n": "\(p.per_te)"]))
        }
        return testo
    }
}


struct MenuPaginaOnline: View {
    let ispirazione: Inspiration
    @Environment(Store.self) private var store

    var body: some View {
        let capo = store.pagine?.pagine.first { $0.raccolta == "inspiration" && $0.capofamiglia != false && $0.giusta == true }
            ?? store.pagine?.pagine.first { $0.raccolta == "inspiration" && $0.capofamiglia != false }
        let prima = (capo?.versioni_famiglia ?? []).filter { $0.id != capo?.id }
        let testa = ispirazione.testa
        let impostazioni = ispirazione.impostazioni
        Menu {

            if let impostazioni {
                Button("\(impostazioni.titolo)…") { store.apriImpostazioniInspiration() }
                if testa != nil || capo != nil { Divider() }
            }

            if let testa {
                Button(testa.rileggi_parola ?? ispirazione.t("rileggi")) { Task { await store.rileggiInspiration() } }
                    .disabled(store.riletturaInCorso)
                if capo != nil { Divider() }
            }
            if let capo {
                Button(ispirazione.t("apri_pagina_online", o: ispirazione.t("apri_online"))) { apriOnline(capo) }
                Button(ispirazione.t("copia_link_pagina", o: ispirazione.t("copia_link"))) { copiaLink(capo) }
                if !prima.isEmpty {
                    Menu(ispirazione.t("versioni_di_prima")) {
                        ForEach(prima) { v in
                            Button(v.frase) { if let u = URL(string: v.url) { NSWorkspace.shared.open(u) } }
                        }
                    }
                }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
        .menuIndicator(.hidden)
        .fixedSize()

        .disabled(impostazioni == nil && capo == nil && testa == nil)
        .help(ispirazione.t("aiuto_menu_altro", o: ispirazione.t("aiuto_pagina_online")))
        .accessibilityLabel(ispirazione.t("altro_menu"))
    }
}



struct Chip: View {
    let testo: String
    var simbolo: String? = nil
    let acceso: Bool
    var piccolo = false
    var spenta = false
    let azione: () -> Void

    var body: some View {
        Button(action: azione) {
            HStack(spacing: 4) {
                if let simbolo { Image(systemName: simbolo) }
                Text(testo)
            }
            .font(piccolo ? Testo.secondario : Testo.corpo.weight(acceso ? .semibold : .regular))
            .padding(.horizontal, piccolo ? 9 : 12)
            .padding(.vertical, piccolo ? 4 : 6)
            .foregroundStyle(acceso ? Color.white : (spenta ? Color.secondary : Color.primary))
            .background(acceso ? AnyShapeStyle(Color.accentColor)
                        : (spenta ? AnyShapeStyle(Color.clear) : AnyShapeStyle(Superficie.riquadro)), in: Capsule())
            .overlay {
                if spenta && !acceso { Capsule().strokeBorder(Superficie.separatore, lineWidth: 0.5) }
            }
        }
        .buttonStyle(.plain)
    }
}



struct CopertinaSpunto: View {
    let spunto: Spunto
    let lato: CGFloat
    @State private var immagine: NSImage?

    @State private var illeggibile = false

    var body: some View {
        let senza = spunto.copertina == nil || illeggibile


        Rectangle().fill(Superficie.riquadro)
            .overlay {
                if let immagine {
                    Image(nsImage: immagine).resizable().aspectRatio(contentMode: .fill)
                } else if senza, spunto.haAnteprima {


                    AnteprimaSenzaCopertina(spunto: spunto, grande: lato > 600)
                } else if spunto.copertina == nil, let segno = spunto.segno, segno.tipo == "scende", segno.aVista {


                    Image(systemName: "arrow.down").font(.title2)
                        .foregroundStyle(.secondary)
                        .help(segno.aiuto ?? "")
                } else if senza {
                    VStack(spacing: 6) {
                        Image(systemName: spunto.simbolo).font(.title2)
                        Text(spunto.piattaforma).font(Testo.minimo)
                    }
                    .foregroundStyle(.secondary)
                }
            }
            .clipped()
        .task(id: spunto.copertina) {

            guard let c = spunto.copertina else {
                immagine = nil
                illeggibile = false
                return
            }
            let letta = await Copertine.condivise.immagine(c, lato: lato)
            immagine = letta
            illeggibile = letta == nil
        }
    }
}




struct AnteprimaSenzaCopertina: View {
    let spunto: Spunto
    let grande: Bool

    var body: some View {


        let verticale = spunto.forma == "verticale"
        let righe = grande ? (verticale ? 14 : 5) : (verticale ? 6 : 3)
        Text(spunto.anteprimaTitolo)
            .font(grande ? Testo.corpo : Testo.secondario)
            .lineLimit(righe)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, grande ? 22 : 14)

            .padding(.top, grande ? 0 : 28)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}


@MainActor
final class Copertine {
    static let condivise = Copertine()
    private let memoria = NSCache<NSString, NSImage>()

    func immagine(_ percorso: String, lato: CGFloat) async -> NSImage? {
        let chiave = "\(percorso)|\(Int(lato))" as NSString
        if let img = memoria.object(forKey: chiave) { return img }
        let cg = await Task.detached(priority: .userInitiated) { Copertine.riduci(percorso, lato: lato) }.value
        guard let cg else { return nil }
        let img = NSImage(cgImage: cg, size: .zero)
        memoria.setObject(img, forKey: chiave)
        return img
    }

    nonisolated static func riduci(_ percorso: String, lato: CGFloat) -> CGImage? {
        guard let sorgente = CGImageSourceCreateWithURL(URL(fileURLWithPath: percorso) as CFURL, nil) else { return nil }
        let opzioni = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: lato,
            kCGImageSourceCreateThumbnailWithTransform: true,
        ] as CFDictionary
        return CGImageSourceCreateThumbnailAtIndex(sorgente, 0, opzioni)
    }
}


struct SchedeVuote: View {
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 200, maximum: 300), spacing: 16)], spacing: 22) {
            ForEach(0..<8, id: \.self) { _ in
                VStack(alignment: .leading, spacing: 6) {
                    RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous).fill(Superficie.riquadro)
                        .aspectRatio(4.0 / 5.0, contentMode: .fit)
                    RoundedRectangle(cornerRadius: 4).fill(Superficie.riquadro).frame(height: 12)
                    RoundedRectangle(cornerRadius: 4).fill(Superficie.riquadro).frame(width: 120, height: 10)
                }
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
}







struct SpuntoAperto: View {
    let ispirazione: Inspiration
    let spunto: Spunto
    @Environment(Store.self) private var store
    @FocusState private var fuoco: Bool

    @State private var elenco: [String] = []

    var body: some View {
        let i = ispirazione
        let s = spunto
        let tutte = i.voci + i.a_parte
        let ids = elenco.isEmpty ? Self.elencoAttuale(i, s, store) : elenco
        let k = ids.firstIndex(of: s.id)
        let prossimoTe = Self.prossimoCheAspetta(ids, da: k, in: tutte)
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button { store.spuntoAperto = nil } label: {
                    Label(i.t("titolo"), systemImage: "chevron.left")
                }
                Spacer(minLength: Spazio.fratelli)
                Button { vai(ids, k, -1, tutte) } label: { Image(systemName: "arrow.left") }
                    .disabled((k ?? 0) == 0)
                    .help(i.t("precedente"))
                Text(k.map { i.t("posizione", ["k": "\($0 + 1)", "n": "\(ids.count)"]) } ?? "")
                    .font(Testo.secondario).foregroundStyle(.secondary).monospacedDigit()
                    .help(i.t("aiuto_frecce"))
                Button { vai(ids, k, 1, tutte) } label: { Image(systemName: "arrow.right") }
                    .disabled(k == nil || k! >= ids.count - 1)
                    .help(i.t("successivo"))


                if let id = prossimoTe {
                    Button { store.spuntoAperto = id } label: {
                        Label(i.t("prossimo_che_aspetta"), systemImage: "arrow.forward.circle")
                    }
                    .fixedSize()
                    .help(i.t("aiuto_prossimo", o: i.t("prossimo_che_aspetta")))
                }
                Spacer(minLength: Spazio.fratelli)
                if let u = URL(string: s.url), !s.url.isEmpty {
                    Button(i.t("apri_originale")) { NSWorkspace.shared.open(u) }
                        .help(i.t("aiuto_apri_originale"))
                }
                Menu {

                    MenuSpunto(spunto: s, ispirazione: i, conOriginale: false)

                    if let az = s.lavorazione?.azioni, (az.capisci_pannello_menu ?? az.capisci_pannello) == true {
                        Divider()
                        Button(i.t("capisci_pannello_menu", o: i.t("capisci_pannello"))) {
                            Task {
                                if let e = await store.azioneInspiration(["capisci", s.id, "--pannello"]) { store.erroreGesto = e }
                            }
                        }
                        .help(i.t("aiuto_capisci_pannello"))
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .menuIndicator(.hidden)
                .fixedSize()
            }
            .padding(.horizontal, Spazio.margine)
            .padding(.vertical, 10)
            .background(Superficie.pagina)
            Divider()
            if store.inspirationNonRiletta {

                FasciaRilettura(ispirazione: i)
                    .padding(.horizontal, Spazio.margine)
                    .padding(.top, 10)
            }
            if let notizia = store.notizia {


                FasciaNotizia(notizia: notizia)
                    .padding(.horizontal, Spazio.margine)
                    .padding(.top, 10)
            }
            HStack(alignment: .top, spacing: 0) {
                ColonnaContenuto(spunto: s, ispirazione: i)
                    .frame(width: 360)
                    .padding(Spazio.margine)
                Divider()
                ColonnaTesto(spunto: s, ispirazione: i, prossimo: prossimoTe.map { id in { store.spuntoAperto = id } })
            }
        }
        .focusable()
        .focusEffectDisabled()
        .focused($fuoco)
        .onAppear {
            fuoco = true


            if store.modoIstantanea, elenco.isEmpty { Bacheca.filtriDaIstantanea(store, i) }
            if elenco.isEmpty { elenco = Self.elencoAttuale(i, s, store) }
            store.notiziaDaIstantanea()
        }
        .onKeyPress(.leftArrow) {
            vai(ids, k, -1, tutte)
            return .handled
        }
        .onKeyPress(.rightArrow) {
            vai(ids, k, 1, tutte)
            return .handled
        }
        .onExitCommand { store.spuntoAperto = nil }
    }


    static func elencoAttuale(_ i: Inspiration, _ s: Spunto, _ store: Store) -> [String] {
        (s.a_parte == true ? i.a_parte
            : Bacheca.filtra(i.voci, store: store, scheda: Bacheca.selezione(i, store: store), ispirazione: i)).map(\.id)
    }


    static func prossimoCheAspetta(_ ids: [String], da k: Int?, in tutte: [Spunto]) -> String? {
        guard let k, !ids.isEmpty else { return nil }
        let dopo = ids.indices.filter { $0 > k } + ids.indices.filter { $0 < k }
        for j in dopo {
            if tutte.first(where: { $0.id == ids[j] })?.tocca == "te" { return ids[j] }
        }
        return nil
    }

    private func vai(_ ids: [String], _ k: Int?, _ passo: Int, _ tutte: [Spunto]) {
        guard let k else { return }
        var j = k + passo

        while ids.indices.contains(j), !tutte.contains(where: { $0.id == ids[j] }) { j += passo }
        guard ids.indices.contains(j) else { return }
        store.spuntoAperto = ids[j]
    }
}



struct ColonnaContenuto: View {
    let spunto: Spunto
    let ispirazione: Inspiration
    @Environment(Store.self) private var store
    @State private var lettore: AVPlayer?
    @State private var trascrizione: String?
    @State private var trascrizioneAperta = false
    @State private var didascaliaAperta = false
    @State private var storiaAperta = false

    var body: some View {
        let d = spunto.dettaglio
        let i = ispirazione
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                let forma = RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous)
                if let lettore, !store.modoIstantanea {
                    VistaVideo(lettore: lettore)
                        .aspectRatio(9.0 / 16.0, contentMode: .fit)
                        .clipShape(forma)
                } else {
                    CopertinaSpunto(spunto: spunto, lato: 900)
                        .aspectRatio(spunto.forma == "verticale" ? 9.0 / 16.0 : 16.0 / 10.0, contentMode: .fit)
                        .clipShape(forma)
                        .overlay(forma.strokeBorder(Superficie.separatore, lineWidth: 0.5))
                }
                if spunto.video != nil {
                    Label(ispirazione.t("video_qui"), systemImage: "play.rectangle")
                        .font(Testo.minimo).foregroundStyle(.secondary)
                }
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    segnoContenuto
                    Text(spunto.dettaglio.contenuto).fixedSize(horizontal: false, vertical: true)
                }
                .font(Testo.secondario)
                if !spunto.dettaglio.online.isEmpty {
                    Text(spunto.dettaglio.online).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                let cosaSo = !d.realizzato.isEmpty || !d.promette.isEmpty || !d.simili.isEmpty
                if cosaSo || (d.dalla_didascalia && !d.destinazione.isEmpty) {
                    Divider().padding(.vertical, 4)
                    if d.dalla_didascalia {
                        DisclosureGroup(isExpanded: $didascaliaAperta) {
                            VStack(alignment: .leading, spacing: 12) {
                                Text(i.t("dalla_didascalia_frase")).font(Testo.secondario).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                                sapere(d, i)
                            }
                            .padding(.top, 8)
                        } label: {
                            Text(i.t("dalla_didascalia")).font(Testo.titoloGruppo)
                        }
                    } else {
                        Text(i.t("cosa_ne_so")).font(Testo.titoloSezione)
                        sapere(d, i)
                    }
                }
                if spunto.trascrizione != nil {
                    DisclosureGroup(ispirazione.t("trascrizione"), isExpanded: $trascrizioneAperta) {
                        Text(trascrizione ?? "")
                            .font(Testo.secondario)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .font(Testo.secondario)
                }
                if !d.storia.isEmpty {
                    DisclosureGroup(isExpanded: $storiaAperta) {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(d.storia.enumerated()), id: \.offset) { _, p in
                                Text("\(p.quando)  \(p.cosa)").font(Testo.minimo).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .padding(.top, 6)
                    } label: {
                        Text(i.t("storia")).font(Testo.secondario)
                    }
                    .font(Testo.secondario)
                }
            }
        }
        .task(id: spunto.id) {
            lettore?.pause()
            lettore = spunto.video.map { AVPlayer(url: URL(fileURLWithPath: $0)) }
            trascrizione = spunto.trascrizione.flatMap { try? String(contentsOfFile: $0, encoding: .utf8) }
            trascrizioneAperta = false
            didascaliaAperta = false
            storiaAperta = false
        }
        .onDisappear { lettore?.pause() }
    }



    @ViewBuilder
    private var segnoContenuto: some View {
        switch spunto.contenuto_salute {
        case "attenzione":
            Image(systemName: Simbolo.attenzione).foregroundStyle(Salute.attenzione.colore)
        case "ok":
            Image(systemName: "checkmark.circle.fill").foregroundStyle(Salute.ok.colore)
        case .some:
            Image(systemName: "arrow.down.circle").foregroundStyle(.secondary)
        case nil:
            Image(systemName: spunto.visto ? "checkmark.circle.fill" : Simbolo.attenzione)
                .foregroundStyle(spunto.visto ? Salute.ok.colore : Salute.attenzione.colore)
        }
    }

    @ViewBuilder
    private func sapere(_ d: DettaglioSpunto, _ i: Inspiration) -> some View {
        if d.dalla_didascalia && !d.destinazione.isEmpty {
            Label(d.destinazione, systemImage: "arrow.turn.down.right").font(Testo.corpo)
                .help(i.t("dove_va"))
        }
        if !d.realizzato.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(i.t("cosa_mostra")).font(Testo.titoloGruppo)
                Text(d.realizzato).fixedSize(horizontal: false, vertical: true)
            }
        }
        if !d.promette.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(i.t("cosa_promette")).font(Testo.titoloGruppo)
                Text(d.promette).fixedSize(horizontal: false, vertical: true)
            }
        }
        if !d.simili.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(i.t("cose_simili")).font(Testo.titoloGruppo)
                ForEach(d.simili, id: \.self) { c in
                    VStack(alignment: .leading, spacing: 1) {
                        if let u = URL(string: c.url), !c.url.isEmpty {
                            Link(c.nome, destination: u)
                        } else {
                            Text(c.nome)
                        }
                        Text(c.perche).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }
}



struct VistaVideo: NSViewRepresentable {
    let lettore: AVPlayer

    func makeNSView(context: Context) -> NSView { VideoMac.vista(lettore) }

    func updateNSView(_ vista: NSView, context: Context) { VideoMac.aggiorna(vista, lettore) }
}



struct RigaAudio: View {
    let audio: AudioDiOwner
    let ispirazione: Inspiration

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "waveform").foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(audio.frase).font(Testo.corpo).fixedSize(horizontal: false, vertical: true)
                if !audio.quando.isEmpty {
                    Text(audio.quando).font(Testo.minimo).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: Spazio.fratelli)
            if let file = audio.audio {
                LettoreAudio(file: file, ispirazione: ispirazione)
            }
            if let u = URL(string: audio.permalink), !audio.permalink.isEmpty {
                Button(ispirazione.t("ascolta_slack")) { NSWorkspace.shared.open(u) }
                    .help(ispirazione.t("aiuto_ascolta_slack"))
            }
        }
    }
}


struct LettoreAudio: View {
    let file: String
    let ispirazione: Inspiration
    @State private var lettore: AVPlayer?
    @State private var suona = false

    var body: some View {
        Button {
            if suona {
                lettore?.pause()
                suona = false
            } else {
                if lettore == nil { lettore = AVPlayer(url: URL(fileURLWithPath: file)) }
                if let l = lettore, let fine = l.currentItem?.duration, fine.isNumeric,
                   l.currentTime().seconds >= fine.seconds - 0.1 {
                    l.seek(to: .zero)
                }
                lettore?.play()
                suona = true
            }
        } label: {
            Label(ispirazione.t(suona ? "pausa" : "ascolta"), systemImage: suona ? "pause.fill" : "play.fill")
        }
        .help(ispirazione.t("aiuto_ascolta"))
        .onReceive(NotificationCenter.default.publisher(for: AVPlayerItem.didPlayToEndTimeNotification)) { nota in
            if (nota.object as? AVPlayerItem) === lettore?.currentItem { suona = false }
        }
        .onDisappear {
            lettore?.pause()
            suona = false
        }
    }
}



struct ParoleDiOwner: View {
    let spunto: Spunto
    let ispirazione: Inspiration

    var body: some View {
        let s = spunto
        let d = s.dettaglio
        let i = ispirazione
        let L = s.lavorazione
        let audio = d.audio_owner ?? []



        let soloIlTitolo = s.titolo_sono_parole == true && d.parole_owner.count == 1 && audio.isEmpty
            && s.titolo == "«\(d.parole_owner[0].testo)»"
        let parole = soloIlTitolo ? [] : d.parole_owner
        let haRisposte = L.map { L in
            L.domande.contains { ($0.chiusa && !$0.dalSistema) || $0.inViaggio || !$0.statoAudio.isEmpty } || L.perche.eCorretto
        } ?? false
        let nessuna = d.nessuna_parola_vale ?? (d.parole_owner.isEmpty && audio.isEmpty && !haRisposte)
        if !parole.isEmpty || !audio.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(i.t("le_tue_parole")).font(Testo.titoloGruppo)
                ForEach(parole, id: \.self) { p in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("«\(p.testo)»").font(Testo.corpo).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            if let a = p.fileAudio { LettoreAudio(file: a, ispirazione: i) }
                        }
                        if !p.quando.isEmpty {
                            Text(p.quando).font(Testo.minimo).foregroundStyle(.secondary)
                        }
                    }
                }
                ForEach(audio, id: \.self) { a in
                    RigaAudio(audio: a, ispirazione: i)
                }

                if L == nil, let u = URL(string: s.permalink), !s.permalink.isEmpty {
                    Button(i.t("rispondi_slack")) { NSWorkspace.shared.open(u) }
                        .help(i.t("aiuto_rispondi_slack"))
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.10), in: RoundedRectangle(cornerRadius: Raggio.riquadro))
        } else if nessuna {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(i.t("nessuna_parola")).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if L == nil, let u = URL(string: s.permalink), !s.permalink.isEmpty {
                    Button(i.t("rispondi_slack")) { NSWorkspace.shared.open(u) }
                        .help(i.t("aiuto_rispondi_slack"))
                }
            }
        }
    }
}




struct ColonnaTesto: View {
    let spunto: Spunto
    let ispirazione: Inspiration
    var prossimo: (() -> Void)?

    var body: some View {
        let s = spunto
        let d = s.dettaglio
        let i = ispirazione
        let L = s.lavorazione

        let inFila = L?.adessoFila != nil
        ScrollView {
            VStack(alignment: .leading, spacing: Spazio.griglia) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.titolo).font(.title2.weight(.bold)).fixedSize(horizontal: false, vertical: true)
                    Text(d.testa).font(Testo.secondario).foregroundStyle(.secondary)


                    if s.lavorazione == nil, let b = s.badge {
                        Label(b.aiuto, systemImage: Salute(motore: b.salute) == .neutra ? "eye.slash" : Simbolo.attenzione)
                            .font(Testo.secondario)
                            .foregroundStyle(Salute(motore: b.salute).colore)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if inFila {
                    EmptyView()
                } else if let L, L.perche.c_e || L.perche.confermato {
                    if !s.progetto.isEmpty {
                        Label(s.progetto, systemImage: "arrow.turn.down.right").font(Testo.corpo)
                            .help(i.t("dove_va"))
                    }
                } else if !d.dalla_didascalia, !d.destinazione.isEmpty {
                    Label(d.destinazione, systemImage: "arrow.turn.down.right").font(Testo.corpo)
                        .help(i.t("dove_va"))
                }




                if L == nil {
                    ParoleDiOwner(spunto: s, ispirazione: i)
                }

                if let L {
                    RiquadroLavorazione(spunto: s, lavorazione: L, ispirazione: i, prossimo: prossimo)
                }

                if !d.domande.isEmpty && L == nil {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(i.t("domanda_per_te")).font(Testo.titoloGruppo)
                        ForEach(d.domande, id: \.self) { q in
                            Text(q).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(Spazio.margine)
            .frame(maxWidth: inFila ? 880 : 720, alignment: .leading)
        }
    }
}
