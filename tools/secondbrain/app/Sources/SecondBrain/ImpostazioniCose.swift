import SwiftUI






struct PannelloImpostazioniCose: View {
    @Environment(Store.self) private var store
    @Environment(\.undoManager) private var undo
    @State private var sezione = Store.sezioneImpostazioni

    static let sezioni = ["stati", "aree", "veloci", "urgenti", "settimana"]
    static let simboli = ["stati": "circle.lefthalf.filled", "aree": "square.grid.2x2", "veloci": "hare",
                          "urgenti": "exclamationmark.circle", "settimana": "calendar"]

    var body: some View {
        Group {
            if let c = store.cose, c.stati != nil {
                HStack(spacing: 0) {
                    List(selection: Binding(get: { sezione }, set: { if let s = $0 { sezione = s } })) {
                        ForEach(Self.sezioni, id: \.self) { s in
                            Label(c.t("impostazioni_\(s)"), systemImage: Self.simboli[s] ?? "circle").tag(s)
                        }
                    }
                    .listStyle(.sidebar)
                    .frame(width: 170)
                    Divider()
                    VStack(spacing: 0) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            Text(c.t("impostazioni_\(sezione)")).font(Testo.titoloSezione)
                            Text(c.t("aiuto_impostazioni_\(sezione)")).font(.system(size: 12)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            switch sezione {
                            case "aree": SezioneAree(cose: c, store: store, fai: fai)
                            case "veloci": SezioneVeloci(cose: c, fai: fai)
                            case "urgenti": SezioneUrgenti(cose: c, fai: fai)
                            case "settimana": SezioneSettimana(cose: c, fai: fai)
                            default: SezioneStati(cose: c, store: store, fai: fai)
                            }
                        }
                        .padding(20)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if let e = store.coseEsitoImpostazioni, !e.testo.isEmpty {
                        Divider()
                        HStack(spacing: 8) {
                            Text(e.testo).font(.system(size: 12)).foregroundStyle(e.errore ? .primary : .secondary).lineLimit(2)
                            if e.annullabile, undo?.canUndo == true {
                                Button(c.t("annulla")) { undo?.undo() }.buttonStyle(.link).font(.system(size: 12))
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 20).padding(.vertical, 8)
                        .id(e.segno)
                    }
                    }
                }
            } else {

                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 640, minHeight: 460)
        .task { if store.cose == nil { await store.caricaCose() } }
        .onReceive(NotificationCenter.default.publisher(for: .apriImpostazioniAttivita)) { n in
            if let s = n.object as? String { sezione = s }
        }
    }


    private func fai(_ argomenti: [String]) {
        Task { await store.gestoVista(argomenti, undo: undo) }
    }
}




struct AperturaImpostazioni: View {
    @Environment(\.openSettings) private var apri
    static var provaImpostazioni = false
    static var aperture = 0
    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .onReceive(NotificationCenter.default.publisher(for: .apriImpostazioniAttivita)) { _ in
                if Self.provaImpostazioni { Self.aperture += 1 } else { apri() }
            }
    }
}



struct SezioneStati: View {
    let cose: Cose
    let store: Store
    let fai: ([String]) -> Void

    static var bozza = ""
    @State private var nuovo = SezioneStati.bozza
    @State private var tipoNuovo = "da_fare"
    @State private var areaDa = ""
    @State private var statoIn = ""

    var body: some View {
        let stati = (cose.stati ?? []).filter { $0.tolto != true }
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(stati.enumerated()), id: \.element.id) { i, s in
                RigaStato(cose: cose, stato: s, primo: i == 0, ultimo: i == stati.count - 1, fai: fai,
                          sposta: { passo in
                              var ids = stati.map(\.id)
                              let j = i + passo
                              guard j >= 0, j < ids.count else { return }
                              ids.swapAt(i, j)
                              fai(["stato-ordine", ids.joined(separator: ",")])
                          }, altri: stati.filter { $0.id != s.id })
            }
        }

        HStack(spacing: 8) {
            TextField(cose.t("stato_segnaposto"), text: $nuovo).textFieldStyle(.roundedBorder).frame(width: 200)
                .onChange(of: nuovo) { _, v in SezioneStati.bozza = v }
                .onSubmit(aggiungi)
            Picker("", selection: $tipoNuovo) {
                ForEach(cose.scelte_tipi ?? []) { t in Text(t.nome).tag(t.id) }
            }
            .labelsHidden().frame(width: 170)
            Button(cose.t("stato_nuovo"), action: aggiungi).disabled(nuovo.trimmingCharacters(in: .whitespaces).isEmpty)
        }

        let tolti = (cose.stati ?? []).filter { $0.tolto == true }
        if !tolti.isEmpty {
            Text(cose.t("stati_tolti")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary).padding(.top, 6)
            ForEach(tolti) { s in
                HStack {
                    SegnoStato(stato: s.id, dimensione: 13)
                    Text(s.nome).foregroundStyle(.secondary)
                    Spacer()
                    Button(cose.t("rimetti")) { fai(["stato-rimetti", s.id]) }.controlSize(.small)
                }
            }
        }

        Divider().padding(.vertical, 6)
        if let titolo = cose.testi?["titolo_stato_da_area"] {
            Text(titolo).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
        }
        let aree = cose.areeDiOwner.filter { ($0.n_aperte ?? 0) > 0 }
        let aperti = stati.filter { !$0.chiuso }
        HStack(spacing: 8) {
            Picker("", selection: $areaDa) {
                ForEach(aree) { a in Text(a.nome).tag(a.id) }
            }
            .labelsHidden().frame(width: 220)
            Picker("", selection: $statoIn) {
                ForEach(aperti) { s in Text(s.nome).tag(s.id) }
            }
            .labelsHidden().frame(width: 160)
            Button(cose.t("stato_da_area")
                .replacingOccurrences(of: "{stato}", with: aperti.first { $0.id == statoIn }?.nome ?? "…")
                .replacingOccurrences(of: "{area}", with: aree.first { $0.id == areaDa }?.nome ?? "…")) {
                fai(["stato-da-area", areaDa, statoIn])
            }
            .disabled(areaDa.isEmpty || statoIn.isEmpty)
            .help(cose.t("aiuto_stato_da_area"))
        }
        .onAppear {

            if areaDa.isEmpty { areaDa = aree.first?.id ?? "" }
            if statoIn.isEmpty { statoIn = (aperti.first { $0.tipo == "aspetta" } ?? aperti.first)?.id ?? "" }
        }
    }

    private func aggiungi() {
        let n = nuovo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        fai(["stato-nuovo", n, tipoNuovo])
        nuovo = ""
    }
}



struct RigaStato: View {
    let cose: Cose
    let stato: StatoDef
    let primo: Bool
    let ultimo: Bool
    let fai: ([String]) -> Void
    let sposta: (Int) -> Void
    let altri: [StatoDef]
    @State private var nome = ""
    @State private var inviato: String?
    @FocusState private var dentro: Bool

    var body: some View {
        HStack(spacing: 8) {
            Menu {
                ForEach(cose.scelte_segni?[stato.tipo] ?? [], id: \.self) { segno in

                    Button { fai(["stato-segno", stato.id, segno, stato.colore]) } label: { Image(systemName: segno) }
                }
                Divider()
                ForEach(cose.scelte_colori ?? []) { c in
                    Button(c.nome) { fai(["stato-segno", stato.id, stato.segno, c.id]) }
                }
            } label: {
                SegnoStato(stato: stato.id, dimensione: 15)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()

            TextField(cose.t("stato_segnaposto"), text: $nome)
                .textFieldStyle(.roundedBorder).frame(minWidth: 170, idealWidth: 240, maxWidth: 300)
                .focused($dentro)
                .onSubmit { salvaNome() }

                .onChange(of: dentro) { _, d in if !d { salvaNome() } }
            Picker("", selection: Binding(get: { stato.tipo }, set: { fai(["stato-tipo", stato.id, $0]) })) {
                ForEach(cose.scelte_tipi ?? []) { t in Text(t.nome).tag(t.id) }
            }
            .labelsHidden().fixedSize()
            .help(cose.t("aiuto_tipo_\(stato.tipo)"))

            Text(stato.chiuso ? "" : (stato.n_aperte ?? 0).formatted()).font(.system(size: 11)).monospacedDigit().foregroundStyle(.tertiary)
                .frame(width: 34, alignment: .trailing)
                .help(stato.chiuso ? "" : cose.t("aiuto_n_aperte").replacingOccurrences(of: "{n}", with: (stato.n_aperte ?? 0).formatted()))
            if !stato.chiuso {
                Toggle(cose.t("stato_per_le_nuove"), isOn: Binding(get: { stato.predefinito == true }, set: { si in
                    if si { fai(["stato-predefinito", stato.id]) }
                }))
                .toggleStyle(.checkbox).controlSize(.small).help(cose.t("aiuto_stato_per_le_nuove"))
            }
            Spacer(minLength: 4)
            Button { sposta(-1) } label: { Image(systemName: "chevron.up") }.buttonStyle(.borderless).disabled(primo)
            Button { sposta(1) } label: { Image(systemName: "chevron.down") }.buttonStyle(.borderless).disabled(ultimo)
            if (stato.n_aperte ?? 0) > 0 {
                Menu {
                    ForEach(altri.filter { !$0.chiuso }) { a in Button(a.nome) { fai(["stato-togli", stato.id, "--in", a.id]) } }
                } label: { Image(systemName: "minus.circle") }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
                .help(cose.testi?["togli_stato_in"] ?? cose.t("sposta_task_in"))
            } else {
                Button { fai(["stato-togli", stato.id]) } label: { Image(systemName: "minus.circle") }
                    .buttonStyle(.borderless).help(cose.t("togli_stato"))
            }
        }
        .onAppear { nome = stato.nome }

        .onChange(of: stato.nome) { _, n in nome = n; inviato = nil }
        .onDisappear { salvaNome() }
    }

    private func salvaNome() {
        let n = nome.trimmingCharacters(in: .whitespacesAndNewlines)
        if n.isEmpty || n == stato.nome { nome = stato.nome; return }

        guard n != inviato else { return }
        inviato = n
        fai(["stato-nome", stato.id, n])
    }
}



struct SezioneAree: View {
    let cose: Cose
    let store: Store
    let fai: ([String]) -> Void
    static var bozza = ""
    @State private var nuova = SezioneAree.bozza

    var body: some View {
        let aree = cose.areeDiOwner


        LazyVStack(alignment: .leading, spacing: 6) {
            ForEach(Array(aree.enumerated()), id: \.element.id) { i, a in
                RigaArea(cose: cose, area: a, primo: i == 0, ultimo: i == aree.count - 1, altre: aree.filter { $0.id != a.id },
                         fai: fai, sposta: { passo in
                             var ids = aree.map(\.id)
                             let j = i + passo
                             guard j >= 0, j < ids.count else { return }
                             ids.swapAt(i, j)
                             fai(["area-ordine", ids.joined(separator: ",")])
                         })
            }
        }
        HStack(spacing: 8) {
            TextField(cose.t("area_segnaposto"), text: $nuova).textFieldStyle(.roundedBorder).frame(width: 220)
                .onChange(of: nuova) { _, v in SezioneAree.bozza = v }
                .onSubmit(aggiungi)
            Button(cose.t("area_nuova").trimmingCharacters(in: CharacterSet(charactersIn: "…")), action: aggiungi)
                .disabled(nuova.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        let fuori = (cose.aree_def ?? []).filter { $0.tolta == true || $0.unita_in != nil }
        if !fuori.isEmpty {
            Text(cose.t("aree_tolte")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary).padding(.top, 6)
            ForEach(fuori) { a in
                HStack {
                    Text(a.nome).foregroundStyle(.secondary)
                    Spacer()
                    if a.unita_in != nil {
                        Button(cose.t("separa_area")) { fai(["area-separa", a.id]) }.controlSize(.small)
                    } else {
                        Button(cose.t("rimetti")) { fai(["area-rimetti", a.id]) }.controlSize(.small)
                    }
                }
            }
        }
    }

    private func aggiungi() {
        let n = nuova.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        fai(["area-nuova", n])
        nuova = ""
    }
}

struct RigaArea: View {
    let cose: Cose
    let area: AreaDef
    let primo: Bool
    let ultimo: Bool
    let altre: [AreaDef]
    let fai: ([String]) -> Void
    let sposta: (Int) -> Void
    @State private var nome = ""
    @State private var inviato: String?
    @FocusState private var dentro: Bool

    var body: some View {
        HStack(spacing: 8) {
            Menu {
                ForEach(cose.scelte_colori ?? []) { c in Button(c.nome) { fai(["area-colore", area.id, c.id]) } }
                Divider()
                Button(cose.t("colore_nessuno")) { fai(["area-colore", area.id, "togli"]) }
            } label: {
                Circle().fill(area.colore.map { SegnoStato.colore($0) } ?? Color.secondary.opacity(0.25)).frame(width: 11, height: 11)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            TextField(cose.t("area_segnaposto"), text: $nome).textFieldStyle(.roundedBorder).frame(width: 200)
                .focused($dentro)
                .onSubmit { salvaNome() }
                .onChange(of: dentro) { _, d in if !d { salvaNome() } }
            Text((area.n_aperte ?? 0).formatted()).font(.system(size: 11)).monospacedDigit().foregroundStyle(.tertiary)
                .frame(width: 34, alignment: .trailing)
                .help(cose.t("aiuto_n_aperte").replacingOccurrences(of: "{n}", with: (area.n_aperte ?? 0).formatted()))
            Menu(cose.t("unisci_area")) {
                ForEach(altre) { b in Button(b.nome) { fai(["area-unisci", area.id, b.id]) } }
            }
            .fixedSize().controlSize(.small).help(cose.t("aiuto_unisci_area"))
            Spacer(minLength: 4)
            Button { sposta(-1) } label: { Image(systemName: "chevron.up") }.buttonStyle(.borderless).disabled(primo)
            Button { sposta(1) } label: { Image(systemName: "chevron.down") }.buttonStyle(.borderless).disabled(ultimo)
            if (area.n ?? 0) > 0 {
                Menu {
                    ForEach(altre) { b in Button(b.nome) { fai(["area-togli", area.id, "--in", b.id]) } }
                    Divider()
                    Button(cose.t("senza_area")) { fai(["area-togli", area.id, "--senza"]) }
                } label: { Image(systemName: "minus.circle") }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
                .help(cose.testi?["togli_area_in"] ?? cose.t("sposta_task_in"))
            } else {
                Button { fai(["area-togli", area.id]) } label: { Image(systemName: "minus.circle") }
                    .buttonStyle(.borderless).help(cose.t("togli_area"))
            }
        }
        .onAppear { nome = area.nome }
        .onChange(of: area.nome) { _, n in nome = n; inviato = nil }
        .onDisappear { salvaNome() }
    }

    private func salvaNome() {
        let n = nome.trimmingCharacters(in: .whitespacesAndNewlines)
        if n.isEmpty || n == area.nome { nome = area.nome } else if n != inviato { inviato = n; fai(["area-nome", area.id, n]) }
    }
}





struct AppenaChiesto: ViewModifier {
    @Environment(Store.self) private var store
    @Binding var appena: [String: Int]
    let salvati: [Int]
    func body(content: Content) -> some View {
        content
            .onChange(of: salvati) { appena = [:] }
            .onChange(of: store.coseEsitoImpostazioni?.segno) { if store.coseEsitoImpostazioni?.errore == true { appena = [:] } }
    }
}

struct SezioneVeloci: View {
    let cose: Cose
    let fai: ([String]) -> Void
    @State private var appena: [String: Int] = [:]
    var body: some View {
        let salvato = cose.impostazioni?.veloci_minuti ?? 30
        let m = appena["veloci"] ?? salvato
        HStack(spacing: 10) {
            Text(cose.t("filtro_veloci").replacingOccurrences(of: "{quanto}", with: SommaTempo.breve(m, cose)))
            Stepper("", value: Binding(get: { m }, set: { v in
                        appena["veloci"] = max(5, v)
                        fai(["imposta", "veloci_minuti", String(max(5, v))])
                    }), in: 5...480, step: 5)
                .labelsHidden()
        }
        .modifier(AppenaChiesto(appena: $appena, salvati: [salvato]))
    }
}

struct SezioneUrgenti: View {
    let cose: Cose
    let fai: ([String]) -> Void
    @State private var appena: [String: Int] = [:]
    var body: some View {

        let salvato = cose.impostazioni?.urgenti ?? .init(p1: true, giorni_prima: 6, giorni_dopo: 7)
        let u = ImpostazioniAttivita.Urgenti(p1: salvato.p1, giorni_prima: appena["prima"] ?? salvato.giorni_prima,
                                             giorni_dopo: appena["dopo"] ?? salvato.giorni_dopo)
        let manda = { (p1: Bool, prima: Int, dopo: Int) in
            appena["prima"] = prima
            appena["dopo"] = dopo
            fai(["imposta", "urgenti", "{\"p1\": \(p1), \"giorni_prima\": \(prima), \"giorni_dopo\": \(dopo)}"])
        }
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
            GridRow {
                Toggle(cose.t("urgenti_p1"), isOn: Binding(get: { u.p1 }, set: { manda($0, u.giorni_prima, u.giorni_dopo) }))
                    .toggleStyle(.checkbox).gridCellColumns(2)
            }
            GridRow {
                Text(cose.t("urgenti_giorni_prima"))
                Stepper("\(u.giorni_prima.formatted())", value: Binding(get: { u.giorni_prima }, set: { manda(u.p1, max(0, $0), u.giorni_dopo) }),
                        in: 0...60)
            }
            GridRow {
                Text(cose.t("urgenti_giorni_dopo"))
                Stepper("\(u.giorni_dopo.formatted())", value: Binding(get: { u.giorni_dopo }, set: { manda(u.p1, u.giorni_prima, max(0, $0)) }),
                        in: 0...60)
            }
        }
        .modifier(AppenaChiesto(appena: $appena, salvati: [salvato.giorni_prima, salvato.giorni_dopo]))
    }
}

struct SezioneSettimana: View {
    let cose: Cose
    let fai: ([String]) -> Void
    @State private var appena: [String: Int] = [:]
    var body: some View {
        let s = cose.impostazioni?.settimana ?? .init(inizio: 0, giorni: [0, 1, 2, 3, 4], dalle: "09:00", alle: "19:00", giornata_minuti: 480)
        let nomi = cose.giorni_lunghi ?? []

        let manda = { (json: String) in fai(["imposta", "settimana", json]) }
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
            GridRow {
                Text(cose.t("settimana_inizio"))
                Picker("", selection: Binding(get: { s.inizio }, set: { manda("{\"inizio\": \($0)}") })) {
                    ForEach(Array(nomi.enumerated()), id: \.offset) { i, n in Text(n).tag(i) }
                }
                .labelsHidden().frame(width: 160)
            }
            GridRow {
                Text(cose.t("settimana_giorni"))
                HStack(spacing: 6) {
                    ForEach(Array(nomi.enumerated()), id: \.offset) { i, n in

                        Toggle(cose.giorni_brevi.map { i < $0.count ? $0[i] : "" } ?? String(n.prefix(3)), isOn: Binding(get: { s.giorni.contains(i) }, set: { si in
                            var g = Set(s.giorni)
                            if si { g.insert(i) } else { g.remove(i) }
                            manda("{\"giorni\": [\(g.sorted().map(String.init).joined(separator: ", "))]}")
                        }))
                        .toggleStyle(.button).controlSize(.small)
                    }
                }
            }
            GridRow {
                Text(cose.t("settimana_dalle"))
                Picker("", selection: Binding(get: { s.dalle }, set: { manda("{\"dalle\": \"\($0)\"}") })) {
                    ForEach(Self.ore, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().frame(width: 100)
            }
            GridRow {
                Text(cose.t("settimana_alle"))
                Picker("", selection: Binding(get: { s.alle }, set: { manda("{\"alle\": \"\($0)\"}") })) {
                    ForEach(Self.ore, id: \.self) { Text($0).tag($0) }
                }
                .labelsHidden().frame(width: 100)
            }
            GridRow {
                Text(cose.t("settimana_giornata"))
                Stepper(SommaTempo.breve(appena["giornata"] ?? s.giornata_minuti, cose),
                        value: Binding(get: { appena["giornata"] ?? s.giornata_minuti }, set: { v in
                            appena["giornata"] = max(60, v)
                            manda("{\"giornata_minuti\": \(max(60, v))}")
                        }), in: 60...960, step: 30)
            }
        }
        .modifier(AppenaChiesto(appena: $appena, salvati: [s.giornata_minuti]))
    }


    static let ore: [String] = (0..<48).map { String(format: "%02d:%02d", $0 / 2, ($0 % 2) * 30) }
}
