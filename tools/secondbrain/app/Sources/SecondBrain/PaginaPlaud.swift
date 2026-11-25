import AppKit
import Charts
import SwiftUI





struct PaginaPlaud: View {
    let stato: Stato
    @Environment(Store.self) private var store
    private var plaud: PlaudStore { PlaudStore.condiviso }

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: plaud.dati?.t("titolo") ?? "Plaud",
                         sottotitolo: plaud.dati?.t("sottotitolo") ?? "") {
            if let p = plaud.dati {
                TestaPlaud(p: p)
                switch plaud.modulo {
                case "metodo": ModuloMetodo(p: p)
                case "da_nominare": ModuloDaNominare(p: p)
                case "fuori": ModuloFuori(p: p)
                case "perche": ModuloPerche(p: p)
                case "attivita": ModuloAttivita(p: p)
                default: ModuloQuadro(p: p)
                }
            } else if let e = plaud.errore {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: Simbolo.attenzione).foregroundStyle(Salute.attenzione.colore)
                    Text(e).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: Spazio.fratelli)

                    Button(plaud.t("rileggi")) { Task { await plaud.carica(store, forza: true) } }
                        .disabled(plaud.inLettura || store.modoIstantanea)
                        .help(plaud.t("aiuto_rileggi"))
                }
                .scheda()
            } else {
                ProgressView().frame(maxWidth: .infinity).scheda()
            }
        }
        .task { await plaud.carica(store) }
    }
}



struct TestaPlaud: View {
    let p: Plaud
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var plaud = PlaudStore.condiviso
        ViewThatFits(in: .horizontal) {
            HStack(spacing: Spazio.griglia) {
                scelta($plaud.modulo)
                Spacer(minLength: Spazio.fratelli)
                lettura
            }
            VStack(alignment: .leading, spacing: 8) {
                scelta($plaud.modulo)
                lettura
            }
        }
    }

    private func scelta(_ modulo: Binding<String>) -> some View {
        Picker(selection: modulo) {
            ForEach(p.moduli) { m in
                Text(m.nome).tag(m.id).help(m.aiuto)
            }
        } label: {
            EmptyView()
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .fixedSize()
    }

    private var lettura: some View {
        HStack(spacing: 6) {
            Text(p.letto).font(Testo.secondario).foregroundStyle(.secondary)
            if PlaudStore.condiviso.inLettura {
                ProgressView().controlSize(.small)
            } else {
                Button {
                    Task { await PlaudStore.condiviso.carica(store, forza: true) }
                } label: {
                    Image(systemName: Simbolo.aggiorna)
                }
                .buttonStyle(.borderless)
                .disabled(store.modoIstantanea)
                .help(p.t("aiuto_rileggi"))
            }
        }
        .fixedSize()
    }
}





enum TintaPlaud {
    static let accento = Color.accentColor

    static let neutro = Color.dinamico(chiaro: NSColor(white: 0.82, alpha: 1), scuro: NSColor(white: 0.36, alpha: 1))
    static let arancio = Color.dinamico(chiaro: NSColor(srgbRed: 0.93, green: 0.69, blue: 0.45, alpha: 1),
                                        scuro: NSColor(srgbRed: 0.80, green: 0.55, blue: 0.32, alpha: 1))
    static let rosa = Color.dinamico(chiaro: NSColor(srgbRed: 0.91, green: 0.62, blue: 0.58, alpha: 1),
                                     scuro: NSColor(srgbRed: 0.75, green: 0.45, blue: 0.42, alpha: 1))


    static func livello(_ id: String) -> Color {
        switch id {
        case "confermato": accento
        case "solido": accento.opacity(0.72)
        case "una_prova": accento.opacity(0.45)
        case "solo_nome": accento.opacity(0.22)
        case "sospetto": arancio
        case "smentito": rosa
        default: neutro
        }
    }

    private static func c(_ esa: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((esa >> 16) & 0xff) / 255, green: CGFloat((esa >> 8) & 0xff) / 255,
                blue: CGFloat(esa & 0xff) / 255, alpha: 1)
    }


    static func pillola(_ tinta: String) -> (fondo: Color, testo: Color) {
        switch tinta {
        case "verde": (Color.dinamico(chiaro: c(0xDDF1E2), scuro: c(0x1F3D27)), Color.dinamico(chiaro: c(0x1E6B34), scuro: c(0x9FDDB0)))
        case "blu": (Color.dinamico(chiaro: c(0xDCE8FB), scuro: c(0x1E3352)), Color.dinamico(chiaro: c(0x1F4E99), scuro: c(0xA9C8F5)))
        case "arancio": (TintaPriorita.fondo(1), TintaPriorita.testo(1))
        default: (TintaPriorita.fondo(3), TintaPriorita.testo(3))
        }
    }
}



struct ModuloQuadro: View {
    let p: Plaud

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.sezioni) {
            obiettivo
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: p.t("numeri"))
                GrigliaNumeri(numeri: p.numeri)
            }
            livelli
            if let f = p.fiducia, !f.isEmpty { fiducia(f) }
            if let i = p.indizi, !i.isEmpty { indizi(i) }
            mesi
            storia
        }
    }

    private var obiettivo: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(p.t("obiettivo")).font(Testo.secondario.weight(.semibold)).foregroundStyle(TintaPlaud.accento)
            Text(p.obiettivo.frase).font(.title3.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            if !p.obiettivo.parole_di_owner.isEmpty {
                Text("«\(p.obiettivo.parole_di_owner)»").italic().font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !p.obiettivo.metodo.isEmpty {
                Text(p.obiettivo.metodo).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .help(p.t("metodo"))
            }
        }
        .scheda(tinta: TintaPlaud.accento)
    }

    private var livelli: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("livelli")).help(p.t("aiuto_livelli"))
            VStack(alignment: .leading, spacing: 14) {
                BarraLivelli(livelli: p.livelli)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 12, alignment: .topLeading)],
                          alignment: .leading, spacing: 10) {
                    ForEach(p.livelli) { lv in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            RoundedRectangle(cornerRadius: 3).fill(TintaPlaud.livello(lv.id))
                                .frame(width: 12, height: 12)
                                .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                            VStack(alignment: .leading, spacing: 1) {
                                HStack(spacing: 6) {
                                    Text(lv.nome).font(Testo.nome)
                                    Text(lv.pct).font(Testo.cifreInColonna).foregroundStyle(.secondary)
                                }
                                Text(lv.cifre).font(Testo.secondario).foregroundStyle(.secondary).monospacedDigit()
                            }
                        }
                        .help(lv.aiuto)
                    }
                }
            }
            .scheda()
        }
    }


    private func fiducia(_ fasce: [FasciaFiduciaPlaud]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("fiducia")).help(p.t("aiuto_fiducia"))
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 10) {
                ForEach(fasce) { f in
                    GridRow(alignment: .center) {
                        Text(f.fascia).font(Testo.nome)
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Superficie.traccia)
                                Capsule().fill(TintaPlaud.accento.opacity([1, 0.72, 0.45, 0.25][min(max(f.livello, 0), 3)]))
                                    .frame(width: max(4, geo.size.width * f.frazione))
                            }
                        }
                        .frame(height: 10)
                        Text(f.speaker).font(Testo.cifreInColonna).foregroundStyle(.secondary)
                            .gridColumnAlignment(.trailing)
                    }
                }
            }
            .scheda()
        }
    }


    private func indizi(_ righe: [IndizioPlaud]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("indizi")).help(p.t("aiuto_indizi"))
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow {
                    Text(p.t("col_indizio"))
                    Text(p.t("col_partenza")).gridColumnAlignment(.trailing)
                    Text(p.t("col_giusti")).gridColumnAlignment(.trailing)
                    Text(p.t("col_sbagliati")).gridColumnAlignment(.trailing)
                    Text(p.t("col_peso")).gridColumnAlignment(.trailing)
                }
                .font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(righe) { x in
                    Divider()
                    GridRow(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(x.indizio).font(Testo.nome)
                            if !x.perche.isEmpty {
                                Text(x.perche).font(Testo.secondario).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Text(x.partenza).monospacedDigit().foregroundStyle(.secondary)
                        Text(x.giusti).monospacedDigit()
                        Text(x.sbagliati).monospacedDigit()
                        Text(x.peso).monospacedDigit().fontWeight(x.verificato ? .semibold : .regular)
                    }
                }
            }
            .scheda()
        }
    }

    private var mesi: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("per_mese")).help(p.t("aiuto_per_mese"))
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 14) {
                    Legenda(colore: TintaPlaud.neutro, testo: p.t("serie_senza_nome"))
                    Legenda(colore: TintaPlaud.accento, testo: p.t("serie_solidi"))
                }
                GraficoMesi(mesi: p.mesi, senzaNome: p.t("serie_senza_nome"), solidi: p.t("serie_solidi"))
                    .frame(height: 200)
            }
            .scheda()
        }
    }

    private var storia: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("storia"), conteggio: "\(p.storia_giri ?? p.storia.count)").help(p.t("aiuto_storia"))
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow {
                    ForEach(["col_quando", "col_senza_nome", "col_solidi", "col_sospetti", "col_verificate", "col_fuori"],
                            id: \.self) { k in
                        Text(p.t(k)).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    }
                }
                ForEach(p.storia) { g in
                    Divider()
                    GridRow {
                        Text(g.quando)
                        Text(g.senza_nome).monospacedDigit()
                        Text(g.solidi).monospacedDigit()
                        Text(g.sospetti).monospacedDigit()
                        Text(g.verificate).monospacedDigit()
                        Text(g.fuori).monospacedDigit()
                    }
                    GridRow {
                        Text(g.confronto).font(Testo.secondario).foregroundStyle(.secondary)
                            .gridCellColumns(6)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if let altri = p.storia_altri, !altri.isEmpty {
                    Divider()
                    GridRow {
                        Text(altri).font(Testo.secondario).foregroundStyle(.tertiary).gridCellColumns(6)
                    }
                }
            }
            .scheda()
        }
    }
}

struct GrigliaNumeri: View {
    let numeri: [NumeroPlaud]

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 12, alignment: .topLeading)],
                  alignment: .leading, spacing: 12) {
            ForEach(numeri) { n in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Cifra(testo: n.cifra)
                        if n.segnale == true {
                            Image(systemName: "info.circle").foregroundStyle(.secondary)
                        }
                    }
                    Text(n.parola).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
                .scheda(interno: 14)
                .help(n.aiuto)
            }
        }
    }
}


struct BarraLivelli: View {
    let livelli: [LivelloPlaud]

    var body: some View {
        GeometryReader { g in
            HStack(spacing: 1.5) {
                ForEach(livelli.filter { $0.frazione > 0 }) { lv in
                    Rectangle().fill(TintaPlaud.livello(lv.id))
                        .frame(width: max(2, (g.size.width - 1.5 * CGFloat(livelli.count)) * lv.frazione))
                        .help("\(lv.nome), \(lv.pct). \(lv.aiuto)")
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
        }
        .frame(height: 18)
    }
}

struct Legenda: View {
    let colore: Color
    let testo: String

    var body: some View {
        HStack(spacing: 5) {
            RoundedRectangle(cornerRadius: 2).fill(colore).frame(width: 10, height: 10)
            Text(testo).font(Testo.secondario).foregroundStyle(.secondary)
        }
    }
}


struct GraficoMesi: View {
    let mesi: [MesePlaud]
    let senzaNome: String
    let solidi: String

    var body: some View {
        Chart {
            ForEach(mesi) { m in
                BarMark(x: .value("mese", m.etichetta), y: .value("%", m.pct_senza_nome))
                    .foregroundStyle(TintaPlaud.neutro)
                    .position(by: .value("serie", senzaNome))
                BarMark(x: .value("mese", m.etichetta), y: .value("%", m.pct_solidi))
                    .foregroundStyle(TintaPlaud.accento)
                    .position(by: .value("serie", solidi))
            }
        }
        .chartYScale(domain: 0...100)
        .chartYAxis {
            AxisMarks(values: [0, 25, 50, 75, 100]) { v in
                AxisGridLine()
                AxisValueLabel { if let n = v.as(Int.self) { Text("\(n)%") } }
            }
        }
        .chartXAxis {
            AxisMarks { _ in AxisValueLabel(orientation: .verticalReversed) }
        }
        .chartLegend(.hidden)
    }
}




struct ModuloMetodo: View {
    let p: Plaud

    var body: some View {
        if let m = p.metodo {
            VStack(alignment: .leading, spacing: Spazio.sezioni) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(p.t("metodo_in_breve")).font(Testo.secondario.weight(.semibold))
                            .foregroundStyle(TintaPlaud.accento)
                        Spacer()
                        Text(m.aggiornato).font(Testo.secondario).foregroundStyle(.secondary)
                    }
                    Text(m.in_breve).font(.title3.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                }
                .scheda(tinta: TintaPlaud.accento)
                VStack(alignment: .leading, spacing: 10) {
                    TitoloGruppo(titolo: p.t("passi"), conteggio: "\(m.passi.count)").help(p.t("aiuto_passi"))
                    VStack(spacing: 0) {
                        ForEach(Array(m.passi.enumerated()), id: \.element.id) { i, x in
                            if i > 0 { Separatore().padding(.leading, 44) }
                            HStack(alignment: .firstTextBaseline, spacing: 12) {
                                Text("\(x.n)").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                                    .frame(width: 18, alignment: .trailing)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(x.passo).font(Testo.nome).fixedSize(horizontal: false, vertical: true)
                                    if !x.parole.isEmpty || !x.quando.isEmpty {
                                        (Text(x.parole).italic()
                                            + Text(x.quando.isEmpty ? "" : (x.parole.isEmpty ? x.quando : "  \(x.quando)"))
                                            .monospacedDigit())
                                            .font(Testo.secondario).foregroundStyle(.secondary)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                }
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 14)
                            .padding(.vertical, 9)
                        }
                    }
                    .scheda(interno: 0)
                }
                if !m.scoperte.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        TitoloGruppo(titolo: p.t("scoperte"), conteggio: "\(m.scoperte.count)").help(p.t("aiuto_scoperte"))
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(m.scoperte.enumerated()), id: \.offset) { _, s in
                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                    Image(systemName: "lightbulb").foregroundStyle(TintaPlaud.accento)
                                    Text(s).fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        .scheda()
                    }
                }
            }
        }
    }
}



struct ModuloDaNominare: View {
    let p: Plaud

    var body: some View {
        @Bindable var plaud = PlaudStore.condiviso
        let righe = plaud.righeFiltrate
        VStack(alignment: .leading, spacing: 12) {
            if let piano = p.da_nominare.piano, !piano.isEmpty {
                PianoNomi(p: p, piano: piano, totale: p.da_nominare.piano_totale)
                    .padding(.bottom, Spazio.griglia)
            }
            TitoloGruppo(titolo: p.t("da_nominare"), conteggio: Self.numero(righe.count)).help(p.t("aiuto_modulo_da_nominare"))
            VStack(alignment: .leading, spacing: 4) {
                Text(p.da_nominare.frase)
                Text(p.da_nominare.contesto).foregroundStyle(.secondary)
            }
            .font(Testo.secondario)
            .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Spazio.griglia) {
                TextField(p.t("cerca"), text: $plaud.cerca)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 340)
                    .onChange(of: plaud.cerca) { _, _ in plaud.mostrate = PlaudStore.passo }
                Toggle(p.t("con_indizi"), isOn: $plaud.soloIndizi)
                    .toggleStyle(.checkbox)
                    .help(p.t("aiuto_con_indizi"))
                    .onChange(of: plaud.soloIndizi) { _, _ in plaud.mostrate = PlaudStore.passo }
                Spacer(minLength: 0)
            }
            ElencoRegistrazioni(p: p, righe: Array(righe.prefix(plaud.mostrate)))
            if righe.count > plaud.mostrate {
                Button("\(p.t("mostra_altre")) \(min(PlaudStore.passo, righe.count - plaud.mostrate))") {
                    plaud.mostrate += PlaudStore.passo
                }
                .frame(maxWidth: .infinity)
            }
        }
    }



    static func numero(_ n: Int) -> String {
        var cifre = Array(String(n))
        var i = cifre.count - 3
        while i > 0 { cifre.insert(".", at: i); i -= 3 }
        return String(cifre)
    }
}


struct PianoNomi: View {
    let p: Plaud
    let piano: [GruppoPianoPlaud]
    let totale: TotalePianoPlaud?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("piano")).help(p.t("aiuto_piano"))
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 8) {
                GridRow {
                    Text(p.t("col_gruppo"))
                    Text(p.t("col_come"))
                    Text(p.t("col_voci")).gridColumnAlignment(.trailing)
                    Text(p.t("col_ore")).gridColumnAlignment(.trailing)
                }
                .font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(Array(piano.enumerated()), id: \.element.id) { i, g in
                    Divider()
                    GridRow(alignment: .firstTextBaseline) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text("\(i + 1)").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                            Text(g.gruppo).font(Testo.nome)
                        }
                        Text(g.come).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        Text(g.voci).monospacedDigit()
                        Text(g.ore).monospacedDigit()
                    }
                }
                if let totale {
                    Divider()
                    GridRow {
                        Text(p.t("totale")).font(Testo.nome)
                        Text("")
                        Text(totale.voci).monospacedDigit().fontWeight(.semibold)
                        Text(totale.ore).monospacedDigit().fontWeight(.semibold)
                    }
                }
            }
            .scheda()
        }
    }
}


struct ElencoRegistrazioni: View {
    let p: Plaud
    let righe: [RegistrazionePlaud]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(righe.enumerated()), id: \.element.id) { i, r in
                if i > 0 { Separatore().padding(.leading, 14) }
                RigaRegistrazione(p: p, r: r)
            }
            if righe.isEmpty {
                Text(p.t("nessuna")).font(Testo.secondario).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
            }
        }
        .scheda(interno: 0)
    }
}

struct RigaRegistrazione: View {
    let p: Plaud
    let r: RegistrazionePlaud
    @State private var sopra = false

    var body: some View {
        Button {
            if let url = URL(string: r.link) { NSWorkspace.shared.open(url) }
        } label: {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(r.titolo).font(Testo.nome).lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Text([r.data, r.durata, r.fonte].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(Testo.secondario).foregroundStyle(.secondary)
                    Text(r.contesto.isEmpty ? p.t("senza_contesto") : r.contesto)
                        .font(Testo.secondario)
                        .foregroundStyle(r.contesto.isEmpty ? .tertiary : .secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    if r.una_voce_sola {
                        HStack(spacing: 5) {
                            Image(systemName: "person.wave.2")
                            Text(p.t("una_voce_sola"))
                        }
                        .font(Testo.secondario)
                        .foregroundStyle(TintaPriorita.testo(1))
                        .help(p.t("aiuto_una_voce_sola"))
                    }
                    if !r.indizi.isEmpty {
                        (Text("\(p.t("nel_testo"))  ").foregroundStyle(.secondary) + Text(r.indizi))
                            .font(Testo.secondario)
                            .lineLimit(1)
                            .help(p.t("aiuto_nel_testo"))
                    }
                }
                Spacer(minLength: Spazio.fratelli)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(r.numeri).font(Testo.secondario).monospacedDigit().foregroundStyle(.secondary)
                        .multilineTextAlignment(.trailing)
                    Image(systemName: "arrow.up.right.square")
                        .foregroundStyle(sopra ? TintaPlaud.accento : Color.secondary)
                }
                .fixedSize()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .contentShape(Rectangle())
            .background(sopra ? Superficie.incasso : Color.clear)
        }
        .buttonStyle(.plain)
        .onHover { sopra = $0 }
        .help(p.t("aiuto_apri"))
    }
}



struct ModuloFuori: View {
    let p: Plaud

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.sezioni) {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: p.t("modulo_fuori")).help(p.t("aiuto_modulo_fuori"))
                Text(p.fuori.frase).font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                GrigliaNumeri(numeri: p.fuori.numeri)
            }
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: p.t("piu_lunghe_fuori"), conteggio: "\(p.fuori.righe.count)")
                    .help(p.t("aiuto_piu_lunghe_fuori"))
                ElencoRegistrazioni(p: p, righe: p.fuori.righe)
            }
        }
    }
}



struct ModuloPerche: View {
    let p: Plaud

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.sezioni) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text(p.t("in_breve")).font(Testo.secondario.weight(.semibold)).foregroundStyle(TintaPlaud.accento)
                    Spacer()
                    Text(p.perche.aggiornato).font(Testo.secondario).foregroundStyle(.secondary)
                }
                Text(p.perche.in_breve).font(.title3.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            }
            .scheda(tinta: TintaPlaud.accento)
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: p.t("fatti"), conteggio: "\(p.perche.fatti.count)")
                VStack(spacing: 0) {
                    ForEach(Array(p.perche.fatti.enumerated()), id: \.offset) { i, f in
                        if i > 0 { Separatore().padding(.leading, 44) }
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text("\(i + 1)").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                                .frame(width: 18, alignment: .trailing)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(f.cosa).fixedSize(horizontal: false, vertical: true)
                                if !f.prova.isEmpty {
                                    (Text("\(p.t("prova"))  ").fontWeight(.medium) + Text(f.prova))
                                        .font(Testo.secondario).foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 9)
                    }
                }
                .scheda(interno: 0)
            }
            if !p.perche.aperto.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    TitoloGruppo(titolo: p.t("aperto"), conteggio: "\(p.perche.aperto.count)")
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(p.perche.aperto.enumerated()), id: \.offset) { _, a in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Image(systemName: "questionmark.circle").foregroundStyle(.secondary)
                                Text(a).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .scheda()
                }
            }
            if !p.perche.conseguenza.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    TitoloGruppo(titolo: p.t("conseguenza"))
                    Text(p.perche.conseguenza).fixedSize(horizontal: false, vertical: true)
                        .scheda()
                }
            }
        }
    }
}



struct ModuloAttivita: View {
    let p: Plaud

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: p.t("attivita"), conteggio: "\(p.attivita.count)").help(p.t("aiuto_attivita"))
            VStack(spacing: 0) {
                ForEach(Array(p.attivita.enumerated()), id: \.element.id) { i, a in
                    if i > 0 { Separatore().padding(.leading, 44) }
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("\(a.n)").font(Testo.cifreInColonna).foregroundStyle(.secondary)
                            .frame(width: 18, alignment: .trailing)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(a.cosa).fixedSize(horizontal: false, vertical: true)
                            let sotto = [a.esito, a.quando].filter { !$0.isEmpty }.joined(separator: " · ")
                            if !sotto.isEmpty {
                                Text(sotto).font(Testo.secondario).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: Spazio.fratelli)
                        PillolaStato(testo: a.stato, tinta: a.tinta)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 9)
                }
            }
            .scheda(interno: 0)
        }
    }
}

struct PillolaStato: View {
    let testo: String
    let tinta: String

    var body: some View {
        let c = TintaPlaud.pillola(tinta)
        Text(testo)
            .font(Testo.distintivo)
            .foregroundStyle(c.testo)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(c.fondo, in: Capsule())
            .fixedSize()
    }
}
