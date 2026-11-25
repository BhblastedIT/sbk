import SwiftUI





struct PaginaPosta: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: store.posta?.t("titolo") ?? "Mail",
                         sottotitolo: store.posta?.t("sottotitolo") ?? "") {
            if let p = store.posta {
                SchedaVerdettoPosta(posta: p)
                SchedaContoPosta(posta: p)
                if let c = store.contoPosta, !c.nuovi.isEmpty { ElencoNuovi(posta: p, conto: c) }
                SchedaCaselle(posta: p)
                ElencoMittenti(posta: p)
                if !p.storia.isEmpty { SchedaStoriaPosta(posta: p) }
            } else if let e = store.errorePosta {
                Text(e).foregroundStyle(.secondary).scheda()
            } else {
                ProgressView().frame(maxWidth: .infinity).scheda()
            }
        }
        .task {
            await store.caricaPosta()
            await store.caricaContoPosta()
        }
    }
}



struct Posta: Codable, Hashable {
    let ok: Bool
    let verdetto: String
    let da_fare: Int
    let da_guardare: Int
    let caselle: [CasellaPosta]
    let categorie: [CategoriaPosta]
    let mittenti: [MittentePosta]
    let storia: [VocePosta]
    let testi: [String: String]


    func t(_ chiave: String) -> String { testi[chiave] ?? chiave }
}

struct CasellaPosta: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let allineata: Bool
    let da_scrivere: Int
    let da_togliere: Int
    let frase: String
    let per_categoria: [ContoCategoria]
}

struct ContoCategoria: Codable, Hashable {
    let categoria: String
    let mittenti: Int
}

struct CategoriaPosta: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let simbolo: String
    let colore: String
    let aiuto: String

    var tinta: Color {
        switch colore {
        case "blue": .blue
        case "teal": .teal
        case "orange": .orange
        case "green": .green
        case "pink": .pink
        case "red": .red
        case "indigo": .indigo
        case "purple": .purple
        default: .gray
        }
    }
}

struct MittentePosta: Codable, Hashable, Identifiable {
    let casella: String
    let mittente: String
    let categoria: String
    let mail_90gg: Int
    let spostabile: Bool
    let aiuto: String

    var id: String { casella + "|" + mittente }
}

struct VocePosta: Codable, Hashable {
    let quando: String
    let frase: String
}

struct EsitoPosta: Codable {
    let ok: Bool
    let frase: String
}


struct SpostamentoPosta: Identifiable {
    let mittente: MittentePosta
    let verso: CategoriaPosta
    var id: String { mittente.id + ">" + verso.id }
}



struct SchedaVerdettoPosta: View {
    let posta: Posta
    @Environment(Store.self) private var store
    @State private var conferma = false

    var body: some View {
        let aPosto = posta.da_fare == 0 && posta.da_guardare == 0
        HStack(spacing: 14) {
            TesseraIcona(simbolo: aPosto ? "checkmark.circle.fill" : "arrow.triangle.2.circlepath",
                         colore: aPosto ? .green : .orange, lato: 36)
                .help(posta.t(aPosto ? "aiuto_icona_ok" : "aiuto_icona_da_fare"))
            VStack(alignment: .leading, spacing: 2) {
                Text(posta.verdetto).font(Testo.nome)
                Text(posta.t("sotto_verdetto"))
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            if store.postaInCorso {
                ProgressView().controlSize(.small).help(posta.t("aiuto_rotella"))
            }
            Button(posta.t("pulsante")) { conferma = true }
                .buttonStyle(.borderedProminent)
                .disabled(posta.da_fare == 0 || store.postaInCorso || store.modoIstantanea)
                .help(posta.t(posta.da_fare == 0 ? "aiuto_pulsante_fermo" : "aiuto_pulsante"))
        }
        .scheda(tinta: aPosto ? .green : .orange)
        .alert(posta.t("conferma_titolo"), isPresented: $conferma) {
            Button(posta.t("foglio_annulla"), role: .cancel) {}
                .keyboardShortcut(.defaultAction)
            Button(posta.t("pulsante")) { Task { await store.applicaPosta() } }
        } message: {
            Text(posta.t("conferma"))
        }
    }
}



struct SchedaCaselle: View {
    let posta: Posta
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: posta.t("caselle"), conteggio: "\(posta.caselle.count)")
                .help(posta.t("aiuto_conto_caselle"))
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: Spazio.griglia, alignment: .top)],
                      alignment: .leading, spacing: Spazio.griglia) {
                ForEach(posta.caselle) { c in
                    Button {
                        store.postaCasella = c.id
                    } label: {
                        tessera(c)
                    }
                    .buttonStyle(.plain)
                    .help("\(c.id). \(posta.t("aiuto_tessera"))")
                }
            }
        }
    }

    private func tessera(_ c: CasellaPosta) -> some View {
        let scelta = (store.postaCasella ?? posta.caselle.first?.id) == c.id
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: Simbolo.ok).foregroundStyle(c.allineata ? .green : .orange).font(.caption)
                    .help(posta.t(c.allineata ? "aiuto_pallino_ok" : "aiuto_pallino_da_fare"))
                Text(c.nome).font(Testo.nome)
            }
            Text(c.frase).font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(conti(c)).font(Testo.minimo).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .help(posta.t("aiuto_conti"))
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .scheda(interno: 12, tinta: scelta ? .accentColor : nil)
    }

    private func conti(_ c: CasellaPosta) -> String {
        c.per_categoria.map { conto in
            let nome = posta.categorie.first(where: { $0.id == conto.categoria })?.nome ?? conto.categoria
            return "\(conto.mittenti) \(nome)"
        }.joined(separator: " · ")
    }
}



struct ElencoMittenti: View {
    let posta: Posta
    @Environment(Store.self) private var store
    @State private var categoria = "tutte"
    @State private var spostamento: SpostamentoPosta?
    private let tetto = 150

    var body: some View {
        @Bindable var store = store
        let casella = store.postaCasella ?? posta.caselle.first?.id ?? ""
        let nomeCasella = posta.caselle.first(where: { $0.id == casella })?.nome ?? casella
        let cerca = store.postaCerca.trimmingCharacters(in: .whitespaces).lowercased()
        let tutti = posta.mittenti.filter {
            $0.casella == casella && (categoria == "tutte" || $0.categoria == categoria)
                && (cerca.isEmpty || $0.mittente.contains(cerca) || $0.aiuto.lowercased().contains(cerca))
        }.sorted { ($0.mail_90gg, $1.mittente) > ($1.mail_90gg, $0.mittente) }
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "\(posta.t("mittenti_di")) \(nomeCasella)", conteggio: "\(tutti.count)") {
                TextField(posta.t("cerca"), text: $store.postaCerca)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 220)
                Picker(posta.t("aiuto_filtro"), selection: $categoria) {
                    Text(posta.t("tutte")).tag("tutte")
                    ForEach(posta.categorie) { c in Text(c.nome).tag(c.id) }
                }
                .labelsHidden()
                .frame(width: 160)
                .help(posta.t("aiuto_filtro"))
            }
            .help(posta.t("aiuto_conto_mittenti"))
            VStack(spacing: 0) {
                ForEach(Array(tutti.prefix(tetto).enumerated()), id: \.element.id) { i, m in
                    if i > 0 { Separatore().padding(.leading, 52) }
                    riga(m)
                }
                if tutti.isEmpty {
                    Text(posta.t("nessuno")).font(Testo.secondario).foregroundStyle(.secondary)
                        .padding(14)
                }
            }
            .scheda(interno: 0)
            if tutti.count > tetto {
                Text(posta.t("troppi").replacingOccurrences(of: "{n}", with: "\(tetto)")
                    .replacingOccurrences(of: "{tot}", with: "\(tutti.count)"))
                    .font(Testo.secondario).foregroundStyle(.secondary)
            }
            Text(posta.t("speciali"))
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .sheet(item: $spostamento) { s in
            FoglioSpostaMittente(posta: posta, spostamento: s)
        }
    }

    private func riga(_ m: MittentePosta) -> some View {
        let cat = posta.categorie.first(where: { $0.id == m.categoria })
        return HStack(spacing: 12) {
            TesseraIcona(simbolo: cat?.simbolo ?? "envelope.fill", colore: cat?.tinta ?? .gray, lato: 26)
                .help(m.aiuto)
            Text(m.mittente).font(Testo.corpo).lineLimit(1).truncationMode(.middle)
                .help(m.aiuto)
            Spacer(minLength: Spazio.fratelli)
            Text("\(m.mail_90gg) mail")
                .font(Testo.cifreInColonna).foregroundStyle(.secondary)
                .help(posta.t("aiuto_mail"))
            Menu {
                ForEach(posta.categorie.filter { $0.id != m.categoria }) { c in
                    Button(c.nome) { spostamento = SpostamentoPosta(mittente: m, verso: c) }
                }
            } label: {
                Text(cat?.nome ?? m.categoria)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()

            .disabled(!m.spostabile || store.postaInCorso || store.modoIstantanea)
            .help(m.spostabile ? "\(cat?.aiuto ?? "") \(posta.t("aiuto_menu"))" : posta.t("aiuto_menu_fermo"))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}


struct FoglioSpostaMittente: View {
    let posta: Posta
    let spostamento: SpostamentoPosta
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi
    @State private var perche = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("\(posta.t("foglio_titolo")) \(spostamento.mittente.mittente)").font(Testo.titoloSezione)
            Text("\(posta.t("foglio_va_in")) \(spostamento.verso.nome). \(spostamento.verso.aiuto)")
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField(posta.t("foglio_perche"), text: $perche, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
            Text(posta.t("foglio_nota"))
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(posta.t("foglio_annulla"), role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button(posta.t("foglio_sposta")) {
                    let s = spostamento
                    let p = perche
                    chiudi()
                    Task { await store.spostaMittente(s.mittente, verso: s.verso.id, perche: p) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(perche.trimmingCharacters(in: .whitespaces).isEmpty)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}



struct SchedaStoriaPosta: View {
    let posta: Posta

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: posta.t("storia"))
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(posta.storia.enumerated()), id: \.offset) { i, v in
                    if i > 0 { Separatore() }
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text(v.quando).font(Testo.secondario).foregroundStyle(.secondary)
                            .frame(width: 150, alignment: .leading)
                        Text(v.frase).font(Testo.corpo)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                }
            }
            .scheda(interno: 0)
        }
    }
}



struct ContoPosta: Codable, Hashable {
    let ok: Bool
    let totale: Int
    let frase: String
    let letto: String
    let caselle: [CasellaConto]
    let nuovi: [NuovoMittente]
}

struct CasellaConto: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let letta: Bool
    let in_arrivo: Int
    let non_lette: Int
    let oltre_un_mese: Int
    let altre_schede: Int
    let frase: String
}

struct NuovoMittente: Codable, Hashable, Identifiable {
    let casella: String
    let mittente: String
    let mail: Int
    let oggetto: String
    let proposta: String
    let perche: String

    var id: String { casella + "|" + mittente }
}


struct SchedaContoPosta: View {
    let posta: Posta
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: posta.t("posta_in_arrivo"), conteggio: store.contoPosta.map { "\($0.totale)" } ?? "") {
                if store.contoInLettura {
                    ProgressView().controlSize(.small).help(posta.t("aiuto_rileggi"))
                }
                Button(posta.t("rileggi")) { Task { await store.caricaContoPosta(rileggi: true) } }
                    .disabled(store.contoInLettura || store.modoIstantanea)
                    .help(posta.t("aiuto_rileggi"))
            }
            .help(posta.t("aiuto_posta_in_arrivo"))
            if let c = store.contoPosta {
                Text("\(c.frase) \(c.letto)").font(Testo.secondario).foregroundStyle(.secondary)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: Spazio.griglia, alignment: .top)],
                          alignment: .leading, spacing: Spazio.griglia) {
                    ForEach(c.caselle) { k in tessera(k) }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity).scheda()
            }
        }
    }

    private func tessera(_ k: CasellaConto) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(k.nome).font(Testo.nome)
                Spacer(minLength: Spazio.fratelli)
                Text("\(k.in_arrivo)").font(Testo.nome).monospacedDigit()
                    .foregroundStyle(k.in_arrivo == 0 ? .green : .primary)
                    .help(posta.t("aiuto_in_arrivo"))
            }
            Text(k.frase).font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .help("\(posta.t("aiuto_non_lette")) \(posta.t("aiuto_vecchie"))")
            if k.altre_schede > 0 {
                Text(posta.t("altre_schede").replacingOccurrences(of: "{n}", with: "\(k.altre_schede)")).font(Testo.minimo).foregroundStyle(.secondary)
                    .help(posta.t("aiuto_altre_schede"))
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .scheda(interno: 12)
    }
}



struct ElencoNuovi: View {
    let posta: Posta
    let conto: ContoPosta
    @Environment(Store.self) private var store
    @State private var altra: (NuovoMittente, CategoriaPosta)?
    @State private var mostraFoglio = false
    private let tetto = 60

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: posta.t("nuovi"), conteggio: "\(conto.nuovi.count)")
                .help(posta.t("aiuto_nuovi"))
            VStack(spacing: 0) {
                ForEach(Array(conto.nuovi.prefix(tetto).enumerated()), id: \.element.id) { i, n in
                    if i > 0 { Separatore().padding(.leading, 52) }
                    riga(n)
                }
            }
            .scheda(interno: 0)
            if conto.nuovi.count > tetto {
                Text(posta.t("troppi").replacingOccurrences(of: "{n}", with: "\(tetto)")
                    .replacingOccurrences(of: "{tot}", with: "\(conto.nuovi.count)"))
                    .font(Testo.secondario).foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $mostraFoglio) {
            if let (n, c) = altra { FoglioNuovoMittente(posta: posta, nuovo: n, verso: c) }
        }
    }

    private func riga(_ n: NuovoMittente) -> some View {
        let cat = posta.categorie.first(where: { $0.id == n.proposta })
        let casella = posta.caselle.first(where: { $0.id == n.casella })?.nome ?? n.casella
        return HStack(alignment: .top, spacing: 12) {
            TesseraIcona(simbolo: cat?.simbolo ?? "envelope.fill", colore: cat?.tinta ?? .gray, lato: 26)
                .help(cat?.aiuto ?? "")
            VStack(alignment: .leading, spacing: 2) {
                Text(n.mittente).font(Testo.corpo).lineLimit(1).truncationMode(.middle)
                Text("\(casella). \(n.oggetto)").font(Testo.secondario).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.tail)
                Text("\(cat?.nome ?? n.proposta). \(n.perche)").font(Testo.minimo).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            Text("\(n.mail) mail").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                .help(posta.t("aiuto_mail_in_arrivo"))
            Button(posta.t("conferma_proposta")) {
                Task { await store.confermaNuovo(n, verso: n.proposta, perche: n.perche) }
            }
            .disabled(store.postaInCorso || store.modoIstantanea)
            .help(posta.t("aiuto_conferma_proposta"))
            Menu {
                ForEach(posta.categorie.filter { $0.id != n.proposta }) { c in
                    Button(c.nome) { altra = (n, c); mostraFoglio = true }
                }
            } label: {
                Text(posta.t("foglio_titolo"))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .disabled(store.postaInCorso || store.modoIstantanea)
            .help(posta.t("aiuto_altra_categoria"))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}

struct FoglioNuovoMittente: View {
    let posta: Posta
    let nuovo: NuovoMittente
    let verso: CategoriaPosta
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi
    @State private var perche = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("\(posta.t("foglio_titolo")) \(nuovo.mittente)").font(Testo.titoloSezione)
            Text("\(posta.t("foglio_va_in")) \(verso.nome). \(verso.aiuto)")
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField(posta.t("foglio_perche"), text: $perche, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
            HStack {
                Spacer()
                Button(posta.t("foglio_annulla"), role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button(posta.t("foglio_sposta")) {
                    let n = nuovo
                    let c = verso.id
                    let p = perche
                    chiudi()
                    Task { await store.confermaNuovo(n, verso: c, perche: p) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(perche.trimmingCharacters(in: .whitespaces).isEmpty)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}
