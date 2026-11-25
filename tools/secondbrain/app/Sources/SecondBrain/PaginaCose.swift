import SwiftUI









struct PaginaCose: View {
    let stato: Stato
    @Environment(Store.self) private var store
    @Environment(\.undoManager) private var undo
    @Environment(\.accessibilityReduceMotion) private var ridotto
    @FocusState private var fuoco: FuocoCose?
    @State private var larghezza: CGFloat = 1000

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Fasce(stato: stato)

            if store.motoreVecchio || ProcessInfo.processInfo.environment["SB_MOTORE_VECCHIO"] == "1" {
                Fascia(salute: .attenzione, testo: store.cose?.testi?["motore_altra_versione"] ?? Store.fraseMotoreVecchio,
                       dettaglio: nil) { EmptyView() }
            }
            if let c = store.cose {
                TestataCose(cose: c, store: store)
                HStack(spacing: 0) {
                    VStack(spacing: 0) {
                        BarraScheda(cose: c, store: store, fuoco: $fuoco)
                        Rectangle().fill(fuoco == .nuova ? Color.accentColor : Superficie.separatore)
                            .frame(height: fuoco == .nuova ? 1 : 0.5)
                            .animation(.easeOut(duration: 0.15), value: fuoco == .nuova)
                        contenuto(c)
                            .transition(.opacity)
                            .animation(.easeInOut(duration: 0.15), value: store.schedaCose?.modo)
                            .conVoce(store: store)
                        Rectangle().fill(Superficie.separatore).frame(height: 0.5)
                        RigaEsitoCose(store: store)
                    }
                    .frame(minWidth: 0, maxWidth: .infinity)
                    if store.dettaglioCose {
                        Rectangle().fill(Superficie.separatore).frame(width: 1)
                        DettaglioCose(cose: c, store: store, fuoco: $fuoco)
                            .frame(width: larghezza < 1000 ? 320 : 360)
                            .clipped()
                            .frame(maxHeight: .infinity, alignment: .topLeading)
                            .transition(ridotto ? .opacity : .move(edge: .trailing).combined(with: .opacity))
                    }
                }
                .animation(ridotto ? .easeInOut(duration: 0.15) : .smooth(duration: 0.25), value: store.dettaglioCose)
                .clipShape(RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous))
                .scheda(interno: 0)
            } else if let e = store.erroreCose {
                Fascia(salute: .attenzione, testo: e, dettaglio: nil) {
                    Button(store.t("riprova")) { Task { await store.caricaCose(rileggi: true) } }
                        .disabled(store.coseInLettura || store.modoIstantanea)
                }
                Spacer()
            } else {
                RigheFerme()
            }
        }
        .padding(.horizontal, 28)
        .padding(.top, 18)
        .padding(.bottom, 16)
        .frame(minWidth: 380, idealWidth: 560, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezza = $0 }
        .task { await store.apriCose() }
        .task { await store.caricaVoce(); store.seguiVoce() }
        .onAppear { store.coseUndo = undo }
        .onChange(of: undo) { _, nuovo in store.coseUndo = nuovo }
        .onChange(of: fuoco, initial: true) { _, f in
            store.coseCampoAttivo = [.nuova, .cerca, .titolo, .descrizione].contains(f)
        }
        .onChange(of: store.coseFuocoChiesto, initial: true) { _, chiesto in
            guard let chiesto else { return }
            fuoco = chiesto
            store.coseFuocoChiesto = nil
        }
        .sheet(isPresented: Binding(get: { store.coseDataPer != nil }, set: { if !$0 { store.coseDataPer = nil } })) {
            if let c = store.cose, let ids = store.coseDataPer { FoglioDataCosa(cose: c, ids: ids, store: store) }
        }
        .sheet(isPresented: Binding(get: { store.coseNuovaAreaPer != nil }, set: { if !$0 { store.coseNuovaAreaPer = nil } })) {
            if let c = store.cose, let ids = store.coseNuovaAreaPer { FoglioNuovaArea(cose: c, ids: ids, store: store) }
        }
        .sheet(isPresented: Binding(get: { store.coseTempoPer != nil }, set: { if !$0 { store.coseTempoPer = nil } })) {
            if let c = store.cose, let ids = store.coseTempoPer { FoglioTempo(cose: c, ids: ids, store: store) }
        }
        .onExitCommand { esc() }
        .onChange(of: store.coseVista, initial: true) { _, _ in store.applicaOrdineSalvato() }
    }

    @ViewBuilder
    private func contenuto(_ c: Cose) -> some View {
        switch store.schedaCose?.modo {
        case "bacheca": BachecaCose(cose: c, store: store)
        case "calendario": CalendarioScala(cose: c, store: store)


        case "foglio": TabellaCose(cose: c, store: store, fuoco: $fuoco, foglio: true).id("foglio")
        default: TabellaCose(cose: c, store: store, fuoco: $fuoco)
        }
    }


    private func esc() {

        let reg = Registratore.condiviso
        if reg.voce == Registrazione.attivita && reg.stato == .registra { reg.annulla(); return }
        if StatoConversazione.condiviso.aperta { StatoConversazione.condiviso.aperta = false; return }
        if store.dettaglioCose { store.dettaglioCose = false; fuoco = .tabella; return }
        if !store.coseScelte.isEmpty { store.coseScelte = []; return }
        if !store.coseCerca.isEmpty { store.coseCerca = "" }
    }
}





struct TestataCose: View {
    let cose: Cose
    let store: Store
    @Namespace private var spazio
    @Environment(\.accessibilityReduceMotion) private var ridotto
    @State private var larghezza: CGFloat = 900
    @State private var rinomino: String?
    @State private var nome = ""
    @FocusState private var nomeAttivo: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 18) {
                Text(cose.t("titolo")).font(.system(size: 26, weight: .bold))
                    .fixedSize()
                    .help(cose.t("sottotitolo"))
                let (dentro, fuori) = divise()
                HStack(alignment: .center, spacing: 18) {
                    ForEach(dentro) { s in scheda(s) }
                    if store.vistaSpeciale, let s = store.schedaCose { scheda(s) }
                    if !fuori.isEmpty {
                        Menu {
                            ForEach(fuori) { s in Button(s.nome) { store.coseVista = s.id } }
                        } label: {
                            Text(cose.t("altre_viste")).font(.system(size: 13)).foregroundStyle(.secondary)
                        }
                        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.visible).fixedSize()
                        .help(cose.t("aiuto_altre_viste"))
                    }
                    menuNuova
                }
                .fixedSize()
                Spacer(minLength: 8)
                TastoFatte(cose: cose, store: store)
                TastoGruppi(cose: cose, store: store)
                MenuFiltra(cose: cose, store: store)
                MostraCose(cose: cose, store: store)
            }
            .frame(height: 36)
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezza = $0 }
            if !store.coseFiltroAlVolo.values.allSatisfy(\.isEmpty) {
                Pastiglie(cose: cose, store: store)
            }
        }
    }



    private func divise() -> ([SchedaCose], [SchedaCose]) {
        let schede = store.schedeVisibili

        let titolo = (cose.t("titolo") as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 26, weight: .bold)]).width
        let fisso: CGFloat = titolo + 18 + 22 + 18 + 144 + 16
        var resta = larghezza - fisso
        func misura(_ s: SchedaCose) -> CGFloat {
            let f = NSFont.systemFont(ofSize: 13, weight: .semibold)
            var w = (s.nome as NSString).size(withAttributes: [.font: f]).width + 18
            if s.modo != "tabella" { w += 18 }
            if (s.modo == "tabella" || s.modo == "foglio"), s.numero > 0 { w += CGFloat(s.numero.formatted().count) * 7 + 5 }
            return w
        }

        let altre = (cose.t("altre_viste") as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 13)]).width + 14 + 18
        let larghe = schede.map(misura)

        if larghe.reduce(0, +) <= resta { return (schede, []) }
        let aperta = schede.firstIndex { $0.id == store.coseVista }
        var budget = resta - altre - (aperta.map { larghe[$0] } ?? 0)
        var dentro: [SchedaCose] = []
        var fuori: [SchedaCose] = []
        for (i, s) in schede.enumerated() {
            if i == aperta { dentro.append(s); continue }
            if fuori.isEmpty && larghe[i] <= budget {
                dentro.append(s)
                budget -= larghe[i]
            } else {
                fuori.append(s)
            }
        }
        return (dentro, fuori)
    }

    @ViewBuilder
    private func scheda(_ s: SchedaCose) -> some View {
        let scelta = store.coseVista == s.id
        if rinomino == s.id {
            TextField("", text: $nome)
                .textFieldStyle(.roundedBorder).font(.system(size: 13)).frame(width: 150)
                .focused($nomeAttivo)
                .onSubmit { salvaNome(s) }
                .onExitCommand { rinomino = nil }
                .onAppear { nomeAttivo = true }
                .onChange(of: nomeAttivo) { _, attivo in if !attivo && rinomino == s.id { salvaNome(s) } }
        } else {
            Button {
                withAnimation(Movimento.cambio(ridotto)) { store.coseVista = s.id }
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    if s.modo == "bacheca" { Image(systemName: "rectangle.split.3x1").font(.system(size: 11)) }
                    if s.modo == "calendario" { Image(systemName: "calendar").font(.system(size: 11)) }
                    if s.modo == "foglio" { Image(systemName: "tablecells").font(.system(size: 11)) }
                    Text(s.nome).font(.system(size: 13, weight: scelta ? .semibold : .regular))
                    if s.modo == "tabella" || s.modo == "foglio", s.numero > 0 {
                        Text(s.numero.formatted()).font(.system(size: 11)).monospacedDigit()
                            .foregroundStyle(.secondary).contentTransition(.numericText())
                    }
                    if scelta && !store.coseFiltroAlVolo.values.allSatisfy(\.isEmpty) {
                        Circle().fill(Color.accentColor).frame(width: 5, height: 5).help(cose.t("aiuto_vista_cambiata"))
                    }
                }
                .foregroundStyle(scelta ? Color.primary : Color.secondary)
                .padding(.vertical, 5)
                .overlay(alignment: .bottom) {
                    if scelta {
                        Capsule().fill(Color.accentColor).frame(height: 2).offset(y: 5)
                            .matchedGeometryEffect(id: "vista", in: spazio)
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(s.aiuto)
            .simultaneousGesture(TapGesture(count: 2).onEnded { if !store.vistaSpeciale { inizia(s) } })
            .contextMenu { if !store.vistaSpeciale(s.id) { menuScheda(s) } }
            .draggable("vista:" + s.id)
            .dropDestination(for: String.self) { valori, _ in
                guard let v = valori.first, v.hasPrefix("vista:") else { return false }
                riordina(String(v.dropFirst(6)), prima: s.id)
                return true
            }
        }
    }

    private func inizia(_ s: SchedaCose) {
        nome = s.nome
        rinomino = s.id
    }

    private func salvaNome(_ s: SchedaCose) {
        let testo = nome.trimmingCharacters(in: .whitespaces)
        rinomino = nil
        guard testo != s.nome, !(testo.isEmpty && s.pronta == nil) else { return }
        Task { await store.gestoVista(["vista-nome", s.id, testo]) }
    }

    private func riordina(_ chi: String, prima dove: String) {
        guard chi != dove else { return }
        var ordine = (cose.schede ?? []).map(\.id).filter { $0 != chi }
        ordine.insert(chi, at: ordine.firstIndex(of: dove) ?? ordine.count)
        Task { await store.gestoVista(["vista-ordine", ordine.joined(separator: ",")]) }
    }

    @ViewBuilder
    private func menuScheda(_ s: SchedaCose) -> some View {
        Button(cose.t("rinomina")) { inizia(s) }
        Button(cose.t("duplica")) { Task { await duplica(s, nil) } }

        ForEach(cose.idModi.filter { $0 != s.modo && cose.testi?["duplica_\($0)"] != nil }, id: \.self) { m in
            Button(cose.t("duplica_\(m)")) { Task { await duplica(s, m) } }
        }
        Divider()
        if s.pronta != nil {
            Button(cose.t("nascondi_vista")) { Task { await store.gestoVista(["vista-nascondi", s.id]) } }
                .disabled(store.schedeVisibili.count <= 1)
            Button(cose.t("rimetti_vista")) { Task { await store.gestoVista(["vista-rimetti", s.id]) } }
                .disabled(s.cambiata != true)
        } else {
            Button(cose.t("elimina_vista"), role: .destructive) { Task { await store.gestoVista(["vista-elimina", s.id]) } }
                .disabled(store.schedeVisibili.count <= 1)
        }
    }

    private func duplica(_ s: SchedaCose, _ modo: String?) async {
        let e = await store.gestoVista(["vista-duplica", s.id] + (modo.map { [$0] } ?? []))
        if let id = e?.id, let nuova = store.cose?.schede?.first(where: { $0.id == id }) {
            store.coseVista = id
            inizia(nuova)
        }
    }


    private var menuNuova: some View {
        Menu {
            ForEach(cose.idModi, id: \.self) { m in
                Button(cose.t("modo_\(m)")) {
                    Task {
                        let e = await store.gestoVista(["vista-nuova", m] + (store.vistaSpeciale ? [] : [store.coseVista]))
                        if let id = e?.id, let nuova = store.cose?.schede?.first(where: { $0.id == id }) {
                            store.coseVista = id
                            inizia(nuova)
                        }
                    }
                }
            }
            if let nascoste = cose.schede_nascoste, !nascoste.isEmpty {
                Divider()
                Menu(cose.t("viste_nascoste")) {
                    ForEach(nascoste) { v in Button(v.nome) { Task { await store.gestoVista(["vista-mostra", v.id]) } } }
                }
            }
            if let eliminate = cose.schede_eliminate, !eliminate.isEmpty {
                Menu(cose.t("viste_eliminate")) {
                    ForEach(eliminate) { v in Button(v.nome) { Task { await store.gestoVista(["vista-ripristina", v.id]) } } }
                }
            }
        } label: {
            Image(systemName: "plus").font(.system(size: 12, weight: .medium)).foregroundStyle(.secondary)
                .frame(width: 22, height: 22).contentShape(Rectangle())
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
        .help(cose.t("aiuto_nuova_vista"))
        .disabled(store.modoIstantanea)
    }
}



struct MenuFiltra: View {
    let cose: Cose
    let store: Store

    var body: some View {
        let attivi = store.coseFiltroAlVolo.values.reduce(0) { $0 + $1.count }
        Menu {

            if let pronti = cose.filtri_pronti, !pronti.isEmpty {
                Section(cose.t("filtri_pronti")) {
                    ForEach(pronti) { p in
                        Toggle(cose.t("filtro_scelta").replacingOccurrences(of: "{nome}", with: p.nome)
                                .replacingOccurrences(of: "{n}", with: (p.n ?? 0).formatted()), isOn: Binding(
                            get: { store.coseFiltroAlVolo["pronto"]?.contains(p.id) == true },
                            set: { si in store.filtraAlVolo("pronto", p.id, si, una: true) }))
                        .help(p.aiuto ?? cose.t("aiuto_filtri_pronti"))
                    }
                }
                Divider()
            }
            ForEach(["priorita", "scadenza", "area", "stima", "stato"], id: \.self) { campo in
                if let f = cose.filtri?[campo] {
                    Menu(f.nome) {
                        ForEach(f.scelte) { s in
                            Toggle(cose.t("filtro_scelta").replacingOccurrences(of: "{nome}", with: s.nome).replacingOccurrences(of: "{n}", with: s.n.formatted()), isOn: Binding(
                                get: { store.coseFiltroAlVolo[campo]?.contains(s.id) == true },
                                set: { si in store.filtraAlVolo(campo, s.id, si, una: f.una) }))
                        }
                    }
                }
            }
            if attivi > 0 {
                Divider()
                Button(cose.t("togli_filtri")) { store.coseFiltroAlVolo = [:] }
            }
        } label: {
            Label(cose.t("filtra"), systemImage: "line.3.horizontal.decrease")
                .font(.system(size: 12, weight: attivi > 0 ? .semibold : .regular))
                .foregroundStyle(attivi > 0 ? Color.accentColor : Color.secondary)
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
        .help(cose.t("aiuto_filtra"))
        .disabled(store.vistaSpeciale)
    }
}




struct TastoFatte: View {
    let cose: Cose
    let store: Store

    var body: some View {
        if let s = store.schedaCose, !store.vistaSpeciale, s.modo != "calendario" {
            let nascoste = s.fatte == "no"
            Button {
                Task { await store.mostraFatte(s, nascoste) }
            } label: {

                Label(cose.t(nascoste ? "fatte_tasto_mostra" : "fatte_tasto_nascondi"),
                      systemImage: nascoste ? "eye" : "eye.slash")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            .buttonStyle(.plain).fixedSize()
            .help(cose.t(nascoste ? "aiuto_fatte_tasto_mostra" : "aiuto_fatte_tasto_nascondi"))
            .disabled(store.modoIstantanea)
        }
    }
}




struct TastoGruppi: View {
    let cose: Cose
    let store: Store

    var body: some View {
        if let s = store.schedaCose, !store.vistaSpeciale, s.modo != "calendario", s.modo != "foglio" {
            Menu {
                ForEach(["nessuno", "priorita", "stato", "area", "scadenza"], id: \.self) { g in
                    if !(s.modo == "bacheca" && g == "nessuno") {
                        Toggle(g == "nessuno" ? cose.t("nessun_gruppo") : cose.col(g), isOn: Binding(
                            get: { s.gruppo == g },
                            set: { _ in Task { await store.gestoVista(["vista-imposta", s.id, "gruppo", "\"\(g)\""]) } }))
                    }
                }
            } label: {
                Label(s.gruppo == "nessuno" ? cose.t("menu_gruppi") : cose.t("menu_gruppi") + " · " + cose.col(s.gruppo),
                      systemImage: "rectangle.3.group")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            .disabled(store.modoIstantanea)
        }
    }
}



struct MostraCose: View {
    let cose: Cose
    let store: Store
    var body: some View {
        let s = store.schedaCose
        let speciale = store.vistaSpeciale
        Menu {
            if let s, !speciale {

                if s.modo != "calendario" && s.modo != "foglio" {
                    Menu(cose.t("menu_gruppi")) {
                        ForEach(["nessuno", "priorita", "stato", "area", "scadenza"], id: \.self) { g in
                            if !(s.modo == "bacheca" && g == "nessuno") {
                                Toggle(g == "nessuno" ? cose.t("nessun_gruppo") : cose.col(g), isOn: Binding(
                                    get: { s.gruppo == g },
                                    set: { _ in Task { await store.gestoVista(["vista-imposta", s.id, "gruppo", "\"\(g)\""]) } }))
                            }
                        }
                    }
                }
                if s.modo != "calendario" {
                    MenuOrdineCose(cose: cose, store: store, scheda: s)
                }
                if s.modo == "tabella" {
                    Menu(cose.t("menu_colonne")) {
                        ForEach(Store.colonneAccendibili, id: \.self) { c in
                            Toggle(cose.col(c), isOn: Binding(
                                get: { Store.colonnaAccesa(store.coseColonne, c) },
                                set: { si in store.coseColonne[visibility: c] = si ? .visible : .hidden }))
                        }
                        Divider()
                        Button(cose.t("colonne_rimetti")) { store.coseColonne = TableColumnCustomization<VoceCosa>() }
                    }
                } else if s.modo == "foglio" {

                    Menu(cose.t("menu_colonne")) {
                        ForEach(Store.colonneAccendibili, id: \.self) { c in
                            Toggle(cose.col(c), isOn: Binding(
                                get: { Store.colonnaAccesa(store.coseColonneFoglio, c, tutte: true) },
                                set: { si in store.coseColonneFoglio[visibility: c] = si ? .visible : .hidden }))
                        }
                        Divider()
                        Button(cose.t("colonne_rimetti")) { store.coseColonneFoglio = TableColumnCustomization<VoceCosa>() }
                    }
                }
                Menu(cose.t("menu_fatte")) {
                    ForEach(["no", "7_giorni", "tutte"], id: \.self) { f in
                        Toggle(cose.t("fatte_\(f)"), isOn: Binding(get: { s.fatte == f }, set: { _ in
                            Task { await store.gestoVista(["vista-imposta", s.id, "fatte", "\"\(f)\""]) }
                        }))
                    }
                }
                Menu(cose.t("menu_modo")) {
                    ForEach(cose.idModi, id: \.self) { m in
                        Toggle(cose.t("modo_\(m)"), isOn: Binding(get: { s.modo == m }, set: { _ in
                            Task {

                                await store.gestoVista(["vista-imposta", s.id, "modo", "\"\(m)\""])
                            }
                        }))
                    }
                }
            }
            Picker(cose.t("menu_righe"), selection: Binding(get: { store.coseDueRighe }, set: { store.coseDueRighe = $0 })) {
                Text(cose.t("righe_una")).tag(false)
                Text(cose.t("righe_due")).tag(true)
            }
            Divider()
            Button(cose.t("voce_fatte")) { store.coseVista = "fatte" }
            Button(cose.t("voce_eliminate")) { store.coseVista = "eliminate" }
            if let s, s.pronta != nil, !speciale {
                Button(cose.t("rimetti_vista")) { Task { await store.gestoVista(["vista-rimetti", s.id]) } }
                    .disabled(s.cambiata != true)
            }
            Divider()
            Button(cose.t("voce_rileggi")) { Task { await store.caricaCose(rileggi: true) } }

            if cose.stati != nil { Button(cose.t("impostazioni_apri")) { store.apriImpostazioni(Store.sezioneImpostazioni) } }
        } label: {
            Label(cose.t("mostra"), systemImage: "slider.horizontal.3")
                .font(.system(size: 12)).foregroundStyle(.secondary)
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
        .help(cose.t("aiuto_mostra"))
    }
}


struct Pastiglie: View {
    let cose: Cose
    let store: Store

    var body: some View {
        HStack(spacing: 8) {
            ForEach(store.coseFiltroAlVolo.keys.sorted(), id: \.self) { campo in
                if let valori = store.coseFiltroAlVolo[campo], !valori.isEmpty, let f = cose.filtri?[campo] {


                    let nomi = valori.compactMap { v in
                        f.scelte.first { $0.id == v }?.nome ?? cose.aree_def?.first { $0.id == v }?.nome
                    }.joined(separator: ", ")
                    HStack(spacing: 4) {
                        Text(cose.t("pastiglia").replacingOccurrences(of: "{campo}", with: f.nome)
                            .replacingOccurrences(of: "{valori}", with: nomi))
                            .font(.system(size: 11, weight: .medium))
                        Button { store.coseFiltroAlVolo[campo] = nil } label: {
                            Image(systemName: "xmark").font(.system(size: 8, weight: .bold))
                        }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Superficie.selezione, in: Capsule())
                    .fixedSize()
                }
            }
            Button(cose.t("togli_filtri")) { store.coseFiltroAlVolo = [:] }.buttonStyle(.link).font(.system(size: 12))
            if store.schedaCose?.pronta == nil && !store.vistaSpeciale {
                Button(cose.t("salva_nella_vista")) { Task { await store.salvaFiltri(nuova: false) } }
                    .buttonStyle(.link).font(.system(size: 12))
            }
            Button(cose.t("salva_come_vista")) { Task { await store.salvaFiltri(nuova: true) } }
                .buttonStyle(.link).font(.system(size: 12))
            Spacer()
        }
        .frame(height: 24)
    }
}





struct BarraScheda: View {
    let cose: Cose
    let store: Store
    var fuoco: FocusState<FuocoCose?>.Binding
    @State private var nuova = ""
    @State private var capito: CapitoTitolo?

    @State private var capitoPer = ""
    @State private var tolte: Set<String> = []
    @State private var invio = false

    var body: some View {
        HStack(spacing: 12) {
            if store.coseScelte.count > 1 {
                scelte
            } else {
                campoNuova
                Spacer(minLength: 8)
                ricerca
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 44)
        .animation(.easeInOut(duration: 0.15), value: store.coseScelte.count > 1)
    }

    private var campoNuova: some View {
        HStack(spacing: 8) {
            Image(systemName: "plus").font(.system(size: 13))
                .foregroundStyle(fuoco.wrappedValue == .nuova ? Color.accentColor : .secondary)
            TextField(cose.t("nuova_segnaposto"), text: $nuova)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(invio ? .secondary : .primary)
                .focused(fuoco, equals: .nuova)
                .onSubmit { Task { await aggiungi() } }
                .onKeyPress(.downArrow) { fuoco.wrappedValue = .tabella; return .handled }
                .onExitCommand { nuova = ""; fuoco.wrappedValue = .tabella }
                .disabled(store.modoIstantanea || invio)
                .help(cose.t("aiuto_nuova"))
                .task(id: nuova) {

                    let testo = nuova
                    guard testo.split(separator: " ").count >= 2 else { capito = nil; capitoPer = ""; return }
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    guard !Task.isCancelled else { return }
                    let c = await store.capisci(testo)
                    if testo == nuova {
                        capito = c?.etichette.isEmpty == false ? c : nil
                        capitoPer = testo
                    }
                }
            ForEach(store.coseNuovaIn.sorted { $0.key < $1.key }, id: \.key) { campo, valore in
                HStack(spacing: 3) {
                    Text(nomeQui(campo, valore)).font(.system(size: 11, weight: .medium))
                    Button { store.coseNuovaIn[campo] = nil } label: { Image(systemName: "xmark").font(.system(size: 8, weight: .bold)) }
                        .buttonStyle(.plain).foregroundStyle(.secondary)
                }
                .padding(.horizontal, 7).padding(.vertical, 2)
                .background(Superficie.riquadroPremuto, in: Capsule())
                .fixedSize()
            }
            ForEach(capitoPer == nuova ? (capito?.etichette ?? []) : [], id: \.self) { e in
                if !tolte.contains(e.tipo) {
                    HStack(spacing: 3) {
                        Text(e.testo).font(.system(size: 11, weight: .medium))
                        Button { tolte.insert(e.tipo) } label: { Image(systemName: "xmark").font(.system(size: 8, weight: .bold)) }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 7).padding(.vertical, 2)
                    .background(Superficie.selezione, in: Capsule())
                    .help(cose.t("aiuto_etichetta"))
                    .fixedSize()
                }
            }
        }
    }

    private var ricerca: some View {
        HStack(spacing: 5) {
            Image(systemName: "magnifyingglass").font(.system(size: 12)).foregroundStyle(.secondary)
            TextField(cose.t("cerca"), text: Binding(get: { store.coseCerca }, set: { store.coseCerca = $0 }))
                .textFieldStyle(.plain).font(.system(size: 13))
                .focused(fuoco, equals: .cerca)
                .onExitCommand { store.coseCerca = ""; fuoco.wrappedValue = .tabella }
            if !store.coseCerca.isEmpty {
                Button { store.coseCerca = "" } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain).foregroundStyle(.tertiary)
                    .help(cose.t("togli_ricerca"))
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
        .frame(width: 210)
    }


    private var scelte: some View {
        let ids = store.idsAzione
        return HStack(spacing: 10) {
            Text(cose.t("scelte_tanti").replacingOccurrences(of: "{n}", with: ids.count.formatted()))
                .font(.system(size: 13, weight: .semibold))
            Button(cose.t("fatte_tante")) { Task { await store.fattaORiapri(ids) } }
            Menu(cose.col("scadenza")) { VociData(cose: cose, store: store, ids: ids) }.fixedSize()
            Menu(cose.col("priorita")) { VociPriorita(cose: cose, store: store, ids: ids) }.fixedSize()
            Menu(cose.col("stato")) { VociStato(cose: cose, store: store, ids: ids) }.fixedSize()
            Button(cose.t("elimina_tante").replacingOccurrences(of: "{n}", with: ids.count.formatted()), role: .destructive) {
                Task { await store.gestoTask("elimina", ids) }
            }
            Spacer()
            Button(cose.t("togli_scelta")) { store.coseScelte = [] }.buttonStyle(.link)
        }
        .buttonStyle(.bordered).controlSize(.small)
    }


    private func nomeQui(_ campo: String, _ valore: String) -> String {
        if let q = store.nomeQuiSettimana(campo, valore) { return q }
        if campo == "scadenza", let g = cose.mese?.giorni.first(where: { $0.giorno == valore }) { return g.quando }
        return cose.gruppi_per?[campo]?.gruppi.first { $0.valore == valore }?.nome ?? valore
    }


    private func aggiungi() async {
        let testo = nuova.trimmingCharacters(in: .whitespaces)
        guard !testo.isEmpty, !invio else { return }
        invio = true
        var titolo = testo
        var campi: [String: String] = [:]


        if let c = capito, capitoPer.trimmingCharacters(in: .whitespaces) == testo {
            for e in c.etichette.reversed() {
                guard !tolte.contains(e.tipo), titolo.hasSuffix(e.parole) else { break }
                titolo = String(titolo.dropLast(e.parole.count)).trimmingCharacters(in: .whitespaces)
                if e.tipo == "priorita", let p = c.priorita { campi["priorita"] = "\(p)" }
                if e.tipo == "scadenza", let s = c.scadenza { campi["scadenza"] = s }
            }
        }
        let id = await store.nuovaTask(titolo.isEmpty ? testo : titolo, campi: store.coseNuovaIn.merging(campi) { _, nuovo in nuovo })
        invio = false
        if id != nil {
            nuova = ""
            capito = nil
            tolte = []
            store.coseNuovaIn = [:]
        }
        fuoco.wrappedValue = .nuova
    }
}



struct TabellaCose: View {
    let cose: Cose
    let store: Store
    var fuoco: FocusState<FuocoCose?>.Binding

    var foglio = false

    @State private var larghezzaTabella: CGFloat = 0

    static var disegni = 0


    private var colonne: TableColumnCustomization<VoceCosa> { foglio ? store.coseColonneFoglio : store.coseColonne }
    private func metti(_ c: TableColumnCustomization<VoceCosa>) {
        if foglio { store.coseColonneFoglio = c } else { store.coseColonne = c }
    }

    private var colonneAttivabili: [String] {
        ["task"] + Store.ordineColonne(colonne).filter { Store.colonnaAccesa(colonne, $0, tutte: foglio) }
    }

    var body: some View {


        let modo = store.schedaCose?.modo ?? ""
        if (foglio ? modo == "foglio" : !["foglio", "bacheca", "calendario"].contains(modo)) {
            tabella
        } else {
            Color.clear
        }
    }

    @ViewBuilder private var tabella: some View {
        let _ = Self.disegni += 1
        let s = store.schedaCose
        let gruppi = store.disposizione()


        let righeFoglio = foglio ? gruppi.flatMap(\.righe) : []

        let conGruppi = !foglio && !(gruppi.count == 1 && gruppi[0].id.isEmpty)
        let chiusi = s.map { store.gruppiChiusi($0) } ?? []
        let misure = MisureColonne.calcolaUnaVolta(cose, store: store,
                                                   carattere: foglio ? ScorrimentoCose.condiviso.carattereFoglio : ScorrimentoCose.condiviso.carattereIntestazione,
                                                   livelli: store.coseOrdine)
        let per = { (id: String) in misure[id] ?? MisuraColonna(minimo: 60, ideale: 80, massimo: 160) }
        Table(of: VoceCosa.self,
              selection: Binding(get: { store.coseScelte }, set: { store.coseScelte = $0 }),
              sortOrder: Binding(get: { store.coseOrdine }, set: { nuovo in


                  if let s, let c = nuovo.first { store.clicIntestazione(s, c.campo, aggiungi: false) }
              }),

              columnCustomization: store.dettaglioCose
                  ? Binding(get: { colonneColDettaglio(misure) }, set: { _ in })
                  : Binding(get: { colonne }, set: { metti($0) })) {
            colonneUno(per)
            colonneDue(per)
        } rows: {
            if conGruppi {
                ForEach(gruppi) { g in
                    Section(isExpanded: Binding(get: { !chiusi.contains(g.id) },
                                                set: { aperto in if let s { store.chiudiGruppo(s, g.id, !aperto) } })) {
                        ForEach(g.righe) { TableRow($0) }
                    } header: {



                        IntestazioneFerma(gruppo: g, cose: cose)
                    }
                }
            } else if foglio {
                ForEach(righeFoglio) { TableRow($0) }
            } else {
                ForEach(gruppi.first?.righe ?? []) { TableRow($0) }
            }
        }
        .alternatingRowBackgrounds(.disabled)
        .modifier(StileFoglio(foglio: foglio))



        .id(store.coseOrdine)
        .background(AdattaColonne(titoloTask: cose.col("task"),
                                  misure: Dictionary(misure.map { (cose.col($0.key), $0.value) }, uniquingKeysWith: { a, _ in a }),
                                  chiave: chiaveColonne,
                                  maiuscolo: { nome in

                                      guard let s = store.schedaCose, let campo = campoDaNome(nome) else { return }
                                      store.clicIntestazione(s, campo, aggiungi: true)
                                  },
                                  compatto: foglio,
                                  cliccata: { nome, riga, sola in


                                      guard foglio else { return }
                                      if nome.isEmpty {
                                          guard riga < righeFoglio.count, !store.modoIstantanea else { return }
                                          let id = righeFoglio[riga].id
                                          Task { await store.fattaORiapri([id]) }
                                          return
                                      }
                                      guard let col = idDaNome(nome) else { return }

                                      let eraAttiva = sola && col != "task" && store.coseFoglioColonna == col && store.coseFoglioModifica == nil
                                      store.coseFoglioColonna = col
                                      if eraAttiva, let id = store.coseScelte.first {

                                          DispatchQueue.main.async { _ = invioFoglio(id) }
                                      }
                                  }))
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezzaTabella = $0 }
        .focused(fuoco, equals: .tabella)
        .contextMenu(forSelectionType: String.self) { ids in

            if ids.isEmpty {
                Button(cose.t("voce_nuova")) { store.coseFuocoChiesto = .nuova }
                Button(cose.t("colonne_rimetti")) {
                    metti(TableColumnCustomization<VoceCosa>())
                }
            } else {
                VociTask(cose: cose, store: store, ids: righeIn(ids), conDettaglio: true)
            }
        } primaryAction: { ids in

            if foglio, let id = ids.first {
                _ = invioFoglio(id)
                return
            }

            if let id = ids.first {
                store.cosaAperta = id
                store.dettaglioCose = true
            }
        }

        .onKeyPress(keys: [.leftArrow, .rightArrow], phases: .down) { k in
            guard foglio, k.modifiers.subtracting([.numericPad, .function]).isEmpty, store.coseFoglioModifica == nil else { return .ignored }
            let fila = colonneAttivabili
            let i = fila.firstIndex(of: store.coseFoglioColonna) ?? 0
            store.coseFoglioColonna = fila[max(0, min(fila.count - 1, i + (k.key == .leftArrow ? -1 : 1)))]
            return .handled
        }



        .onKeyPress(characters: .alphanumerics.union(.punctuationCharacters).union(.symbols).subtracting(CharacterSet(charactersIn: "0123")),
                    phases: .down) { k in
            guard foglio, k.modifiers.subtracting([.shift]).isEmpty, store.coseFoglioModifica == nil else { return .ignored }
            return .handled
        }
        .onKeyPress(KeyEquivalent(Character(UnicodeScalar(NSF2FunctionKey)!)), phases: .down) { _ in
            guard foglio, store.coseFoglioModifica == nil, store.idsAzione.count == 1, let id = store.idsAzione.first,
                  let v = store.coseIndice[id], v.eliminata != true else { return .ignored }
            store.iniziaFoglio(v, con: v.titolo)
            return .handled
        }

        .onKeyPress(characters: CharacterSet(charactersIn: "0123"), phases: .down) { k in
            guard k.modifiers.isEmpty, !store.idsAzione.isEmpty, store.coseFoglioModifica == nil else { return .ignored }
            Task { await store.gestoTask("priorita", store.idsAzione, [k.characters]) }
            return .handled
        }
        .onKeyPress(.return) {
            guard let id = store.idsAzione.first, store.coseFoglioModifica == nil else { return .ignored }
            if foglio { return invioFoglio(id) ? .handled : .ignored }
            if store.dettaglioCose { store.coseTitoloInModifica = true } else { store.cosaAperta = id; store.dettaglioCose = true }
            return .handled
        }
        .onKeyPress(keys: [.upArrow, .downArrow], phases: .down) { k in
            guard k.modifiers.contains(.option), store.coseFoglioModifica == nil else { return .ignored }
            let righe = store.righeAVista()
            if let r = k.key == .upArrow ? righe.first : righe.last { store.coseScelte = [r.id] }
            return .handled
        }
        .overlay { vuoto }
    }


    @TableColumnBuilder<VoceCosa, OrdineCosa>
    private func colonneUno(_ per: @escaping (String) -> MisuraColonna) -> some TableColumnContent<VoceCosa, OrdineCosa> {
        TableColumn("") { v in
            if foglio { CellaFoglio(store: store, voce: v, colonna: "cerchio") } else { CellaCerchio(cose: cose, voce: v, store: store) }
        }
            .width(28).customizationID("cerchio").disabledCustomizationBehavior(.all)
        TableColumn(titolo("task"), sortUsing: OrdineCosa(campo: "titolo")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "task").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "task", foglio: true)) } else { CellaTitolo(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "task", foglio: foglio)) } }
            .width(min: MisureColonne.minimoTask, ideal: 280).customizationID("task").disabledCustomizationBehavior(.visibility)
        TableColumn(titolo("priorita"), sortUsing: OrdineCosa(campo: "priorita")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "priorita").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "priorita", foglio: true)) } else { CellaPriorita(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "priorita", foglio: foglio)) } }
            .larghezza(per("priorita")).customizationID("priorita").defaultVisibility(partenza("priorita"))
        TableColumn(titolo("scadenza"), sortUsing: OrdineCosa(campo: "scadenza")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "scadenza").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "scadenza", foglio: true)) } else { CellaScadenza(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "scadenza", foglio: foglio)) } }
            .larghezza(per("scadenza")).customizationID("scadenza").defaultVisibility(partenza("scadenza"))
        TableColumn(titolo("inizio"), sortUsing: OrdineCosa(campo: "inizio")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "inizio").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "inizio", foglio: true)) } else { CellaInizio(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "inizio", foglio: foglio)) } }
            .larghezza(per("inizio")).customizationID("inizio").defaultVisibility(partenza("inizio"))
        TableColumn(titolo("stima"), sortUsing: OrdineCosa(campo: "stima")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "stima").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "stima", foglio: true)) } else { CellaStima(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "stima", foglio: foglio)) } }
            .larghezza(per("stima")).customizationID("stima").defaultVisibility(partenza("stima"))
        TableColumn(titolo("area"), sortUsing: OrdineCosa(campo: "area")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "area").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "area", foglio: true)) } else { CellaArea(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "area", foglio: foglio)) } }
            .larghezza(per("area")).customizationID("area").defaultVisibility(partenza("area"))
    }

    @TableColumnBuilder<VoceCosa, OrdineCosa>
    private func colonneDue(_ per: @escaping (String) -> MisuraColonna) -> some TableColumnContent<VoceCosa, OrdineCosa> {
        TableColumn(titolo("stato"), sortUsing: OrdineCosa(campo: "stato")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "stato").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "stato", foglio: true)) } else { CellaStato(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "stato", foglio: foglio)) } }
            .larghezza(per("stato")).customizationID("stato").defaultVisibility(partenza("stato"))
        TableColumn(titolo("cambio"), sortUsing: OrdineCosa(campo: "cambio")) { v in
            if foglio {
                CellaFoglio(store: store, voce: v, colonna: "cambio").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "cambio", foglio: true))
            } else {
                CellaData(testo: v.cambio_breve ?? v.ultimo_cambio ?? "", aiuto: v.cambio_aiuto).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "cambio", foglio: foglio))
            }
        }
        .larghezza(per("cambio")).customizationID("cambio").defaultVisibility(partenza("cambio"))
        TableColumn(titolo("creata"), sortUsing: OrdineCosa(campo: "creata")) { v in
            if foglio {
                CellaFoglio(store: store, voce: v, colonna: "creata").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "creata", foglio: true))
            } else {
                CellaData(testo: v.creata_breve ?? v.creata ?? "", aiuto: nil).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "creata", foglio: foglio))
            }
        }
        .larghezza(per("creata")).customizationID("creata").defaultVisibility(partenza("creata"))
        TableColumn(titolo("chiusa"), sortUsing: OrdineCosa(campo: "chiusa")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "chiusa").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "chiusa", foglio: true)) } else { CellaData(testo: v.chiusa_breve ?? "", aiuto: v.chiusa_parole).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "chiusa", foglio: foglio)) } }
            .larghezza(per("chiusa")).customizationID("chiusa").defaultVisibility(partenza("chiusa"))
        TableColumn(titolo("rinvii"), sortUsing: OrdineCosa(campo: "rinvii")) { v in
            if foglio {
                CellaFoglio(store: store, voce: v, colonna: "rinvii").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "rinvii", foglio: true))
            } else {
                CellaData(testo: (v.rinvii ?? 0) > 0 ? (v.rinvii ?? 0).formatted() : "", aiuto: v.rinvii_aiuto, cifre: true).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "rinvii", foglio: foglio))
            }
        }
        .larghezza(per("rinvii")).customizationID("rinvii").defaultVisibility(partenza("rinvii"))
        TableColumn(titolo("commenti"), sortUsing: OrdineCosa(campo: "commenti")) { v in if foglio { CellaFoglio(store: store, voce: v, colonna: "commenti").modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "commenti", foglio: true)) } else { CellaCommenti(cose: cose, voce: v, store: store).modifier(CellaAttiva(store: store, cose: cose, id: v.id, colonna: "commenti", foglio: foglio)) } }
            .larghezza(per("commenti")).customizationID("commenti").defaultVisibility(partenza("commenti"))
    }



    private func titolo(_ id: String) -> String {
        let nome = cose.col(id)
        let campo = cose.colonne_info?.first { $0.id == id }?.campo_ordine ?? (id == "task" ? "titolo" : id)
        let livelli = store.coseOrdine
        guard livelli.count > 1, let i = livelli.firstIndex(where: { $0.campo == campo }) else { return nome }
        return nome + MisureColonne.segnoLivello(i, livelli[i].order, primo: i == 0)
    }



    private func invioFoglio(_ id: String) -> Bool {
        guard let v = store.coseIndice[id], v.eliminata != true else { return false }

        if store.coseFoglioModifica == id || store.coseFoglioRiquadro == "\(id)|\(store.coseFoglioColonna)" { return true }
        let ids = store.idsAzione.contains(id) ? store.idsAzione : [id]
        switch store.coseFoglioColonna {
        case "task":
            store.iniziaFoglio(v, con: v.titolo)
        case "area", "stato", "priorita", "scadenza", "stima":

            _ = ids
            store.coseFoglioRiquadro = "\(id)|\(store.coseFoglioColonna)"
        default:
            store.cosaAperta = id
            store.dettaglioCose = true
        }
        return true
    }


    private func idDaNome(_ nome: String) -> String? {
        let base = MisureColonne.base(nome)
        if base == MisureColonne.base(cose.col("task")) { return "task" }
        return Store.colonneAccendibili.first { MisureColonne.base(cose.col($0)) == base }
    }


    private func partenza(_ id: String) -> Visibility {
        if foglio { return .automatic }
        if let i = cose.colonne_info?.first(where: { $0.id == id }) { return i.accesa ? .automatic : .hidden }
        return MisureColonne.spenteDiPartenza.contains(id) ? .hidden : .automatic
    }


    private func campoDaNome(_ nome: String) -> String? {
        let base = MisureColonne.base(nome)
        if let i = cose.colonne_info?.first(where: { $0.nome == base }) { return i.campo_ordine }
        return Store.colonneAccendibili.first { cose.col($0) == base } ?? (base == cose.col("task") ? "titolo" : nil)
    }


    private var chiaveColonne: String {
        let accese = Store.colonneAccendibili.filter { Store.colonnaAccesa(colonne, $0, tutte: foglio) }
        return "\(foglio)|\(store.dettaglioCose)|\(store.coseDueRighe)|" + accese.joined(separator: ",")
    }




    private func colonneColDettaglio(_ misure: [String: MisuraColonna]) -> TableColumnCustomization<VoceCosa> {
        var c = colonne
        let accese = Store.ordineColonne(c).filter { Store.colonnaAccesa(c, $0, tutte: foglio) }

        guard larghezzaTabella > 0 else { return c }
        let spazio = MisureColonne.spazio
        let sc = ScorrimentoCose.condiviso
        var resta = larghezzaTabella - sc.barraVerticale - (foglio ? sc.marginiFoglio : sc.margini) - (28 + spazio) - (MisureColonne.minimoTask + spazio)
        var dentro = true
        for id in accese {
            let serve = (misure[id]?.ideale ?? 100) + spazio
            if dentro, serve <= resta {
                resta -= serve
            } else {
                dentro = false
                c[visibility: id] = .hidden
            }
        }
        return c
    }


    private func righeIn(_ ids: Set<String>) -> [String] {
        let ordine = store.righeAVista().map(\.id)
        return ordine.filter { ids.contains($0) } + ids.filter { !ordine.contains($0) }.sorted()
    }

    @ViewBuilder
    private var vuoto: some View {
        if store.righeAVista().isEmpty, store.disposizione().allSatisfy({ $0.righe.isEmpty }) {
            let cerca = store.coseCerca.trimmingCharacters(in: .whitespaces)
            VStack(spacing: 10) {
                Image(systemName: "checkmark.circle").font(.system(size: 32)).foregroundStyle(.tertiary)
                if cerca.isEmpty, !store.coseFiltroAlVolo.values.allSatisfy(\.isEmpty) {


                    let senzaFiltri = store.schedaCose?.id_righe.count ?? 0
                    Text(cose.testi?["vuoto_filtri"] ?? (senzaFiltri == 1 ? cose.t("nessuna_qui_altrove_uno")
                            : cose.t("nessuna_qui_altrove").replacingOccurrences(of: "{n}", with: senzaFiltri.formatted())))
                        .font(.system(size: 13)).foregroundStyle(.secondary)
                    Button(cose.t("togli_filtri")) { store.coseFiltroAlVolo = [:] }
                        .buttonStyle(.bordered).controlSize(.small)
                } else if cerca.isEmpty {
                    Text(store.schedaCose?.vuoto ?? "").font(.system(size: 13)).foregroundStyle(.secondary)
                } else {
                    let altrove = (cose.righe ?? []).filter { store.trovata($0, cerca) }.count
                    Text(altrove > 0
                         ? (altrove == 1 ? cose.t("nessuna_qui_altrove_uno") : cose.t("nessuna_qui_altrove").replacingOccurrences(of: "{n}", with: altrove.formatted()))
                         : cose.t("ricerca_vuota").replacingOccurrences(of: "{q}", with: cerca))
                        .font(.system(size: 13)).foregroundStyle(.secondary)
                    HStack {
                        if altrove > 0, store.coseVista != "tutte" {
                            Button(cose.t("cerca_fra_tutte")) {
                                let q = store.coseCerca
                                store.coseVista = "tutte"
                                store.coseCerca = q
                            }
                        }
                        Button(cose.t("togli_ricerca")) { store.coseCerca = "" }
                    }
                    .buttonStyle(.bordered).controlSize(.small)
                }
            }
            .multilineTextAlignment(.center)
            .frame(maxWidth: 320)
        }
    }
}


struct IntestazioneFerma: View {
    let gruppo: GruppoVisto
    let cose: Cose

    static var disegni = 0
    var body: some View {
        let _ = Self.disegni += 1
        IntestazioneGruppo(gruppo: gruppo, cose: cose).offset(x: ScorrimentoCose.condiviso.x)
    }
}


struct IntestazioneGruppo: View {
    let gruppo: GruppoVisto
    let cose: Cose

    var inColonna = false

    var body: some View {
        let somma = SommaTempo.frase(gruppo.righe, cose)
        if inColonna {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 7) { nome; numero }
                if !somma.isEmpty {
                    Text(somma).font(.system(size: 10)).monospacedDigit().foregroundStyle(.tertiary).lineLimit(1)
                        .help(somma)
                }
            }
        } else {
            HStack(spacing: 7) {
                nome
                numero

                if !somma.isEmpty {
                    Text(somma).font(.system(size: 11)).monospacedDigit().foregroundStyle(.tertiary).lineLimit(1)
                }
            }
        }
    }

    @ViewBuilder private var nome: some View {
        if gruppo.campo == "priorita", let p = Int(gruppo.id) {
            SegnoPriorita(priorita: p, nome: gruppo.nome)
        } else {
            Text(gruppo.nome).font(.system(size: 13, weight: .semibold)).foregroundStyle(.primary).lineLimit(1)
                .help(gruppo.nome)
        }
    }

    private var numero: some View {
        Text(gruppo.righe.count.formatted()).font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary).fixedSize()
    }
}



enum SommaTempo {
    static func breve(_ minuti: Int, _ cose: Cose) -> String {
        if minuti < 60 { return cose.t("breve_minuti").replacingOccurrences(of: "{n}", with: minuti.formatted()) }
        let h = minuti / 60, m = minuti % 60
        if m == 0 { return cose.t("breve_ore_tonde").replacingOccurrences(of: "{h}", with: h.formatted()) }
        return cose.t("breve_ore_minuti").replacingOccurrences(of: "{h}", with: h.formatted())
            .replacingOccurrences(of: "{mm}", with: String(format: "%02d", m))
    }

    static func frase(_ righe: [VoceCosa], _ cose: Cose) -> String {
        let aperte = righe.filter { !$0.chiusaOra && $0.eliminata != true }
        guard !aperte.isEmpty, cose.testi?["somma_gruppo"] != nil else { return "" }
        let minuti = aperte.compactMap(\.stima_min).reduce(0, +)
        let senza = aperte.filter { $0.stima_min == nil }.count
        var pezzi: [String] = []
        if minuti > 0 { pezzi.append(cose.t("somma_gruppo").replacingOccurrences(of: "{totale}", with: breve(minuti, cose))) }
        if senza == 1, minuti > 0 { pezzi.append(cose.t("somma_senza_uno")) }
        if senza > 1, minuti > 0 { pezzi.append(cose.t("somma_senza").replacingOccurrences(of: "{n}", with: senza.formatted())) }
        return pezzi.joined(separator: cose.t("somma_separatore"))
    }
}



struct CampoTempo: View {
    let cose: Cose
    let store: Store
    let ids: [String]
    let valore: String

    var breve: String = ""
    var spento = false
    var fuoco = false


    var salvaUscendo = true
    var dopo: () -> Void = {}
    @State private var testo = ""
    @State private var anteprima: (testo: String, errore: Bool)?
    @State private var lettura: Task<Void, Never>?

    @State private var inviato: String?
    @FocusState private var dentro: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {

            TextField(text: $testo, prompt: Text(cose.t("stima_segnaposto")).foregroundStyle(.tertiary)) { EmptyView() }
                .textFieldStyle(.plain).font(.system(size: 13))
                .focused($dentro)
                .disabled(spento)
                .help(cose.t("aiuto_stima_scrivi"))
                .onSubmit(salva)
                .onExitCommand { testo = valore; anteprima = nil }
                .onChange(of: testo) { _, t in if dentro { leggi(t) } }
            if let a = anteprima, dentro || a.errore {
                Text(a.testo).font(.system(size: 11))
                    .foregroundStyle(a.errore ? Salute.errore.colore : .secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .onAppear { testo = fuoco || breve.isEmpty ? valore : breve; if fuoco { dentro = true } }
        .onChange(of: valore) { _, v in inviato = nil; if !dentro { testo = breve.isEmpty ? v : breve } }
        .onChange(of: breve) { _, b in if !dentro, !b.isEmpty { testo = b } }


        .onDisappear {
            guard salvaUscendo, testo != valore, testo != breve else { return }
            if let a = anteprima, a.errore { store.coseEsito = EsitoRiga(testo: a.testo, errore: true) } else { salva() }
        }
        .onChange(of: dentro) { _, d in
            if d {
                testo = valore
                anteprima = nil
            } else {
                if salvaUscendo, testo != valore, testo != breve, anteprima?.errore != true { salva() }

                if !breve.isEmpty, anteprima?.errore != true { testo = breve }
            }
        }
    }


    private func leggi(_ t: String) {
        lettura?.cancel()
        guard t != valore else { anteprima = nil; return }
        lettura = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 180_000_000)
            guard !Task.isCancelled else { return }
            let r = await store.motore.chiedi(["cose", "durata", t], scadenza: 10)
            guard !Task.isCancelled, let d = try? JSONDecoder().decode(RispostaDurata.self, from: r.dati) else { return }
            anteprima = d.ok ? (d.anteprima ?? "", false) : (d.errore ?? "", true)
        }
    }

    private func salva() {
        let t = testo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t != valore, t != breve || breve.isEmpty, anteprima?.errore != true, t != inviato else { return }
        inviato = t
        let scelte = ids
        Task { await store.gestoTask("stima", scelte, [t.isEmpty ? "togli" : t]) }
        dopo()
    }
}

struct RispostaDurata: Decodable {
    let ok: Bool
    let minuti: Int?
    let anteprima: String?
    let breve: String?
    let campo: String?
    let errore: String?
}


struct FoglioTempo: View {
    let cose: Cose
    let ids: [String]
    let store: Store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(ids.count == 1 ? (store.coseIndice[ids[0]]?.titolo ?? "")
                 : cose.t("scelte_tanti").replacingOccurrences(of: "{n}", with: ids.count.formatted()))
                .font(Testo.titoloSezione).lineLimit(2)
            CampoTempo(cose: cose, store: store, ids: ids,
                       valore: ids.count == 1 ? (store.coseIndice[ids[0]]?.stima_campo ?? "") : "", fuoco: true,
                       salvaUscendo: false) { chiudi() }
                .padding(8)
                .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
            HStack {
                Spacer()
                Button(cose.t("annulla"), role: .cancel) { chiudi() }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(18)
        .frame(width: 340)
    }
}




struct CellaCerchio: View {

    private var aiutoCerchio: String {
        if voce.eliminata == true { return cose.t("aiuto_ripristina") }
        if voce.stato_sconosciuto == true { return cose.t("aiuto_stato_sconosciuto") }
        if voce.stato_tolto == true { return cose.t("aiuto_stato_tolto") }
        if voce.stato_tipo != nil {
            return cose.t(voce.chiusaOra ? "aiuto_cerchio_chiusa" : "aiuto_cerchio_aperta").replacingOccurrences(of: "{nome}", with: voce.stato_nome ?? "")
        }
        return cose.t("aiuto_cerchio_\(voce.stato ?? "da_fare")")
    }

    let cose: Cose
    let voce: VoceCosa
    let store: Store
    @State private var sopra = false

    var body: some View {
        if store.coseOccupate.contains(voce.id) {
            ProgressView().controlSize(.small).frame(width: 20, height: 20)
        } else {

            SegnoStato(stato: voce.stato ?? "da_fare", eliminata: voce.eliminata == true, anteprima: sopra)
                .frame(width: 20, height: 20).contentShape(Rectangle())
                .onTapGesture {
                    guard !store.modoIstantanea else { return }
                    Task { await store.fattaORiapri([voce.id]) }
                }
                .onHover { sopra = $0 }
                .help(aiutoCerchio)
                .accessibilityElement()
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(voce.stato_nome ?? cose.t("fatta"))
        }
    }
}


struct SegnoStato: View {
    let stato: String
    var eliminata = false
    var anteprima = false
    var dimensione: CGFloat = 16

    var body: some View {
        let (nome, colore) = Self.segno(stato: stato, eliminata: eliminata, anteprima: anteprima)
        Image(systemName: nome).font(.system(size: dimensione)).foregroundStyle(colore)
            .contentTransition(.symbolEffect(.replace))
    }


    static func segno(stato: String, eliminata: Bool, anteprima: Bool) -> (String, Color) {
        if eliminata { return ("arrow.uturn.backward.circle", .secondary) }


        if let d = RegistroStati.condiviso.def[stato] {
            return (anteprima && !d.chiuso ? "checkmark.circle" : d.segno, Self.colore(d.colore))
        }

        if !RegistroStati.condiviso.def.isEmpty { return ("questionmark.circle", .secondary) }
        switch stato {
        case "in_corso": return ("circle.lefthalf.filled", Salute.inCorso.colore)
        case "in_attesa": return ("pause.circle", Salute.attenzione.colore)
        case "fatta": return ("checkmark.circle.fill", Salute.ok.colore)
        default: return (anteprima ? "checkmark.circle" : "circle", .secondary)
        }
    }


    static func colore(_ nome: String?) -> Color {
        switch nome {
        case "blu": return Salute.inCorso.colore
        case "viola": return .purple
        case "giallo": return .yellow
        case "arancio": return Salute.attenzione.colore
        case "verde": return Salute.ok.colore
        case "rosso": return Salute.errore.colore
        default: return .secondary
        }
    }
}


struct CellaTitolo: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    @Environment(\.compatto) private var compatto

    var body: some View {
        let chiusa = voce.chiusaOra || voce.eliminata == true
        HStack(spacing: 6) {
            if voce.priorita == 0 && !chiusa {
                RoundedRectangle(cornerRadius: 1.5).fill(TintaPriorita.testo(0)).frame(width: 3, height: compatto ? 14 : 16)
            }
            if compatto, store.coseFoglioModifica == voce.id {
                CampoFoglio(store: store, voce: voce)
            } else {
                Text(voce.titolo)
                    .font(.system(size: compatto ? 12 : 13))
                    .strikethrough(chiusa)
                    .foregroundStyle(chiusa ? .secondary : .primary)
                    .lineLimit(store.coseDueRighe && !compatto ? 2 : 1).truncationMode(.tail)
            }
            if store.coseAppenaAggiunte.contains(voce.id) {
                Circle().fill(Color.accentColor).frame(width: 6, height: 6)
            }
        }
        .opacity(store.fuoriVista(voce.id) ? 0.45 : 1)
        .help(voce.titolo)
    }
}





struct CampoFoglio: View {
    let store: Store
    let voce: VoceCosa
    @FocusState private var dentro: Bool
    @State private var finito = false

    @State private var scelta: TextSelection?

    var body: some View {
        TextField("", text: Binding(get: { store.coseFoglioBozza }, set: { t in
            store.coseFoglioBozza = t
            let x = t.trimmingCharacters(in: .whitespacesAndNewlines)
            let k = "\(voce.id)|titolo"
            if x.isEmpty || x == store.coseFoglioEra { store.coseScrittiInCorso[k] = nil }
            else { store.coseScrittiInCorso[k] = (voce.id, "titolo", x, store.coseFoglioEra) }
        }), selection: $scelta)
        .textFieldStyle(.plain).font(.system(size: 12))
        .focused($dentro)
        .task {


            try? await Task.sleep(nanoseconds: 60_000_000)
            scelta = TextSelection(insertionPoint: store.coseFoglioBozza.endIndex)
            dentro = true

            for _ in 0..<40 {
                if let ed = (NSApp.keyWindow ?? Store.finestraProva)?.firstResponder as? NSTextView {
                    ed.setSelectedRange(NSRange(location: (ed.string as NSString).length, length: 0))
                    break
                }
                await Task.yield()
                try? await Task.sleep(nanoseconds: 5_000_000)
            }
        }
        .onSubmit { chiudi(passa: false) }
        .onKeyPress(.tab, phases: .down) { _ in chiudi(passa: true); return .handled }

        .onExitCommand { annulla() }
        .onChange(of: dentro) { prima, ora in if prima && !ora { chiudi(passa: false) } }
        .onDisappear { chiudi(passa: false) }
    }

    private func annulla() {
        guard !finito, store.coseFoglioModifica == voce.id else { return }
        finito = true
        store.coseScrittiInCorso["\(voce.id)|titolo"] = nil
        store.coseFoglioBozza = store.coseFoglioEra
        store.coseFoglioModifica = nil
        store.coseFuocoChiesto = .tabella
    }


    private func chiudi(passa: Bool) {
        guard !finito, store.coseFoglioModifica == voce.id else { return }
        finito = true
        let t = store.coseFoglioBozza.trimmingCharacters(in: .whitespacesAndNewlines)
        let era = store.coseFoglioEra
        let id = voce.id
        if !t.isEmpty, t != era {
            Task { await store.salvaScritto(id: id, campo: "titolo", testo: t, era: era) }
        } else {
            store.coseScrittiInCorso["\(id)|titolo"] = nil
        }
        if passa {
            let righe = store.righeAVista()
            if let i = righe.firstIndex(where: { $0.id == id }), i + 1 < righe.count {
                let dopo = righe[i + 1]
                store.coseScelte = [dopo.id]
                store.iniziaFoglio(dopo, con: dopo.titolo)
                return
            }
        }
        store.coseFoglioModifica = nil
        store.coseFuocoChiesto = .tabella
    }
}




struct CellaFoglio: View {
    let store: Store
    let voce: VoceCosa
    let colonna: String

    var body: some View {


        interno.frame(height: Self.altezza)
    }

    static let altezza: CGFloat = 14

    @ViewBuilder private var interno: some View {
        if colonna == "task", store.coseFoglioModifica == voce.id {
            CampoFoglio(store: store, voce: voce).padding(.horizontal, 4)
        } else if colonna == "priorita" {

            testo.font(.system(size: 12)).lineLimit(1).padding(.horizontal, 4)
                .background(TintaPriorita.fondo(voce.priorita ?? 2), in: RoundedRectangle(cornerRadius: 4, style: .continuous))
                .padding(.horizontal, 2)
        } else {
            testo.font(.system(size: 12)).lineLimit(1).truncationMode(.tail).padding(.horizontal, 4)
        }
    }
    private var testo: Text {
        switch colonna {
        case "cerchio":
            if store.coseOccupate.contains(voce.id) {
                return Text(Image(systemName: "ellipsis.circle")).font(.system(size: 15)).foregroundStyle(.tertiary)
            }
            let (nome, colore) = SegnoStato.segno(stato: voce.stato ?? "da_fare", eliminata: voce.eliminata == true, anteprima: false)
            return Text(Image(systemName: nome)).font(.system(size: 15)).foregroundStyle(colore)
        case "task":
            let chiusa = voce.chiusaOra || voce.eliminata == true
            let t = Text(verbatim: voce.titolo).strikethrough(chiusa)
                .foregroundStyle(chiusa || store.fuoriVista(voce.id) ? .secondary : .primary)
            if store.coseAppenaAggiunte.contains(voce.id) {
                return Text("\(t) \(Text(Image(systemName: "circle.fill")).font(.system(size: 6)).foregroundStyle(Color.accentColor))")
            }
            return t
        case "priorita":
            let p = voce.priorita ?? 2
            return Text(verbatim: voce.priorita_nome ?? "").font(.system(size: 11, weight: .semibold))
                .foregroundStyle(TintaPriorita.testo(p))
        case "scadenza":
            let d = voce.scadenza_breve ?? ""
            switch voce.tono_breve ?? "vuota" {
            case "vuota": return Text(verbatim: "")
            case "scaduta":
                return Text("\(Text(Image(systemName: "exclamationmark.circle")).foregroundStyle(.secondary)) \(Text(verbatim: d).fontWeight(.medium).foregroundStyle(.primary))")
            case "oggi": return Text(verbatim: d).fontWeight(.semibold).foregroundStyle(.primary)
            case "passata":
                return Text("\(Text(Image(systemName: "clock")).foregroundStyle(.tertiary)) \(Text(verbatim: d).foregroundStyle(.secondary))")
            case "vicina": return Text(verbatim: d).foregroundStyle(.primary)
            default: return Text(verbatim: d).foregroundStyle(.secondary)
            }
        case "inizio":
            return Text(verbatim: voce.inizio_breve ?? "")
                .fontWeight(voce.tono_inizio == "oggi" ? .medium : .regular)
                .foregroundStyle(CellaInizio.colore(voce.tono_inizio, oltre: voce.oltre_scadenza == true))
        case "stima": return Text(verbatim: voce.stima_breve ?? "").monospacedDigit().foregroundStyle(.secondary)
        case "area": return Text(verbatim: voce.area).foregroundStyle(.secondary)
        case "stato":
            let (nome, colore) = SegnoStato.segno(stato: voce.stato ?? "da_fare", eliminata: false, anteprima: false)
            return Text("\(Text(Image(systemName: nome)).foregroundStyle(colore)) \(Text(verbatim: voce.stato_nome ?? "").foregroundStyle(.secondary))")
        case "cambio": return cifre(voce.cambio_breve ?? voce.ultimo_cambio ?? "")
        case "creata": return cifre(voce.creata_breve ?? voce.creata ?? "")
        case "chiusa": return cifre(voce.chiusa_breve ?? "")
        case "rinvii": return cifre((voce.rinvii ?? 0) > 0 ? (voce.rinvii ?? 0).formatted() : "")
        case "commenti":
            guard let n = voce.commenti_n, n > 0 else { return Text(verbatim: "") }
            return Text("\(Image(systemName: "text.bubble")) \(Text(verbatim: n.formatted()).monospacedDigit())").foregroundStyle(.secondary)
        default: return Text(verbatim: "")
        }
    }

    private func cifre(_ t: String) -> Text { Text(verbatim: t).monospacedDigit().foregroundStyle(.secondary) }
}



struct CellaAttiva: ViewModifier {
    let store: Store
    let cose: Cose
    let id: String
    let colonna: String
    let foglio: Bool

    func body(content: Content) -> some View {


        if foglio {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .background(alignment: .leading) {
                    if store.coseFoglioColonna == colonna, store.coseScelte.count == 1, store.coseScelte.contains(id) {
                        RoundedRectangle(cornerRadius: 3, style: .continuous)
                            .strokeBorder(Color.accentColor, lineWidth: 1.5)
                            .padding(-3)
                            .popover(isPresented: Binding(get: { store.coseFoglioRiquadro == "\(id)|\(colonna)" },
                                                          set: { if !$0 { store.coseFoglioRiquadro = nil } })) {

                                let ids = store.idsAzione.contains(id) ? store.idsAzione : [id]
                                VStack(alignment: .leading, spacing: 2) {
                                    switch colonna {
                                    case "area": VociArea(cose: cose, store: store, ids: ids)
                                    case "priorita": VociPriorita(cose: cose, store: store, ids: ids)
                                    case "scadenza": VociData(cose: cose, store: store, ids: ids)
                                    case "stima": VociStima(cose: cose, store: store, ids: ids)
                                    default: VociStato(cose: cose, store: store, ids: ids)
                                    }
                                }
                                .toggleStyle(.checkbox).buttonStyle(.link)
                                .padding(12)
                            }
                    }
                }
        } else {
            content
        }
    }
}


struct StileFoglio: ViewModifier {
    let foglio: Bool
    func body(content: Content) -> some View {
        if foglio {
            content
                .tableStyle(.bordered(alternatesRowBackgrounds: false))
                .environment(\.defaultMinListRowHeight, MisureColonne.rigaFoglio)
                .environment(\.compatto, true)
        } else {
            content
        }
    }
}


struct SegnoPriorita: View {
    let priorita: Int
    let nome: String



    var body: some View {
        Text(nome).font(.system(size: 11, weight: .semibold)).foregroundStyle(TintaPriorita.testo(priorita))
            .frame(width: 28, height: 16)
            .background(TintaPriorita.fondo(priorita), in: RoundedRectangle(cornerRadius: 4, style: .continuous))
    }
}



struct MenuCella<Etichetta: View, Voci: View>: View {
    let aiuto: String
    let spento: Bool
    @ViewBuilder let voci: () -> Voci
    @ViewBuilder let etichetta: () -> Etichetta
    @State private var sopra = false
    @Environment(\.compatto) private var compatto

    var body: some View {

        if compatto {
            etichetta().lineLimit(1).truncationMode(.tail).padding(.horizontal, 4).help(aiuto)
        } else if sopra && !spento {
            menu
        } else {


            etichetta().lineLimit(1).truncationMode(.tail)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 4).padding(.vertical, 1)
                .contentShape(Rectangle())
                .onHover { sopra = $0 }
                .help(aiuto)
        }
    }

    private var menu: some View {




        Menu { voci() } label: { etichetta().lineLimit(1).truncationMode(.tail) }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 4).padding(.vertical, 1)
            .background(sopra && !spento ? Superficie.riquadroPremuto : .clear,
                        in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
            .animation(.easeOut(duration: 0.1), value: sopra)
            .onHover { sopra = $0 }
            .disabled(spento)
            .help(aiuto)
    }
}

struct CellaPriorita: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store

    var body: some View {
        MenuCella(aiuto: cose.t("aiuto_priorita"), spento: spenta) {
            VociPriorita(cose: cose, store: store, ids: [voce.id])
        } etichetta: {
            SegnoPriorita(priorita: voce.priorita ?? 2, nome: voce.priorita_nome ?? "")
        }
    }

    private var spenta: Bool { store.coseOccupate.contains(voce.id) || voce.aperta == false }
}

struct CellaScadenza: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    @State private var sopra = false

    var body: some View {
        MenuCella(aiuto: (voce.aiuto_scadenza.isEmpty ? "" : voce.aiuto_scadenza + " ") + cose.t("aiuto_data"),
                  spento: store.coseOccupate.contains(voce.id) || voce.aperta == false) {
            VociData(cose: cose, store: store, ids: [voce.id])
        } etichetta: {
            TestoScadenza(voce: voce, vuoto: sopra)
        }
        .onHover { sopra = $0 }
    }
}





struct TestoScadenza: View {
    let voce: VoceCosa
    var vuoto = false
    var corpo: CGFloat = 13

    var body: some View {
        let tono = voce.tono_breve ?? "vuota"
        HStack(spacing: 3) {
            switch tono {
            case "vuota":
                Image(systemName: "plus").font(.system(size: 11)).foregroundStyle(.tertiary).opacity(vuoto ? 1 : 0)
            case "scaduta":
                Image(systemName: "exclamationmark.circle").font(.system(size: corpo - 2)).foregroundStyle(.secondary)
                Text(voce.scadenza_breve ?? "").font(.system(size: corpo, weight: .medium)).foregroundStyle(.primary)
            case "oggi":
                Text(voce.scadenza_breve ?? "").font(.system(size: corpo, weight: .semibold)).foregroundStyle(.primary)
            case "passata":
                Image(systemName: "clock").font(.system(size: corpo - 3)).foregroundStyle(.tertiary)
                Text(voce.scadenza_breve ?? "").font(.system(size: corpo)).foregroundStyle(.secondary)
            case "vicina":
                Text(voce.scadenza_breve ?? "").font(.system(size: corpo)).foregroundStyle(.primary)
            default:
                Text(voce.scadenza_breve ?? "").font(.system(size: corpo)).foregroundStyle(.secondary)
            }
        }
        .lineLimit(1)
    }
}

struct CellaStima: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    @State private var sopra = false

    var body: some View {
        MenuCella(aiuto: cose.t("aiuto_stima"),
                  spento: store.coseOccupate.contains(voce.id) || voce.aperta == false) {
            VociStima(cose: cose, store: store, ids: [voce.id])
        } etichetta: {
            if let s = voce.stima_breve, !s.isEmpty {
                Text(s).font(.system(size: 13)).monospacedDigit().foregroundStyle(.secondary)
            } else {
                Image(systemName: "plus").font(.system(size: 11)).foregroundStyle(.tertiary).opacity(sopra ? 1 : 0)
            }
        }
        .onHover { sopra = $0 }
    }
}

struct CellaArea: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store

    var body: some View {
        MenuCella(aiuto: cose.t("aiuto_area"),
                  spento: store.coseOccupate.contains(voce.id) || voce.aperta == false) {
            VociArea(cose: cose, store: store, ids: [voce.id])
        } etichetta: {
            Text(voce.area).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}

struct CellaStato: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store

    var body: some View {
        MenuCella(aiuto: cose.t("aiuto_stato"),
                  spento: store.coseOccupate.contains(voce.id) || voce.eliminata == true) {
            VociStato(cose: cose, store: store, ids: [voce.id])
        } etichetta: {
            HStack(spacing: 5) {
                SegnoStato(stato: voce.stato ?? "da_fare", dimensione: 12)
                Text(voce.stato_nome ?? "").font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}




@MainActor private func comune(_ store: Store, _ ids: [String], _ valore: (VoceCosa) -> String?) -> String? {
    let valori = Set(ids.compactMap { store.coseIndice[$0] }.map { valore($0) ?? "" })
    return valori.count == 1 ? valori.first : nil
}

struct VociPriorita: View {
    let cose: Cose
    let store: Store
    let ids: [String]
    var tasti = false

    var body: some View {
        let ora = comune(store, ids) { $0.priorita.map(String.init) }
        ForEach(cose.scelte_priorita ?? []) { s in
            let b = Toggle(s.id == "0" ? cose.t("voce_priorita_0") : s.nome, isOn: Binding(get: { ora == s.id }, set: { _ in
                let fai = { Task { await store.gestoTask("priorita", ids, [s.id]) } }
                if tasti { store.daTasto { _ = fai() } } else { _ = fai() }
            }))
            if tasti { b.keyboardShortcut(KeyEquivalent(Character(s.id)), modifiers: [.command, .option]) } else { b }
        }
    }
}

struct VociStato: View {
    let cose: Cose
    let store: Store
    let ids: [String]

    var body: some View {
        let ora = comune(store, ids) { $0.stato }
        ForEach(cose.scelte_stato ?? []) { s in
            Toggle(isOn: Binding(get: { ora == s.id }, set: { _ in
                Task { await store.gestoTask("stato", ids, [s.id]) }
            })) {
                Label { Text(s.nome) } icon: { SegnoStato(stato: s.id, dimensione: 12) }
            }
        }

        if cose.stati != nil {
            Divider()
            Button(cose.t("modifica_stati")) { store.apriImpostazioni("stati") }
        }
    }
}

struct VociData: View {
    let cose: Cose
    let store: Store
    let ids: [String]
    var tasti = false

    var body: some View {
        ForEach(cose.scelte_data ?? []) { s in
            Button(s.nome) { Task { await store.gestoTask("data", ids, [s.id]) } }
        }
        let scegli = Button(cose.t("data_scegli")) {
            if tasti { store.daTasto { store.coseDataPer = ids } } else { store.coseDataPer = ids }
        }
        if tasti { scegli.keyboardShortcut("d", modifiers: [.command, .shift]) } else { scegli }
        Divider()
        Button(cose.t("data_togli")) { Task { await store.gestoTask("data", ids, ["togli"]) } }
            .disabled(ids.allSatisfy { store.coseIndice[$0]?.con_data == false })
    }
}

struct VociStima: View {
    let cose: Cose
    let store: Store
    let ids: [String]

    var body: some View {
        let ora = comune(store, ids) { $0.stima_min.map(String.init) }
        ForEach(cose.scelte_stima ?? []) { s in
            Toggle(s.nome, isOn: Binding(get: { ora == s.id }, set: { _ in
                Task { await store.gestoTask("stima", ids, [s.id]) }
            }))
        }
        Divider()

        Button(cose.t("stima_scrivi")) { store.coseTempoPer = ids }
        Button(cose.t("stima_togli")) { Task { await store.gestoTask("stima", ids, ["togli"]) } }
            .disabled(ids.allSatisfy { store.coseIndice[$0]?.stima_min == nil })
    }
}

struct VociArea: View {
    let cose: Cose
    let store: Store
    let ids: [String]

    var body: some View {
        if cose.aree_def != nil {

            let ora = comune(store, ids) { $0.area_id ?? $0.area }
            ForEach(cose.areeDiOwner) { a in
                Toggle(a.nome, isOn: Binding(get: { ora == a.id }, set: { _ in
                    Task { await store.gestoTask("area", ids, [a.id]) }
                }))
            }
            Divider()
            Toggle(cose.t("senza_area"), isOn: Binding(get: { ora == "senza_area" }, set: { _ in
                Task { await store.gestoTask("area", ids, ["senza_area"]) }
            }))
            .help(cose.t("aiuto_senza_area"))
            Divider()
            Button(cose.t("area_nuova")) { store.coseNuovaAreaPer = ids }
            Button(cose.t("modifica_aree")) { store.apriImpostazioni("aree") }
        } else {
            let ora = comune(store, ids) { $0.area }
            ForEach(cose.aree, id: \.self) { a in
                Toggle(a, isOn: Binding(get: { ora == a }, set: { _ in
                    Task { await store.gestoTask("area", ids, [a]) }
                }))
            }
        }
    }
}


struct FoglioNuovaArea: View {
    let cose: Cose
    let ids: [String]
    let store: Store
    @Environment(\.dismiss) private var chiudi
    @State private var nome = ""
    @FocusState private var dentro: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(cose.t("area_nuova").trimmingCharacters(in: CharacterSet(charactersIn: "…"))).font(Testo.titoloSezione)
            TextField(cose.t("area_segnaposto"), text: $nome)
                .textFieldStyle(.roundedBorder).focused($dentro).onSubmit(fai)
            HStack {
                Spacer()
                Button(cose.t("annulla"), role: .cancel) { chiudi() }.keyboardShortcut(.cancelAction)
                Button(cose.t("area_nuova").trimmingCharacters(in: CharacterSet(charactersIn: "…")), action: fai)
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                    .disabled(nome.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(18)
        .frame(width: 340)
        .onAppear { dentro = true }
    }

    private func fai() {
        let n = nome.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !n.isEmpty else { return }
        let scelte = ids
        chiudi()
        Task { await store.gestoTask("area", scelte, [n]) }
    }
}


struct VociTask: View {
    let cose: Cose
    let store: Store
    let ids: [String]
    var conDettaglio = false
    var tasti = false

    var body: some View {
        let righe = ids.compactMap { store.coseIndice[$0] }
        let tante = ids.count > 1
        let eliminate = !righe.isEmpty && righe.allSatisfy { $0.eliminata == true }
        if tante {
            Text(cose.t("scelte_tanti").replacingOccurrences(of: "{n}", with: ids.count.formatted()))
        }
        if conDettaglio && !tante {
            Button(cose.t("apri_dettaglio")) { store.cosaAperta = ids.first; store.dettaglioCose = true }
            Button(cose.t("modifica_titolo")) {
                store.cosaAperta = ids.first
                store.dettaglioCose = true
                store.coseTitoloInModifica = true
            }
            Divider()
        }
        if eliminate {
            Button(cose.t("ripristina")) { Task { await store.gestoTask("ripristina", ids) } }
        } else {
            let fatte = !righe.isEmpty && righe.allSatisfy { $0.chiusaOra }
            let b = Button(fatte ? cose.t("riapri") : (tante ? cose.t("fatte_tante") : cose.t("fatta"))) {
                if tasti { store.daTasto { Task { await store.fattaORiapri(ids) } } } else { Task { await store.fattaORiapri(ids) } }
            }
            if tasti { b.keyboardShortcut("k", modifiers: .command) } else { b }
            Menu(cose.col("stato")) { VociStato(cose: cose, store: store, ids: ids) }
            Menu(cose.col("priorita")) { VociPriorita(cose: cose, store: store, ids: ids, tasti: tasti) }
            Menu(cose.col("scadenza")) { VociData(cose: cose, store: store, ids: ids, tasti: tasti) }
            Menu(cose.col("stima")) { VociStima(cose: cose, store: store, ids: ids) }
            Menu(cose.col("area")) { VociArea(cose: cose, store: store, ids: ids) }
        }
        Divider()
        Button(tante ? cose.t("copia_titoli") : cose.t("copia_titolo")) { store.copiaTitoli(ids) }

        if !tante, let spunto = righe.first?.spuntoOrigine {
            Button(cose.apriOrigine(righe.first?.link_fonte)) { store.apriSpunto(spunto) }
        } else if !tante, let s = righe.first?.link, let url = URL(string: s) {
            Button(cose.apriOrigine(righe.first?.link_fonte)) { NSWorkspace.shared.open(url) }
        }
        if !eliminate {
            Divider()
            let el = Button(tante ? cose.t("elimina_tante").replacingOccurrences(of: "{n}", with: ids.count.formatted()) : cose.t("elimina"),
                            role: .destructive) {

                if tasti { store.daTasto(cancella: true) { Task { await store.gestoTask("elimina", ids) } } }
                else { Task { await store.gestoTask("elimina", ids) } }
            }
            if tasti { el.keyboardShortcut(.delete, modifiers: .command) } else { el }
        }
    }
}





struct RigaEsitoCose: View {
    let store: Store

    var body: some View {
        HStack(spacing: 10) {
            if let c = store.coseConflitto, !(store.dettaglioCose && store.cosaAperta == c.id) {

                Image(systemName: Simbolo.attenzione).font(.system(size: 11)).foregroundStyle(Salute.attenzione.colore)
                Text(store.t("intanto_cambiata") + " · " + (store.coseIndice[c.id]?.titolo ?? "")).font(.system(size: 12)).lineLimit(1)
                Button(store.t("tieni_la_mia")) { Task { await store.tieniLaMia(c) } }.buttonStyle(.link).font(.system(size: 12))
                Button(store.t("prendi_nuova")) { store.togliConflitto(c) }.buttonStyle(.link).font(.system(size: 12))
                if store.coseConflitti.count > 1 {
                    Text("+\((store.coseConflitti.count - 1).formatted())").font(.system(size: 11)).foregroundStyle(.secondary)
                }
            } else if let e = store.coseEsito {
                if e.errore {
                    Image(systemName: Simbolo.attenzione).font(.system(size: 11)).foregroundStyle(Salute.attenzione.colore)
                }
                Text(e.testo).font(.system(size: 12)).foregroundStyle(e.errore ? .primary : .secondary).lineLimit(1)
                    .id(e.segno).transition(.opacity)
                if e.errore, let r = e.riprova {
                    Button(store.t("riprova")) {
                        Task {
                            if r == ["rileggi"] { await store.caricaCose(rileggi: true) }
                            else if r.first == "voce-testo", r.count == 2 { _ = await store.chiediAllaLista(r[1]) }
                            else { await store.riprovaCose(r, chiave: e.chiave) }
                        }
                    }.buttonStyle(.link).font(.system(size: 12))
                } else if e.annullabile, store.coseUndo?.canUndo == true {
                    Button(store.t("annulla")) { store.annullaUltimo() }.buttonStyle(.link).font(.system(size: 12))
                        .help(store.t("aiuto_annulla_riga"))
                }
            }


            if store.coseVista == "fatte", !store.coseFatteTutte,
               let altre = store.cose?.speciali?.first(where: { $0.id == "fatte" })?.altre, altre > 0 {
                Button(altre == 1 ? store.t("fatte_altre_uno") : store.t("fatte_altre").replacingOccurrences(of: "{n}", with: altre.formatted())) {
                    store.coseFatteTutte = true
                    Task { await store.caricaCose() }
                }
                .buttonStyle(.link).font(.system(size: 12))
            }
            Spacer(minLength: 8)
            Text(conteggio).font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14)
        .frame(height: 28)
        .animation(.easeOut(duration: 0.15), value: store.coseEsito)
    }

    private var conteggio: String {
        let n = store.righeAVista().count
        let tutte = store.disposizione().reduce(0) { $0 + $1.righe.count }


        var s = n < tutte && store.cose?.testi?["conteggio_a_vista"] != nil
            ? store.t("conteggio_a_vista").replacingOccurrences(of: "{n}", with: n.formatted()).replacingOccurrences(of: "{tot}", with: tutte.formatted())
            : store.t("conteggio_task").replacingOccurrences(of: "{n}", with: n.formatted())

        var pezzi = [s]
        let k = store.coseScelte.count
        if k == 1 { pezzi.append(store.t("conteggio_scelte_uno")) }
        if k > 1 { pezzi.append(store.t("conteggio_scelte_tanti").replacingOccurrences(of: "{n}", with: k.formatted())) }

        pezzi.append(store.paroleOrdine)

        if store.schedaCose?.modo == "tabella" || store.schedaCose?.modo == "foglio" {
            let f = ScorrimentoCose.condiviso.colonneFuori
            if f == 1 { pezzi.append(store.t("colonne_a_destra_una")) }
            if f > 1 { pezzi.append(store.t("colonne_a_destra").replacingOccurrences(of: "{n}", with: f.formatted())) }
        }
        return pezzi.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty && $0 != "0" }.joined(separator: " · ")
    }
}






struct DettaglioCose: View {
    let cose: Cose
    let store: Store
    var fuoco: FocusState<FuocoCose?>.Binding

    var body: some View {
        let ids = store.coseScelte.count > 1 ? store.idsAzione : (store.cosaAperta.map { [$0] } ?? [])
        if ids.count > 1 {
            DettaglioTante(cose: cose, store: store, ids: ids)
        } else if let id = ids.first, let v = store.coseIndice[id] {
            DettaglioUna(cose: cose, store: store, voce: v, fuoco: fuoco)
                .id(v.id)
                .transition(.opacity)
        } else {
            VStack {
                HStack { Spacer(); chiudi }
                Spacer()
            }
            .padding(18)
        }
    }

    private var chiudi: some View {
        Button { store.dettaglioCose = false } label: { Image(systemName: "xmark").font(.system(size: 12)) }
            .buttonStyle(.borderless).foregroundStyle(.secondary).help(cose.t("aiuto_chiudi_dettaglio"))
    }
}

struct DettaglioUna: View {
    let cose: Cose
    let store: Store
    let voce: VoceCosa
    var fuoco: FocusState<FuocoCose?>.Binding
    @State private var titolo = ""
    @State private var descrizione = ""

    @State private var titoloEra = ""
    @State private var descrizioneEra = ""

    var body: some View {
        let aperta = voce.aperta != false
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Menu {
                    VociStato(cose: cose, store: store, ids: [voce.id])
                } label: {
                    SegnoStato(stato: voce.stato ?? "da_fare", eliminata: voce.eliminata == true)
                }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help(cose.t("aiuto_stato"))
                Spacer()
                Button { store.dettaglioCose = false } label: { Image(systemName: "xmark").font(.system(size: 12)) }
                    .buttonStyle(.borderless).foregroundStyle(.secondary).help(cose.t("aiuto_chiudi_dettaglio"))
            }
            .frame(height: 24)
            .padding(.horizontal, 20).padding(.top, 16)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {

                    if store.coseTitoloInModifica && voce.eliminata != true {
                        TextField(cose.t("titolo_segnaposto"), text: $titolo, axis: .vertical)
                            .textFieldStyle(.plain)
                            .font(Testo.verdetto)
                            .lineLimit(1...6)
                            .focused(fuoco, equals: .titolo)
                            .onSubmit { salva("titolo"); fuoco.wrappedValue = .tabella }
                            .onExitCommand { titolo = titoloEra; fuoco.wrappedValue = .tabella }
                            .onAppear { DispatchQueue.main.async { fuoco.wrappedValue = .titolo } }
                    } else {
                        Text(titolo.isEmpty ? voce.titolo : titolo)
                            .font(Testo.verdetto)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture { if voce.eliminata != true { store.coseTitoloInModifica = true } }
                            .help(cose.t("modifica_titolo"))
                    }
                    ForEach(store.coseConflitti.filter { $0.id == voce.id }, id: \.campo) { conflitto($0) }
                    Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 2) {

                        riga(cose.col("stato")) {
                            MenuCella(aiuto: cose.t("aiuto_stato"), spento: voce.eliminata == true) {
                                VociStato(cose: cose, store: store, ids: [voce.id])
                            } etichetta: {
                                HStack(spacing: 6) {
                                    SegnoStato(stato: voce.stato ?? "da_fare", dimensione: 13)
                                    Text(voce.stato_nome ?? "").font(.system(size: 13))
                                }
                            }
                        }
                        riga(cose.col("priorita")) {
                            Picker("", selection: Binding(get: { "\(voce.priorita ?? 2)" }, set: { p in
                                Task { await store.gestoTask("priorita", [voce.id], [p]) }
                            })) {
                                ForEach(cose.scelte_priorita ?? []) { s in Text(s.nome).tag(s.id) }
                            }
                            .pickerStyle(.segmented).labelsHidden().controlSize(.small).frame(maxWidth: 180)
                            .help(cose.t("aiuto_priorita"))
                            .disabled(!aperta)
                        }
                        riga(cose.col("scadenza")) {
                            MenuCella(aiuto: voce.aiuto_scadenza, spento: !aperta) {
                                VociData(cose: cose, store: store, ids: [voce.id])
                            } etichetta: {
                                if voce.con_data { TestoScadenza(voce: voce) } else { aggiungi }
                            }
                        }
                        riga(cose.col("stima")) {

                            CampoTempo(cose: cose, store: store, ids: [voce.id], valore: voce.stima_campo ?? "",
                                       breve: voce.stima_breve ?? "", spento: !aperta)
                        }
                        riga(cose.col("area")) {
                            MenuCella(aiuto: cose.t("aiuto_area"), spento: !aperta) {
                                VociArea(cose: cose, store: store, ids: [voce.id])
                            } etichetta: {
                                Text(voce.area).font(.system(size: 13))
                            }
                        }
                    }
                    .padding(.top, 12)
                    Rectangle().fill(Superficie.separatore).frame(height: 0.5).padding(.vertical, 16)
                    ZStack(alignment: .topLeading) {
                        if descrizione.isEmpty {
                            Text(cose.t("descrizione_segnaposto")).font(.system(size: 13)).foregroundStyle(.tertiary)
                                .padding(.leading, 5)
                        }
                        TextEditor(text: $descrizione)
                            .font(.system(size: 13))
                            .lineSpacing(3)
                            .scrollContentBackground(.hidden)
                            .scrollDisabled(true)
                            .frame(minHeight: 160)
                            .focused(fuoco, equals: .descrizione)
                            .onKeyPress(.tab) { salva("descrizione"); fuoco.wrappedValue = .tabella; return .handled }
                            .onExitCommand { descrizione = descrizioneEra; fuoco.wrappedValue = .tabella }
                            .disabled(voce.eliminata == true)
                    }

                    if cose.testi?["commenti_titolo"] != nil {
                        CommentiCosa(cose: cose, store: store, voce: voce)
                            .padding(.top, 18)
                    }
                }
                .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 16)
            }

            .clipped()
            VStack(alignment: .leading, spacing: 8) {
                Text([cose.t("creata").replacingOccurrences(of: "{giorno}", with: voce.creata ?? ""), voce.fermo ?? "",
                      voce.chiusa_parole ?? "", voce.eliminata_parole ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(Testo.minimo).foregroundStyle(.secondary)
                HStack {


                    if let spunto = voce.spuntoOrigine {
                        Button(cose.apriOrigine(voce.link_fonte)) { store.apriSpunto(spunto) }
                            .buttonStyle(.link).font(.system(size: 11)).help(cose.aiutoApriOrigine(voce.link_fonte))
                    } else if let s = voce.link, let url = URL(string: s) {
                        Button(cose.apriOrigine(voce.link_fonte)) { NSWorkspace.shared.open(url) }
                            .buttonStyle(.link).font(.system(size: 11)).help(cose.aiutoApriOrigine(voce.link_fonte))
                    }
                    Spacer()
                    if voce.eliminata == true {
                        Button(cose.t("ripristina")) { Task { await store.gestoTask("ripristina", [voce.id]) } }
                            .controlSize(.small)
                    } else {
                        Button(cose.t("elimina"), role: .destructive) { Task { await store.gestoTask("elimina", [voce.id]) } }
                            .controlSize(.small).help(cose.t("aiuto_elimina"))
                    }
                }
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 16)
            .background(Superficie.scheda)
            .overlay(alignment: .top) { Rectangle().fill(Superficie.separatore).frame(height: 0.5) }
        }
        .background(Superficie.scheda)
        .onAppear { ricarica(forza: true) }


        .onDisappear {
            salva("titolo")
            salva("descrizione")
            store.coseTitoloInModifica = false
        }
        .onChange(of: voce) { _, _ in ricarica(forza: false) }

        .onChange(of: titolo) { _, t in tieniInCorso("titolo", t.trimmingCharacters(in: .whitespacesAndNewlines), titoloEra) }
        .onChange(of: descrizione) { _, t in tieniInCorso("descrizione", t, descrizioneEra) }
        .onChange(of: fuoco.wrappedValue) { prima, dopo in

            if prima == .titolo && dopo != .titolo { salva("titolo"); store.coseTitoloInModifica = false }
            if prima == .descrizione && dopo != .descrizione { salva("descrizione") }
        }
    }

    private var aggiungi: some View {
        Text(cose.t("aggiungi")).font(.system(size: 13)).foregroundStyle(.tertiary)
    }

    private func riga<C: View>(_ nome: String, @ViewBuilder _ valore: () -> C) -> some View {
        GridRow {
            Text(nome).font(.system(size: 11)).foregroundStyle(.secondary).frame(width: 64, alignment: .leading)
            valore().frame(minHeight: 28, alignment: .leading)
        }
    }


    private func ricarica(forza: Bool) {
        if forza || fuoco.wrappedValue != .titolo { titolo = voce.titolo; titoloEra = voce.titolo }
        if forza || fuoco.wrappedValue != .descrizione { descrizione = voce.dettaglio; descrizioneEra = voce.dettaglio }
    }

    private func tieniInCorso(_ campo: String, _ testo: String, _ era: String) {
        let k = "\(voce.id)|\(campo)"
        if testo == era || (campo == "titolo" && testo.isEmpty) { store.coseScrittiInCorso[k] = nil }
        else { store.coseScrittiInCorso[k] = (voce.id, campo, testo, era) }
    }

    private func salva(_ campo: String) {
        let chiave = "\(voce.id)|\(campo)"
        let testo = campo == "titolo" ? titolo.trimmingCharacters(in: .whitespacesAndNewlines) : descrizione
        let era = campo == "titolo" ? titoloEra : descrizioneEra
        guard testo != era, !store.modoIstantanea else { store.coseScrittiInCorso[chiave] = nil; return }
        if campo == "titolo", testo.isEmpty { titolo = titoloEra; store.coseScrittiInCorso[chiave] = nil; return }
        if campo == "titolo" { titoloEra = testo } else { descrizioneEra = testo }

        if testo == (campo == "titolo" ? voce.titolo : voce.dettaglio) { store.coseScrittiInCorso[chiave] = nil; return }


        let id = voce.id
        Task { await store.salvaScritto(id: id, campo: campo, testo: testo, era: era) }
    }

    private func conflitto(_ c: ConflittoTesto) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(cose.t("intanto_cambiata"), systemImage: Simbolo.attenzione)
                .font(.system(size: 12)).foregroundStyle(Salute.attenzione.colore)
            HStack {
                Button(cose.t("tieni_la_mia")) { Task { await store.tieniLaMia(c) } }
                Button(cose.t("prendi_nuova")) {
                    if c.campo == "titolo" { titolo = c.loro; titoloEra = c.loro } else { descrizione = c.loro; descrizioneEra = c.loro }
                    store.togliConflitto(c)
                }
            }
            .controlSize(.small)
        }
        .padding(.top, 8)
    }
}


struct DettaglioTante: View {
    let cose: Cose
    let store: Store
    let ids: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(cose.t("scelte_tanti").replacingOccurrences(of: "{n}", with: ids.count.formatted())).font(Testo.verdetto)
                Spacer()
                Button { store.dettaglioCose = false } label: { Image(systemName: "xmark").font(.system(size: 12)) }
                    .buttonStyle(.borderless).foregroundStyle(.secondary).help(cose.t("aiuto_chiudi_dettaglio"))
            }
            Text(cose.t("dettaglio_tante").replacingOccurrences(of: "{n}", with: ids.count.formatted()))
                .font(.system(size: 12)).foregroundStyle(.secondary)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow { etichetta(cose.col("stato")); Menu(cose.col("stato")) { VociStato(cose: cose, store: store, ids: ids) }.fixedSize() }
                GridRow { etichetta(cose.col("priorita")); Menu(cose.col("priorita")) { VociPriorita(cose: cose, store: store, ids: ids) }.fixedSize() }
                GridRow { etichetta(cose.col("scadenza")); Menu(cose.col("scadenza")) { VociData(cose: cose, store: store, ids: ids) }.fixedSize() }
                GridRow { etichetta(cose.col("stima")); Menu(cose.col("stima")) { VociStima(cose: cose, store: store, ids: ids) }.fixedSize() }
                GridRow { etichetta(cose.col("area")); Menu(cose.col("area")) { VociArea(cose: cose, store: store, ids: ids) }.fixedSize() }
            }
            .controlSize(.small)
            Spacer()
            HStack {
                Button(cose.t("fatte_tante")) { Task { await store.fattaORiapri(ids) } }
                Spacer()
                Button(cose.t("elimina_tante").replacingOccurrences(of: "{n}", with: ids.count.formatted()), role: .destructive) {
                    Task { await store.gestoTask("elimina", ids) }
                }
            }
            .controlSize(.small)
        }
        .padding(20)
        .disabled(store.modoIstantanea)
    }

    private func etichetta(_ s: String) -> some View {
        Text(s).font(.system(size: 11)).foregroundStyle(.secondary).frame(width: 64, alignment: .leading)
    }
}




struct RigheFerme: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(0..<10, id: \.self) { i in
                HStack(spacing: 12) {
                    Circle().fill(Superficie.riquadro).frame(width: 16, height: 16)
                    RoundedRectangle(cornerRadius: 4).fill(Superficie.riquadro)
                        .frame(width: [360, 270, 420][i % 3], height: 10)
                }
            }
            Spacer()
        }
        .padding(.top, 60)
    }
}



struct Cose: Codable, Hashable {
    let ok: Bool
    let errore: String?
    let verdetto: String?
    let letto: String?
    let avviso: String?
    let davanti_n: Int?
    let aperte_n: Int?
    let aree_cose: [String]?
    let scelte_data: [SceltaData]?
    let testi: [String: String]?
    let righe: [VoceCosa]?
    let colonne: [String: String]?
    let scelte_priorita: [SceltaData]?
    let scelte_stima: [SceltaData]?
    let scelte_stato: [SceltaData]?
    let giorni_brevi: [String]?
    let calendario: [GiornoCal]?

    let schede: [SchedaCose]?
    let schede_nascoste: [NomeVista]?
    let schede_eliminate: [NomeVista]?
    let speciali: [SpecialeCose]?
    let righe_chiuse: [VoceCosa]?
    let righe_eliminate: [VoceCosa]?
    let fatte_oggi_n: Int?
    let gruppi_per: [String: GruppiCampo]?
    let filtri: [String: FiltroCampo]?
    let ordini: [SceltaOrdine]?
    let p0: Int?
    let aiuto_numero: String?
    let mese: MeseCal?

    let stati: [StatoDef]?
    let aree_def: [AreaDef]?
    let impostazioni: ImpostazioniAttivita?
    let durata_giornata_minuti: Int?
    let colonne_info: [InfoColonna]?
    let scelte_tipi: [TipoStato]?
    let scelte_segni: [String: [String]]?
    let scelte_colori: [SceltaData]?
    let giorni_lunghi: [String]?

    let modi: [SceltaData]?
    let filtri_pronti: [FiltroPronto]?

    let contratto: Int?

    var davanti: Int { davanti_n ?? 0 }

    var idModi: [String] { modi?.map(\.id) ?? ["tabella", "bacheca", "calendario"] }
    var aperte: Int { aperte_n ?? 0 }
    var aree: [String] { aree_cose ?? [] }



    var areeDiOwner: [AreaDef] {
        let aVista = Set(aree)
        return (aree_def ?? []).filter { $0.tolta != true && $0.unita_in == nil && $0.senza != true && (aree_cose == nil || aVista.contains($0.nome)) }
    }

    enum CodingKeys: String, CodingKey {
        case ok, errore, verdetto, letto, avviso, scelte_data, testi
        case righe, colonne, scelte_priorita, scelte_stima, scelte_stato, giorni_brevi, calendario
        case schede, schede_nascoste, schede_eliminate, speciali, righe_chiuse, righe_eliminate, fatte_oggi_n
        case gruppi_per, filtri, ordini, p0, aiuto_numero, mese
        case stati, aree_def, impostazioni, durata_giornata_minuti, colonne_info, scelte_tipi, scelte_segni, scelte_colori
        case giorni_lunghi, modi, filtri_pronti, contratto
        case davanti_n = "davanti"
        case aperte_n = "aperte"
        case aree_cose = "aree"
    }



    func t(_ chiave: String) -> String { testi?[chiave] ?? TestiMancanti.manca(chiave) }
    func col(_ id: String) -> String { colonne?[id] ?? t(id) }



    func apriOrigine(_ fonte: String?) -> String {
        if let f = fonte, let t = testi?["apri_origine_\(f)"] { return t }
        return testi?["apri_origine"] ?? t("apri_clickup")
    }
    func aiutoApriOrigine(_ fonte: String?) -> String {
        if let f = fonte, let t = testi?["aiuto_apri_origine_\(f)"] { return t }
        return testi?["aiuto_apri_origine"] ?? t("aiuto_apri_clickup")
    }


    var indice: [String: VoceCosa] {
        var out: [String: VoceCosa] = [:]
        for r in (righe ?? []) + (righe_chiuse ?? []) + (righe_eliminate ?? []) { out[r.id] = r }
        return out
    }
}

struct SchedaCose: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let nome_suo: Bool?
    let pronta: String?
    let modo: String
    let regola: String?
    let filtro: FiltroVista?
    let gruppo: String
    let gruppi_chiusi: [String]
    let ordine: OrdineVista?
    let fatte: String
    let nascosta: Bool
    let cambiata: Bool?
    let aiuto: String
    let vuoto: String
    let numero: Int
    let id_righe: [String]
    let id_fatte: [String]

    var ordine_livelli: [OrdineVista]? = nil
    var ordine_parole: String? = nil
    var id_fatte_oggi: [String]? = nil
    var base: String? = nil


    var livelli: [OrdineVista] { ordine_livelli ?? (ordine.map { [$0] } ?? []) }
}

struct FiltroVista: Codable, Hashable {
    let priorita: [String]
    let stato: [String]
    let area: [String]
    let scadenza: String?
    let stima: String?

    var pronto: String? = nil
}


struct FiltroPronto: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let aiuto: String?
    let vuoto: String?
    let n: Int?
}


private struct ChiaveCompatto: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var compatto: Bool {
        get { self[ChiaveCompatto.self] }
        set { self[ChiaveCompatto.self] = newValue }
    }
}

struct OrdineVista: Codable, Hashable {
    let campo: String
    let verso: String
}

struct NomeVista: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
}

struct SpecialeCose: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let aiuto: String
    let vuoto: String
    let id_righe: [String]
    let altre: Int?
}

struct GruppiCampo: Codable, Hashable {
    let verbo: String
    let gruppi: [GruppoDef]
}

struct GruppoDef: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let valore: String?

    let tipo: String?
    let chiuso: Bool?
}

struct FiltroCampo: Codable, Hashable {
    let nome: String
    let una: Bool
    let scelte: [SceltaN]
}

struct SceltaN: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let n: Int
}

struct MeseCal: Codable, Hashable {
    let id: String
    let titolo: String
    let prima: String
    let dopo: String
    let oggi: String
    let settimane: Int
    let giorni: [GiornoMese]
}

struct GiornoMese: Codable, Hashable, Identifiable {
    let giorno: String
    let numero: Int
    let etichetta: String
    let oggi: Bool
    let passato: Bool
    let fuori: Bool
    let festivo: Bool
    let quando: String
    var id: String { giorno }
}

struct GiornoCal: Codable, Hashable, Identifiable {
    let giorno: String
    let etichetta: String
    let oggi: Bool
    var id: String { giorno }
}

struct VoceCosa: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let area: String
    let urgente: Bool
    let davanti: Bool
    let scadenza: String
    let tono: String
    let aiuto_scadenza: String
    let con_data: Bool
    let quanto: String
    let dettaglio: String
    let fermo: String?
    let link: String?
    let priorita: Int?
    let priorita_nome: String?
    let ultimo_cambio: String?
    let creata: String?
    let o_priorita: Int?
    let o_scadenza: Int?
    let o_stima: Int?
    let o_cambio: Int?
    let o_creata: Int?
    let stato: String?
    let stato_nome: String?
    let o_stato: Int?
    let giorno: String?

    let scadenza_breve: String?

    let tono_breve: String?
    let stima_min: Int?
    let stima_breve: String?
    let gruppo_di: [String: String]?
    let o_scadenza_gruppo: Int?
    let filtro_chiavi: [String]?
    let aperta: Bool?
    let chiusa: String?
    let chiusa_parole: String?
    let fatta_oggi: Bool?
    let eliminata: Bool?
    let eliminata_parole: String?

    let stato_tipo: String?
    let stato_segno: String?
    let stato_colore: String?
    let stato_sconosciuto: Bool?
    let stato_tolto: Bool?
    let nello_stato_giorni: Int?
    let o_nello_stato: Int?
    let area_id: String?
    let o_area: Int?
    let o_titolo: Int?
    let cambio_breve: String?
    let creata_breve: String?
    let cambio_aiuto: String?
    let chiusa_breve: String?
    let o_chiusa: Int?
    let rinvii: Int?
    let o_rinvii: Int?
    let rinvii_aiuto: String?
    let commenti_n: Int?
    let o_commenti: Int?
    let ultimo_commento_parole: String?
    let stima_campo: String?
    let stima_frase: String?
    let pianificata: String?
    let pianificata_giorno: String?
    let pianificata_ora: String?
    let inizio_breve: String?
    let tono_inizio: String?
    let inizio_parole: String?
    let inizio_aiuto: String?
    let oltre_scadenza: Bool?
    let o_inizio: Int?

    let link_fonte: String?


    let link_id: String?


    var spuntoOrigine: String? {
        guard link_fonte == "inspiration", let id = link_id, !id.isEmpty else { return nil }
        return id
    }


    var chiusaOra: Bool { aperta == false || stato_tipo == "fatta" || stato_tipo == "non_serve" || stato == "fatta" }


    var oPriorita: Int { o_priorita ?? 9 }
    var oScadenza: Int { o_scadenza ?? Int.max }
    var oStima: Int { o_stima ?? Int.max }
    var oCambio: Int { o_cambio ?? 0 }
    var oCreata: Int { o_creata ?? 0 }
    var oStato: Int { o_stato ?? 0 }
}

struct SceltaData: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
}


struct SceltaOrdine: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let su: String?
    let giu: String?
    let verso_di_partenza: String?
}


struct InfoColonna: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let accesa: Bool
    let si_cambia: Bool?
    let ordinabile: Bool?
    let campo_ordine: String?
    let verso_di_partenza: String?
}


struct StatoDef: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let tipo: String
    let chiuso: Bool
    let segno: String
    let colore: String
    let ordine: Int?
    let predefinito: Bool?
    let tolto: Bool?
    let `in`: String?
    let nomi_prima: [String]?
    let n_aperte: Int?
    let n: Int?
}


struct AreaDef: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let nomi: [String]?
    let ordine: Int?
    let colore: String?
    let unita_in: String?
    let tolta: Bool?
    let senza: Bool?
    let n_aperte: Int?
    let n: Int?
}

struct TipoStato: Codable, Hashable, Identifiable {
    let id: String
    let nome: String
    let aiuto: String?
    let chiuso: Bool?
}

struct ImpostazioniAttivita: Codable, Hashable {
    struct Urgenti: Codable, Hashable { let p1: Bool; let giorni_prima: Int; let giorni_dopo: Int }
    struct Settimana: Codable, Hashable {
        let inizio: Int; let giorni: [Int]; let dalle: String; let alle: String; let giornata_minuti: Int
    }
    let veloci_minuti: Int?
    let urgenti: Urgenti?
    let settimana: Settimana?
    let predefinito: String?
}

struct EsitoCosa: Codable {
    let ok: Bool
    let messaggio: String?
    let errore: String?

    let annulla: [String]?
    let testo_annulla: String?

    let sparita: Bool?

    let eventi: [String]?
    let ids: [String]?
    let azione: String?
    let riga: String?
    let id: String?

    let intanto: String?

    let riprova: Bool?

    let annullata: Bool?
}


struct FoglioDataCosa: View {
    let cose: Cose
    let ids: [String]
    let store: Store
    @Environment(\.dismiss) private var chiudi
    @State private var giorno = Calendar.current.date(byAdding: .day, value: 1, to: Date()) ?? Date()

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(ids.count == 1 ? (store.coseIndice[ids[0]]?.titolo ?? "")
                 : cose.t("scelte_tanti").replacingOccurrences(of: "{n}", with: ids.count.formatted()))
                .font(Testo.titoloSezione).lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            DatePicker(cose.t("data_scegli"), selection: $giorno, displayedComponents: .date)
                .datePickerStyle(.graphical)
                .labelsHidden()
            HStack {
                Spacer()
                Button(cose.t("annulla"), role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button(cose.t("foglio_sposta")) {
                    let f = DateFormatter()
                    f.calendar = Calendar(identifier: .gregorian)
                    f.locale = Locale(identifier: "en_US_POSIX")
                    f.dateFormat = "yyyy-MM-dd"
                    let quando = f.string(from: giorno)
                    let scelte = ids
                    chiudi()
                    Task { await store.gestoTask("data", scelte, [quando]) }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 380)
    }
}





struct CartaCosa: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    var compatta = false
    @State private var sopra = false

    var body: some View {
        let scelta = store.coseScelte.contains(voce.id)
        let fatta = voce.chiusaOra
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                if compatta, let p = voce.priorita, p <= 1, !fatta {
                    Circle().fill(TintaPriorita.testo(p)).frame(width: 6, height: 6)
                }
                Text(voce.titolo).font(.system(size: compatta ? 11 : 13))
                    .strikethrough(fatta)
                    .foregroundStyle(fatta ? .secondary : .primary)
                    .lineLimit(compatta ? 1 : 3).fixedSize(horizontal: false, vertical: true)
            }
            if !compatta && !fatta {
                HStack(spacing: 8) {
                    if let p = voce.priorita, p <= 1 { SegnoPriorita(priorita: p, nome: voce.priorita_nome ?? "") }
                    if voce.con_data { TestoScadenza(voce: voce, corpo: 11) }
                    if let s = voce.stima_breve, !s.isEmpty { Text(s).font(.system(size: 11)).foregroundStyle(.secondary) }
                    Spacer(minLength: 4)
                    Text(voce.area).font(.system(size: 11)).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, compatta ? 5 : 12).padding(.vertical, compatta ? 2 : 10)
        .background(sopra ? Superficie.riquadroPremuto : Superficie.scheda,
                    in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous)
            .strokeBorder(scelta ? Color.accentColor : Superficie.bordo, lineWidth: scelta ? 2 : 1))
        .overlay(alignment: .leading) {
            if voce.priorita == 0 && !compatta && !fatta {
                RoundedRectangle(cornerRadius: 1.5).fill(TintaPriorita.testo(0)).frame(width: 3).padding(.vertical, 4)
            }
        }
        .opacity(store.fuoriVista(voce.id) ? 0.45 : 1)
        .animation(.easeOut(duration: 0.12), value: sopra)
        .onHover { sopra = $0 }
        .help(voce.titolo)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { store.coseScelte = [voce.id]; store.cosaAperta = voce.id; store.dettaglioCose = true }
        .onTapGesture {
            if NSEvent.modifierFlags.contains(.command) || NSEvent.modifierFlags.contains(.shift) {
                if scelta { store.coseScelte.remove(voce.id) } else { store.coseScelte.insert(voce.id) }
            } else {
                store.coseScelte = [voce.id]
            }
        }
        .contextMenu {
            VociTask(cose: cose, store: store, ids: scelta ? store.idsAzione : [voce.id], conDettaglio: true)
        }
        .draggable(scelta && store.coseScelte.count > 1 ? store.idsAzione.joined(separator: ",") : voce.id)
    }
}


extension Store {


    func rilasciaSulGiorno(_ valori: [String], giorno: String, passato: Bool) -> Bool {
        guard !passato else { return false }
        let ids = idsRilasciati(valori).filter { coseIndice[$0]?.giorno != giorno }
        guard !ids.isEmpty else { return false }
        Task { await gestoTask("data", ids, [giorno]) }
        return true
    }
}

func idsRilasciati(_ valori: [String]) -> [String] {
    valori.flatMap { $0.split(separator: ",").map(String.init) }.filter { !$0.hasPrefix("vista:") }
}




struct BachecaCose: View {
    let cose: Cose
    let store: Store

    var body: some View {
        let s = store.schedaCose
        let campo = s?.gruppo ?? "priorita"
        let def = cose.gruppi_per?[campo]
        ScrollView(.horizontal) {

            LazyHStack(alignment: .top, spacing: 12) {
                ForEach(store.disposizione()) { g in
                    ColonnaBacheca(cose: cose, store: store, gruppo: g, verbo: g.campo == "fatte" ? "fatta" : (def?.verbo ?? campo))
                }
            }
            .padding(12)
        }
    }
}

struct ColonnaBacheca: View {
    let cose: Cose
    let store: Store
    let gruppo: GruppoVisto
    let verbo: String
    @State private var puntata = false

    @State private var aperte: Set<Int> = [0, 1]

    var body: some View {
        let vuota = gruppo.righe.isEmpty

        let fatte = gruppo.campo == "fatte" || store.gruppoChiuso(gruppo)
        let stretta = vuota || fatte
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                if gruppo.campo == "stato" { SegnoStato(stato: gruppo.id, dimensione: 13) }

                IntestazioneGruppo(gruppo: gruppo, cose: cose, inColonna: true)
                Spacer(minLength: 0)
                if let v = gruppo.valore, !fatte {
                    Button { store.nuovaQui(gruppo.campo, v) } label: { Image(systemName: "plus").font(.system(size: 11)) }
                        .buttonStyle(.borderless).foregroundStyle(.secondary)
                        .help(cose.t("nuova_qui"))
                }
            }
            .frame(minHeight: 28)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if gruppo.campo != "priorita" && !fatte && gruppo.righe.count > 20 {

                        ForEach(0..<4, id: \.self) { p in
                            let mie = gruppo.righe.filter { $0.priorita == p }
                            if !mie.isEmpty {
                                Button {
                                    if aperte.contains(p) { aperte.remove(p) } else { aperte.insert(p) }
                                } label: {
                                    HStack(spacing: 6) {
                                        Image(systemName: "chevron.right").font(.system(size: 9, weight: .semibold))
                                            .rotationEffect(.degrees(aperte.contains(p) ? 90 : 0))
                                        SegnoPriorita(priorita: p, nome: "P\(p)")
                                        Text(mie.count.formatted()).font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary)
                                    }
                                    .frame(height: 28).contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .help(cose.t(aperte.contains(p) ? "aiuto_chiudi_gruppo" : "aiuto_apri_gruppo"))
                                if aperte.contains(p) {
                                    ForEach(mie) { v in CartaCosa(cose: cose, voce: v, store: store) }
                                }
                            }
                        }
                    } else {
                        ForEach(gruppo.righe) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: fatte) }
                    }
                    if vuota {
                        Text(cose.t("colonna_vuota")).font(.system(size: 11)).foregroundStyle(.tertiary)
                    }
                }
            }
        }
        .padding(8)
        .frame(width: stretta ? 150 : 272)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(puntata ? Superficie.selezione : (fatte ? Salute.ok.colore.opacity(0.07) : Superficie.incasso),
                    in: RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous))
        .overlay {
            if puntata {
                RoundedRectangle(cornerRadius: Raggio.riquadro, style: .continuous).strokeBorder(Color.accentColor, lineWidth: 1)
            }
        }
        .animation(.easeOut(duration: 0.12), value: puntata)
        .contextMenu {
            if let v = gruppo.valore, !fatte { Button(cose.t("nuova_qui")) { store.nuovaQui(gruppo.campo, v) } }
        }
        .dropDestination(for: String.self) { valori, _ in
            let campo = gruppo.campo == "fatte" ? "stato" : gruppo.campo
            let ids = idsRilasciati(valori).filter { store.coseIndice[$0]?.gruppo_di?[campo] != gruppo.id }
            guard !ids.isEmpty else { return false }
            if gruppo.campo == "fatte" || (gruppo.id == "fatta" && gruppo.valore == nil) {
                Task { await store.gestoTask("fatta", ids) }
            } else if let valore = gruppo.valore {
                Task { await store.gestoTask(verbo, ids, [valore]) }
            } else {
                return false
            }
            return true
        } isTargeted: { puntata = $0 && (gruppo.valore != nil || fatte) }
        .help(fatte ? cose.t("aiuto_colonna_fatta") : (vuota ? cose.t("aiuto_colonna_chiusa") : cose.t("aiuto_bacheca")))
    }
}




struct CalendarioCose: View {
    let cose: Cose
    let store: Store
    @State private var larghezza: CGFloat = 1000

    var body: some View {
        let righe = store.disposizione().flatMap(\.righe)
        let perGiorno = Dictionary(grouping: righe.filter { $0.giorno != nil }, by: { $0.giorno ?? "" })
        let giorni = cose.mese?.giorni ?? []
        let settimane = max(cose.mese?.settimane ?? 5, 1)
        let oggi = giorni.first { $0.oggi }?.giorno ?? ""
        let scadute = righe.filter { ($0.giorno ?? "9") < oggi && $0.giorno != nil }
            .sorted { ($0.oPriorita, $0.giorno ?? "") < ($1.oPriorita, $1.giorno ?? "") }
        let senza = righe.filter { $0.giorno == nil }.sorted { $0.oPriorita < $1.oPriorita }
        let cassetto = store.coseCassetto ?? (larghezza >= 1000)
        HStack(alignment: .top, spacing: 12) {
            if cassetto {
                CassettoCalendario(cose: cose, store: store, scadute: scadute, senza: senza)
                    .frame(width: 248)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Button {
                        withAnimation(.smooth(duration: 0.25)) { store.coseCassetto = !cassetto }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "sidebar.left")
                            if !cassetto {
                                Text(Store.cassettoChiuso(cose, scadute.count, senza.count))
                                    .font(.system(size: 11)).monospacedDigit()
                            }
                        }
                    }
                    .help(cose.t(cassetto ? "aiuto_cassetto" : "aiuto_cassetto_chiuso"))
                    Text(cose.mese?.titolo ?? "").font(Testo.titoloSezione)
                    Spacer()
                    SceltaScala(cose: cose, store: store)
                    Button { store.coseMese = cose.mese?.prima; Task { await store.caricaCose() } } label: { Image(systemName: "chevron.left") }
                        .help(cose.t("aiuto_mese_prima"))
                    Button(cose.t("cal_oggi")) { store.coseMese = nil; Task { await store.caricaCose() } }
                        .help(cose.t("aiuto_cal_oggi"))
                        .disabled(cose.mese?.id == cose.mese?.oggi)
                    Button { store.coseMese = cose.mese?.dopo; Task { await store.caricaCose() } } label: { Image(systemName: "chevron.right") }
                        .help(cose.t("aiuto_mese_dopo"))
                }
                .buttonStyle(.borderless)
                HStack(spacing: 4) {
                    ForEach(cose.giorni_brevi ?? [], id: \.self) { g in
                        Text(g).font(.system(size: 11)).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                GeometryReader { geo in
                    let alta = max(64, (geo.size.height - CGFloat(settimane - 1) * 4) / CGFloat(settimane))
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 7), spacing: 4) {
                        ForEach(giorni) { g in
                            GiornoCalendario(cose: cose, store: store, giorno: g, voci: perGiorno[g.giorno] ?? [],
                                             massimo: max(1, Int((alta - 30) / 22)))
                                .frame(height: alta)
                        }
                    }
                }
            }
        }
        .padding(12)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { larghezza = $0 }
    }
}



struct CassettoCalendario: View {
    let cose: Cose
    let store: Store
    let scadute: [VoceCosa]
    let senza: [VoceCosa]
    @State private var apriScadute = true
    @State private var apriSenza = false
    @State private var puntata = false

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 6, pinnedViews: [.sectionHeaders]) {
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
                            let ids = idsRilasciati(valori).filter { store.coseIndice[$0]?.giorno != nil }
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

struct GiornoCalendario: View {
    let cose: Cose
    let store: Store
    let giorno: GiornoMese
    let voci: [VoceCosa]

    var massimo = 3
    @State private var puntata = false
    @State private var tutte = false

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                if giorno.oggi {
                    Text("\(giorno.numero)").font(.system(size: 11, weight: .semibold)).foregroundStyle(.white)
                        .frame(width: 20, height: 20).background(Color.accentColor, in: Circle())
                } else {
                    Text(giorno.etichetta).font(.system(size: 11, weight: giorno.numero == 1 ? .semibold : .regular))
                        .foregroundStyle(giorno.passato || giorno.fuori ? .tertiary : .secondary)
                }
                Spacer()
            }
            let quante = voci.count > massimo ? max(massimo - 1, 0) : voci.count
            ForEach(voci.prefix(quante)) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: true) }
            if voci.count > quante {
                Button(cose.t("cal_piu").replacingOccurrences(of: "{n}", with: (voci.count - quante).formatted())) { tutte = true }
                    .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(.secondary)
                    .popover(isPresented: $tutte, arrowEdge: .trailing) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(giorno.quando).font(.system(size: 13, weight: .semibold))
                            ForEach(voci) { v in CartaCosa(cose: cose, voce: v, store: store, compatta: true) }
                        }
                        .padding(12).frame(width: 260)
                    }
            }
        }
        .padding(6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(puntata ? Superficie.selezione
                    : (giorno.passato ? Color.clear : (giorno.festivo ? Superficie.incasso.opacity(0.5) : Superficie.incasso)),
                    in: RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous))
        .overlay {
            if giorno.oggi {
                RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous).strokeBorder(Color.accentColor, lineWidth: 1.5)
            } else if giorno.passato {
                RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous).strokeBorder(Superficie.bordo, lineWidth: 1)
            }
        }
        .opacity(giorno.fuori ? 0.6 : 1)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { if !giorno.passato { store.nuovaQui("scadenza", giorno.giorno) } }
        .contextMenu {
            if !giorno.passato {
                Button(cose.t("nuova_nel_giorno").replacingOccurrences(of: "{quando}", with: giorno.quando)) {
                    store.nuovaQui("scadenza", giorno.giorno)
                }
            }
        }
        .dropDestination(for: String.self) { valori, _ in
            store.rilasciaSulGiorno(valori, giorno: giorno.giorno, passato: giorno.passato)
        } isTargeted: { puntata = $0 && !giorno.passato }
        .help(giorno.passato ? cose.t("aiuto_giorno_passato") : cose.t("nuova_nel_giorno").replacingOccurrences(of: "{quando}", with: giorno.quando))
    }
}





@MainActor @Observable
final class ScorrimentoCose {
    static let condiviso = ScorrimentoCose()
    var x: CGFloat = 0

    var altroADestra = false

    var margini: CGFloat = 22

    var barraVerticale: CGFloat = 0

    var carattereIntestazione: NSFont?


    var carattereFoglio: NSFont?
    var marginiFoglio: CGFloat = 0

    var colonneFuori = 0


    var postoFreccia: CGFloat = 16
}


struct MisuraColonna: Equatable {
    var minimo: CGFloat
    var ideale: CGFloat
    var massimo: CGFloat
}




@MainActor
enum MisureColonne {

    static let spazio: CGFloat = 10
    static let minimoTask: CGFloat = 220

    static let massimoLibere: CGFloat = 160


    static let stringeOltre: CGFloat = 96

    static let marginiMenu: CGFloat = 8

    static let rigaFoglio: CGFloat = 22

    static let respiro: CGFloat = 4


    static var spenteDiPartenza: Set<String> {


        Store.infoColonne.isEmpty
            ? ["stato", "cambio", "creata", "inizio", "chiusa", "rinvii", "commenti"]
            : Set(Store.infoColonne.filter { !$0.accesa }.map(\.id))
    }
    private static var cacheTesto: [String: CGFloat] = [:]
    private static var cacheIntestazione: [String: CGFloat] = [:]

    static func testo(_ s: String, _ f: NSFont) -> CGFloat {
        let k = "\(f.fontName)|\(f.pointSize)|\(s)"
        if let w = cacheTesto[k] { return w }
        let w = ceil((s as NSString).size(withAttributes: [.font: f]).width)
        if cacheTesto.count > 20000 { cacheTesto.removeAll() }
        cacheTesto[k] = w
        return w
    }


    static func simbolo(_ nome: String, _ corpo: CGFloat, peso: NSFont.Weight = .regular) -> CGFloat {
        let k = "simbolo|\(nome)|\(corpo)"
        if let w = cacheTesto[k] { return w }
        let conf = NSImage.SymbolConfiguration(pointSize: corpo, weight: peso)
        let w = ceil(NSImage(systemSymbolName: nome, accessibilityDescription: nil)?.withSymbolConfiguration(conf)?.size.width ?? corpo)
        cacheTesto[k] = w
        return w
    }


    static func titoloGrassetto(_ titolo: String, _ corpo: CGFloat?) -> CGFloat {
        let k = "grassetto|\(corpo ?? 0)|\(titolo)"
        if let w = cacheIntestazione[k] { return w }
        let c = NSTableHeaderCell(textCell: titolo)
        c.font = NSFont.systemFont(ofSize: corpo ?? NSFont.smallSystemFontSize, weight: .semibold)
        let w = ceil(c.cellSize(forBounds: NSRect(x: 0, y: 0, width: 1000, height: 28)).width)
        cacheIntestazione[k] = w
        return w
    }




    static func intestazione(_ titolo: String, _ carattere: NSFont?, freccia: CGFloat, segno: String = "") -> CGFloat {


        titoloGrassetto(titolo + segno, carattere?.pointSize) + freccia + respiro
    }


    static func segnoLivello(_ i: Int, _ verso: SortOrder, primo: Bool) -> String {
        let cifra = ["¹", "²", "³"][min(max(i, 0), 2)]
        return " " + cifra + (primo ? "" : (verso == .forward ? "↑" : "↓"))
    }


    static func base(_ titolo: String) -> String {
        var t = titolo
        while let c = t.last, "¹²³↑↓ ".contains(c) { t.removeLast() }
        return t
    }


    static func contenuto(_ id: String, _ righe: [VoceCosa]) -> CGFloat {
        let f12 = NSFont.systemFont(ofSize: 12)
        let f13 = NSFont.systemFont(ofSize: 13)
        let f13m = NSFont.systemFont(ofSize: 13, weight: .medium)
        let cifre = NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular)
        switch id {
        case "priorita":

            return 28 + marginiMenu
        case "scadenza":
            let scaduta = simbolo("exclamationmark.circle", 11) + 3
            let passata = simbolo("clock", 10) + 3
            let w = righe.reduce(simbolo("plus", 11)) { m, v in
                let t = v.scadenza_breve ?? ""
                switch v.tono_breve ?? "vuota" {
                case "vuota": return m
                case "scaduta": return max(m, scaduta + testo(t, f13m))
                case "oggi": return max(m, testo(t, NSFont.systemFont(ofSize: 13, weight: .semibold)))
                case "passata": return max(m, passata + testo(t, f13))
                default: return max(m, testo(t, f13))
                }
            }
            return w + marginiMenu
        case "stima":
            return righe.reduce(simbolo("plus", 11)) { max($0, testo($1.stima_breve ?? "", cifre)) } + marginiMenu
        case "area":
            return righe.reduce(0) { max($0, testo($1.area, f12)) } + marginiMenu
        case "stato":
            let segno = simbolo("circle.lefthalf.filled", 12) + 5
            return righe.reduce(0) { max($0, segno + testo($1.stato_nome ?? "", f12)) } + marginiMenu
        case "cambio":
            return righe.reduce(0) { max($0, testo($1.cambio_breve ?? $1.ultimo_cambio ?? "", f12)) }
        case "creata":
            return righe.reduce(0) { max($0, testo($1.creata_breve ?? $1.creata ?? "", f12)) }
        case "chiusa":
            return righe.reduce(0) { max($0, testo($1.chiusa_breve ?? "", f12)) }
        case "inizio":
            return righe.reduce(simbolo("plus", 11)) { max($0, testo($1.inizio_breve ?? "", f13)) } + marginiMenu
        case "rinvii":
            return righe.reduce(0) { max($0, testo(($1.rinvii ?? 0).formatted(), cifre)) }
        case "commenti":
            let segno = simbolo("text.bubble", 11) + 4
            return righe.reduce(0) { max($0, segno + testo(($1.commenti_n ?? 0).formatted(), cifre)) } + marginiMenu
        default:
            return 0
        }
    }






    @MainActor private static var tenute: [String: [String: MisuraColonna]] = [:]

    @MainActor static func calcolaUnaVolta(_ cose: Cose, store: Store, carattere: NSFont?, livelli: [OrdineCosa]) -> [String: MisuraColonna] {
        let chiave = "\(store.coseGiro)|\(carattere?.fontName ?? "")|\(carattere?.pointSize ?? 0)|\(ScorrimentoCose.condiviso.postoFreccia)|"
            + livelli.map { "\($0.campo)\($0.order == .forward ? "+" : "-")" }.joined(separator: ",")
        if let m = tenute[chiave] { return m }
        let m = calcola(cose, Array(store.coseIndice.values), carattere: carattere, livelli: livelli)
        if tenute.count > 8 { tenute = [:] }
        tenute[chiave] = m
        return m
    }

    static func calcola(_ cose: Cose, _ righe: [VoceCosa], carattere: NSFont?, livelli: [OrdineCosa] = []) -> [String: MisuraColonna] {
        var m: [String: MisuraColonna] = [:]
        for id in Store.colonneAccendibili {
            let campo = cose.colonne_info?.first { $0.id == id }?.campo_ordine ?? id
            var segno = ""
            if livelli.count > 1, let i = livelli.firstIndex(where: { $0.campo == campo }) {
                segno = segnoLivello(i, livelli[i].order, primo: i == 0)
            }
            let testa = intestazione(cose.col(id), carattere, freccia: ScorrimentoCose.condiviso.postoFreccia, segno: segno)
            let dentro = ceil(contenuto(id, righe)) + respiro
            let misura = max(testa, dentro)
            if id == "area" || id == "stato" {

                let ideale = min(max(testa, dentro), max(testa, massimoLibere))
                m[id] = MisuraColonna(minimo: max(testa, min(dentro, stringeOltre)), ideale: ideale, massimo: max(testa, massimoLibere))
            } else {
                m[id] = MisuraColonna(minimo: misura, ideale: misura, massimo: misura)
            }
        }
        return m
    }
}

extension Store {

    static func colonnaAccesa(_ c: TableColumnCustomization<VoceCosa>, _ id: String, tutte: Bool = false) -> Bool {
        let v = c[visibility: id]
        return v != .hidden && !(v == .automatic && !tutte && MisureColonne.spenteDiPartenza.contains(id))
    }



    static func ordineColonne(_ c: TableColumnCustomization<VoceCosa>) -> [String] {
        var ordine: [String] = []
        if let dati = try? JSONEncoder().encode(c),
           let albero = try? JSONSerialization.jsonObject(with: dati) as? [String: Any],
           let fila = albero["columnOrder"] as? [[String: Any]] {
            for x in fila {
                if let base = x["base"] as? [String: Any], let esplicito = base["explicit"] as? [String: Any],
                   let id = esplicito["_0"] as? String { ordine.append(id) }
            }
        }
        let resto = colonneAccendibili.filter { !ordine.contains($0) }
        return ordine.filter { colonneAccendibili.contains($0) } + resto
    }
}








struct AdattaColonne: NSViewRepresentable {

    let titoloTask: String

    let misure: [String: MisuraColonna]

    let chiave: String

    var maiuscolo: (String) -> Void = { _ in }

    var compatto = false


    var cliccata: (String, Int, Bool) -> Void = { _, _, _ in }

    func makeNSView(context: Context) -> NSView { NSView(frame: .zero) }

    func updateNSView(_ v: NSView, context: Context) {
        let c = context.coordinator
        c.titoloTask = titoloTask
        c.misure = misure
        c.maiuscolo = maiuscolo
        c.compatto = compatto
        c.cliccata = cliccata
        if c.chiave != chiave {
            c.chiave = chiave
            c.tirate = [:]
        }
        c.segnaposto = v



        c.controllaMaiuscolo()

        DispatchQueue.main.async {
            c.aggancia(da: v)
            c.adatta()
            c.sorveglia(da: v, volte: 20)
        }
    }

    func makeCoordinator() -> Coordinatore { Coordinatore() }

    @MainActor
    final class Coordinatore: NSObject {
        weak var tabella: NSTableView?
        var titoloTask = ""
        var misure: [String: MisuraColonna] = [:]
        var chiave = ""
        var maiuscolo: (String) -> Void = { _ in }
        var compatto = false
        var cliccata: (String, Int, Bool) -> Void = { _, _, _ in }

        weak var segnaposto: NSView?


        private var eraDavanti = false
        private var xPrima: CGFloat = 0
        private var agganciate = 0
        private var tentativi = 0
        private var sorveglianza = 0
        private var controllo: Any?

        var tirate: [String: CGFloat] = [:]
        private var dentro = false
        private var osservatori: [NSObjectProtocol] = []

        deinit {
            osservatori.forEach(NotificationCenter.default.removeObserver)
            if let controllo { NSEvent.removeMonitor(controllo) }
        }



        func controllaMaiuscolo() {
            guard controllo == nil else { return }
            controllo = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown) { [weak self] e in
                MainActor.assumeIsolated {


                    if let self, self.tabella?.window == nil, let s = self.segnaposto, s.window != nil { self.aggancia(da: s) }

                    if let self, let t = self.tabella, e.window === t.window {
                        self.eraDavanti = t.window?.firstResponder === t
                        if let sv = t.enclosingScrollView { self.xPrima = sv.contentView.bounds.origin.x }
                    }

                    if let self, self.compatto, let t = self.tabella, e.window === t.window {
                        let q = t.convert(e.locationInWindow, from: nil)


                        if t.bounds.contains(q), t.visibleRect.contains(q), Self.colpisce(t, e) {
                            let i = t.column(at: q), r = t.row(at: q)

                            if i >= 0, i < t.tableColumns.count, r >= 0, e.clickCount == 1,
                               e.modifierFlags.intersection([.command, .shift, .control, .option]).isEmpty {
                                let sola = t.selectedRowIndexes.count == 1 && t.selectedRowIndexes.contains(r)
                                self.cliccata(t.tableColumns[i].headerCell.stringValue, r, sola)
                            }
                        }
                    }
                    guard let self, e.modifierFlags.contains(.shift), let t = self.tabella, e.window === t.window,
                          let hv = t.headerView else { return e }
                    let p = hv.convert(e.locationInWindow, from: nil)
                    guard hv.bounds.contains(p) else { return e }
                    let i = hv.column(at: p)
                    guard i >= 0, i < t.tableColumns.count else { return e }

                    let r = hv.headerRect(ofColumn: i)
                    guard p.x > r.minX + 4, p.x < r.maxX - 6 else { return e }
                    self.maiuscolo(MisureColonne.base(t.tableColumns[i].headerCell.stringValue))
                    return nil
                }
            }
        }



        func sorveglia(da v: NSView, volte: Int, giro: Int? = nil) {
            let g = giro ?? { sorveglianza += 1; return sorveglianza }()
            guard volte > 0, g == sorveglianza else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self, weak v] in
                guard let self, let v, v.window != nil else { return }
                if self.aggancia(da: v) { self.adatta() }
                self.sorveglia(da: v, volte: volte - 1, giro: g)
            }
        }


        static func colpisce(_ t: NSTableView, _ e: NSEvent) -> Bool {
            guard let cv = e.window?.contentView else { return false }
            let p = cv.superview.map { $0.convert(e.locationInWindow, from: nil) } ?? e.locationInWindow
            guard let v = cv.hitTest(p) else { return false }
            return v === t || v.isDescendant(of: t)
        }



        @discardableResult
        func aggancia(da v: NSView) -> Bool {
            var su: NSView? = v.superview
            var trovata: NSTableView?
            for _ in 0..<6 where trovata == nil {
                guard let s = su else { break }
                trovata = Self.cerca(in: s, vicinoA: v, titoloTask: titoloTask)
                su = s.superview
            }
            guard let t = trovata, let sv = t.enclosingScrollView else {
                if tabella?.window != nil { return false }



                if tentativi < 60, v.window != nil {
                    tentativi += 1


                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self, weak v] in
                        guard let self, let v else { return }
                        self.aggancia(da: v)
                        self.adatta()
                    }
                }
                return false
            }
            tentativi = 0


            if t === tabella { return false }
            tabella = t
            agganciate += 1
            if agganciate > 1 {
                let davanti = eraDavanti, x = xPrima
                DispatchQueue.main.async { [weak t] in
                    guard let t else { return }
                    if davanti { t.window?.makeFirstResponder(t) }
                    if let r = t.selectedRowIndexes.first { t.scrollRowToVisible(r) }
                    if x > 0, let sv = t.enclosingScrollView {
                        sv.contentView.scroll(to: NSPoint(x: x, y: sv.contentView.bounds.origin.y))
                        sv.reflectScrolledClipView(sv.contentView)
                    }
                }
            }
            controllaMaiuscolo()
            osservatori.forEach(NotificationCenter.default.removeObserver)


            sv.hasHorizontalScroller = true
            sv.autohidesScrollers = true
            sv.scrollerStyle = .legacy
            sv.contentView.postsFrameChangedNotifications = true
            sv.contentView.postsBoundsChangedNotifications = true
            let nc = NotificationCenter.default
            ScorrimentoCose.condiviso.x = sv.contentView.bounds.origin.x
            osservatori = [
                nc.addObserver(forName: NSView.boundsDidChangeNotification, object: sv.contentView, queue: .main) { [weak sv] _ in
                    MainActor.assumeIsolated {

                        guard let sv, let t = sv.documentView else { return }
                        let x = min(max(0, sv.contentView.bounds.origin.x), max(0, t.frame.width - sv.contentView.bounds.width))
                        if abs(ScorrimentoCose.condiviso.x - x) >= 0.5 { ScorrimentoCose.condiviso.x = x }
                        Self.pubblica(sv)
                    }
                },
                nc.addObserver(forName: NSView.frameDidChangeNotification, object: sv.contentView, queue: .main) { [weak self] _ in
                    MainActor.assumeIsolated {
                        self?.adatta()

                        DispatchQueue.main.async { self?.adatta() }
                    }
                },
                nc.addObserver(forName: NSTableView.columnDidResizeNotification, object: t, queue: .main) { [weak self] n in
                    MainActor.assumeIsolated {

                        guard let self, !self.dentro, let col = n.userInfo?["NSTableColumn"] as? NSTableColumn,
                              MisureColonne.base(col.headerCell.stringValue) != self.titoloTask,
                              NSApp.currentEvent?.type == .leftMouseDragged else { return }
                        self.tirate[MisureColonne.base(col.headerCell.stringValue)] = col.width
                        self.adatta()
                    }
                },
            ]
            return true
        }


        static func cerca(in radice: NSView, vicinoA v: NSView, titoloTask: String) -> NSTableView? {
            func tutte(_ x: NSView) -> [NSTableView] { (x as? NSTableView).map { [$0] } ?? x.subviews.flatMap(tutte) }
            let qui = v.convert(v.bounds, to: nil)
            guard !qui.isEmpty else { return nil }
            return tutte(radice).first { t in
                guard let sv = t.enclosingScrollView, t.window != nil,
                      t.tableColumns.contains(where: { MisureColonne.base($0.headerCell.stringValue) == titoloTask }) else { return false }
                return sv.convert(sv.bounds, to: nil).intersects(qui)
            }
        }


        static func parteVisibile(_ sv: NSScrollView) -> CGFloat {
            let clip = sv.contentView.frame
            var destra = clip.maxX


            if sv.scrollerStyle == .legacy, sv.hasVerticalScroller, let t = sv.documentView,
               t.frame.height > sv.contentView.bounds.height + 0.5 {
                let w = (sv.verticalScroller?.frame.width ?? 0) > 0 ? sv.verticalScroller!.frame.width
                    : NSScroller.scrollerWidth(for: .regular, scrollerStyle: .legacy)
                destra = min(destra, max(clip.minX, sv.bounds.width - w))
            }
            return destra - clip.minX
        }


        static func pubblica(_ sv: NSScrollView) {
            guard let t = sv.documentView else { return }
            let s = ScorrimentoCose.condiviso
            let fine = sv.contentView.bounds.minX + parteVisibile(sv)
            let oltre = t.frame.width - fine > 1
            if s.altroADestra != oltre { s.altroADestra = oltre }
            if let tv = t as? NSTableView {
                let fuori = tv.tableColumns.indices.filter { !tv.tableColumns[$0].isHidden && tv.rect(ofColumn: $0).maxX > fine + 1 }.count
                if s.colonneFuori != fuori { s.colonneFuori = fuori }
            }


            let sf = sv.subviews.compactMap { $0 as? SfumaturaDestra }.first ?? {
                let v = SfumaturaDestra(frame: .zero)
                sv.addSubview(v, positioned: .above, relativeTo: sv.contentView)
                return v
            }()
            let cv = sv.contentView.frame
            let bordo = cv.minX + parteVisibile(sv)
            sf.frame = NSRect(x: bordo - SfumaturaDestra.larghezza, y: cv.minY, width: SfumaturaDestra.larghezza, height: cv.height)
            sf.isHidden = !oltre
            let barra = sv.scrollerStyle == .legacy && sv.hasVerticalScroller && sv.verticalScroller?.isHidden == false
                ? (sv.verticalScroller?.frame.width ?? 0) : 0
            if s.barraVerticale != barra { s.barraVerticale = barra }
        }


        func adatta() {


            if tabella?.window == nil, let s = segnaposto, s.window != nil { aggancia(da: s) }
            guard !dentro, let t = tabella, let sv = t.enclosingScrollView else { return }
            let colonne = t.tableColumns.filter { !$0.isHidden }
            guard let task = colonne.first(where: { MisureColonne.base($0.headerCell.stringValue) == titoloTask }) else { return }
            dentro = true
            defer { dentro = false }
            eraDavanti = t.window?.firstResponder === t
            xPrima = sv.contentView.bounds.origin.x


            if compatto, !t.gridStyleMask.contains(.solidVerticalGridLineMask) {
                t.gridStyleMask.insert(.solidVerticalGridLineMask)
                t.gridColor = .separatorColor
            }
            let minimoTask = MisureColonne.minimoTask
            if t.intercellSpacing.width != MisureColonne.spazio {
                t.intercellSpacing = NSSize(width: MisureColonne.spazio, height: t.intercellSpacing.height)
            }
            if sv.scrollerStyle != .legacy { sv.scrollerStyle = .legacy }
            task.minWidth = minimoTask
            task.maxWidth = 10000

            task.resizingMask = [.autoresizingMask, .userResizingMask]

            if let f = task.headerCell.font {
                if compatto, ScorrimentoCose.condiviso.carattereFoglio != f { ScorrimentoCose.condiviso.carattereFoglio = f }
                if !compatto, ScorrimentoCose.condiviso.carattereIntestazione != f { ScorrimentoCose.condiviso.carattereIntestazione = f }
            }
            let altre = colonne.filter { $0 !== task }



            for c in colonne where (c.headerCell.font?.fontName ?? "").contains("Semibold") {
                let solo = MisureColonne.titoloGrassetto(c.headerCell.stringValue, c.headerCell.font?.pointSize)
                let extra = ceil(c.headerCell.cellSize(forBounds: NSRect(x: 0, y: 0, width: 1000, height: 28)).width) - solo


                if extra > ScorrimentoCose.condiviso.postoFreccia + 0.5 { ScorrimentoCose.condiviso.postoFreccia = extra }
            }
            var base: [ObjectIdentifier: CGFloat] = [:]
            for c in altre {
                let titolo = MisureColonne.base(c.headerCell.stringValue)
                if let m = misure[titolo] {

                    if c.minWidth != m.minimo || c.maxWidth != m.massimo {
                        c.minWidth = 0
                        c.maxWidth = m.massimo
                        c.minWidth = m.minimo
                    }
                    c.resizingMask = m.minimo < m.massimo ? [.userResizingMask] : []
                    base[ObjectIdentifier(c)] = min(max(tirate[titolo] ?? m.ideale, m.minimo), m.massimo)
                } else {
                    c.resizingMask = []
                    base[ObjectIdentifier(c)] = c.width
                }
            }


            let prima = t.tableColumns.firstIndex { !$0.isHidden } ?? 0
            let margini = 2 * max(0, t.rect(ofColumn: prima).minX) + 2
            if compatto {
                if abs(ScorrimentoCose.condiviso.marginiFoglio - margini) >= 0.5 { ScorrimentoCose.condiviso.marginiFoglio = margini }
            } else if abs(ScorrimentoCose.condiviso.margini - margini) >= 0.5 { ScorrimentoCose.condiviso.margini = margini }
            let spazi = t.intercellSpacing.width * CGFloat(colonne.count) + margini



            let vede = Self.parteVisibile(sv)
            let somma = altre.reduce(CGFloat(0)) { $0 + (base[ObjectIdentifier($1)] ?? $1.width) }
            var resto = vede - spazi - somma
            if resto < minimoTask {


                let margine = altre.reduce(CGFloat(0)) { $0 + max(0, (base[ObjectIdentifier($1)] ?? $1.width) - $1.minWidth) }
                if margine > 0, resto + margine >= minimoTask {
                    let serve = minimoTask - resto
                    for c in altre {
                        let b = base[ObjectIdentifier(c)] ?? c.width
                        base[ObjectIdentifier(c)] = (b - (b - c.minWidth) / margine * serve).rounded(.down)
                    }
                    resto = vede - spazi - altre.reduce(CGFloat(0)) { $0 + (base[ObjectIdentifier($1)] ?? $1.width) }
                }
            }
            for c in altre {
                let w = base[ObjectIdentifier(c)] ?? c.width


                if abs(c.width - w) >= 1 { c.width = w.rounded() }
            }
            let nuova = max(minimoTask, resto.rounded(.down))
            if abs(task.width - nuova) >= 1 { task.width = nuova }


            t.tile()
            Self.pubblica(sv)
        }
    }
}



final class SfumaturaDestra: NSView {
    static let larghezza: CGFloat = 28
    override var isFlipped: Bool { true }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func draw(_ dirtyRect: NSRect) {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            let fondo = NSColor.controlBackgroundColor
            NSGradient(starting: fondo.withAlphaComponent(0), ending: fondo)?.draw(in: bounds, angle: 0)
        }
    }
    override func viewDidChangeEffectiveAppearance() { needsDisplay = true }
}

extension TableColumn {

    func larghezza(_ m: MisuraColonna) -> TableColumn<RowValue, Sort, Content, Label> {
        width(min: m.minimo, ideal: m.ideale, max: m.massimo)
    }
}


struct CellaData: View {
    let testo: String
    let aiuto: String?
    var cifre = false
    var body: some View {
        Text(testo).font(.system(size: 12)).monospacedDigit().foregroundStyle(.secondary)
            .lineLimit(1).truncationMode(.tail)
            .help(aiuto ?? "")
    }
}



struct CellaInizio: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    @State private var sopra = false

    var body: some View {
        MenuCella(aiuto: voce.inizio_aiuto ?? cose.t("aiuto_inizio"),
                  spento: store.coseOccupate.contains(voce.id) || voce.aperta == false) {
            ForEach(cose.scelte_data ?? []) { s in
                Button(s.nome) { Task { await store.gestoTask("pianifica", [voce.id], [s.id]) } }
            }
            Divider()
            Button(cose.t("togli_dal_calendario")) { Task { await store.gestoTask("pianifica", [voce.id], ["togli"]) } }
                .disabled(voce.pianificata == nil)
        } etichetta: {
            if let t = voce.inizio_breve, !t.isEmpty {
                Text(t).font(.system(size: 13, weight: voce.tono_inizio == "oggi" ? .medium : .regular))
                    .foregroundStyle(Self.colore(voce.tono_inizio, oltre: voce.oltre_scadenza == true))
            } else {
                Image(systemName: "plus").font(.system(size: 11)).foregroundStyle(.tertiary).opacity(sopra ? 1 : 0)
            }
        }
        .onHover { sopra = $0 }
    }

    static func colore(_ tono: String?, oltre: Bool) -> Color {

        if oltre || tono == "da_ripianificare" { return .primary }
        switch tono {
        case "oggi": return .primary
        case "vicina": return .primary
        default: return .secondary
        }
    }
}


struct CellaCommenti: View {
    let cose: Cose
    let voce: VoceCosa
    let store: Store
    var body: some View {
        if let n = voce.commenti_n, n > 0 {
            Button {
                store.coseScelte = [voce.id]
                store.cosaAperta = voce.id
                store.dettaglioCose = true
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "text.bubble").font(.system(size: 11))
                    Text(n.formatted()).font(.system(size: 12)).monospacedDigit()
                }
                .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help(voce.ultimo_commento_parole ?? cose.t("aiuto_commenti_colonna"))
        }
    }
}



struct MenuOrdineCose: View {
    let cose: Cose
    let store: Store
    let scheda: SchedaCose

    var body: some View {
        let livelli = store.livelliOrdine
        Menu(cose.t("menu_ordine")) {
            livello(0, livelli)
            if !livelli.isEmpty { livello(1, livelli) }
            if livelli.count > 1 { livello(2, livelli) }
            Divider()
            Button(cose.t("torna_ordine_vista")) { store.impostaOrdine(scheda, []) }
                .disabled(livelli.isEmpty)
        }
    }

    @ViewBuilder
    private func livello(_ i: Int, _ livelli: [OrdineVista]) -> some View {
        let ora = i < livelli.count ? livelli[i] : nil
        let presi = Set(livelli.prefix(i).map(\.campo))
        let campi = (cose.ordini ?? []).filter { $0.id != "pronto" && !presi.contains($0.id) }
        Menu(cose.t(["ordina_per", "poi_per", "poi_ancora_per"][i])) {
            if i > 0 {
                Toggle(cose.t("ordine_nessuno"), isOn: Binding(get: { ora == nil }, set: { _ in
                    store.impostaOrdine(scheda, Array(livelli.prefix(i)))
                }))
                Divider()
            }
            ForEach(campi) { o in
                Toggle(o.nome, isOn: Binding(get: { ora?.campo == o.id }, set: { _ in
                    var nuovi = Array(livelli.prefix(i))
                    nuovi.append(OrdineVista(campo: o.id, verso: o.verso_di_partenza ?? store.versoDiPartenza(o.id)))

                    nuovi += livelli.dropFirst(i + 1).filter { $0.campo != o.id }
                    store.impostaOrdine(scheda, nuovi)
                }))
            }
            if let ora, let o = cose.ordini?.first(where: { $0.id == ora.campo }) {
                Divider()
                ForEach(["su", "giu"], id: \.self) { v in
                    Toggle((v == "su" ? o.su : o.giu) ?? cose.t("verso_\(o.id)_\(v)"), isOn: Binding(get: { ora.verso == v }, set: { _ in
                        var nuovi = livelli
                        nuovi[i] = OrdineVista(campo: ora.campo, verso: v)
                        store.impostaOrdine(scheda, nuovi)
                    }))
                }
            }
        }
    }
}

extension Store {


    static func cassettoChiuso(_ cose: Cose, _ scadute: Int, _ senza: Int) -> String {
        guard cose.testi?["cassetto_unisci"] != nil else {
            return cose.t("cassetto_chiuso").replacingOccurrences(of: "{s}", with: scadute.formatted())
                .replacingOccurrences(of: "{n}", with: senza.formatted())
        }
        let a = scadute == 1 ? cose.t("cassetto_scaduta") : cose.t("cassetto_scadute").replacingOccurrences(of: "{n}", with: scadute.formatted())
        let b = cose.t("cassetto_senza").replacingOccurrences(of: "{n}", with: senza.formatted())
        return cose.t("cassetto_unisci").replacingOccurrences(of: "{a}", with: a).replacingOccurrences(of: "{b}", with: b)
    }
}



struct RispostaCommenti: Decodable {
    struct Voce: Decodable, Identifiable {

        let eid: String?
        let t: String?
        let tipo: String?
        let quando: String?
        let genere: String?
        let testo: String?
        let da_parole: String?
        let via: String?
        let audio: String?
        let cosa: String?
        let chi_parole: String?
        var id: String { eid ?? "\(t ?? "")|\(tipo ?? "")|\(cosa ?? testo ?? "")" }
    }
    let ok: Bool
    let vuoto: String?
    let commenti: [Voce]?
    let filo: [Voce]?
}




struct CommentiCosa: View {
    let cose: Cose
    let store: Store
    let voce: VoceCosa
    @State private var risposta: RispostaCommenti?
    @State private var cambi = false
    @State private var sopra: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(cose.t("commenti_titolo")).font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary)
                Spacer()
                Toggle(cose.t("commenti_mostra_cambi"), isOn: $cambi).toggleStyle(.checkbox).controlSize(.small)
                    .font(.system(size: 11))
            }
            let voci = (cambi ? risposta?.filo : risposta?.commenti) ?? []
            if voci.isEmpty {
                Text(risposta?.vuoto ?? cose.t("commenti_vuoto")).font(.system(size: 12)).foregroundStyle(.tertiary)
            }
            ForEach(voci) { v in riga(v) }

            CampoVoce(testo: Binding(get: { store.coseBozzeCommento[voce.id] ?? "" },
                                     set: { store.coseBozzeCommento[voce.id] = $0.isEmpty ? nil : $0 }), segnaposto: cose.t("commenta_segnaposto"),
                      voce: Registrazione.attivita, chiave: "commento-\(voce.id)", cosa: cose.t("commenti_titolo"),
                      cartella: store.cartellaDettati, cartellaRegistro: store.cartellaDettati,
                      testi: { store.tv($0) },
                      mandaTesto: { t in
                          let e = await store.gestoTask("commenta", [voce.id], [t])
                          await leggi()
                          return e?.ok == true
                      },
                      mandaAudio: { r in _ = await store.mandaDettato(r); await leggi() },
                      spento: voce.eliminata == true, righe: 1...4)
        }
        .task(id: "\(voce.id)|\(voce.commenti_n ?? 0)") { await leggi() }
    }

    @ViewBuilder
    private func riga(_ v: RispostaCommenti.Voce) -> some View {
        let commento = (v.genere ?? "commento") == "commento"
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: commento ? (v.via == "voce" ? "waveform" : "text.bubble") : "arrow.triangle.2.circlepath")
                .font(.system(size: 11)).foregroundStyle(.tertiary).frame(width: 14)
            VStack(alignment: .leading, spacing: 2) {
                Text([v.quando, commento ? v.da_parole : v.chi_parole].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                Text((commento ? v.testo : v.cosa) ?? "").font(.system(size: commento ? 13 : 12))
                    .foregroundStyle(commento ? .primary : .secondary)
                    .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                if commento, let a = v.audio, !a.isEmpty {
                    Button(store.t("ascolta")) { NSWorkspace.shared.open(URL(fileURLWithPath: a)) }.buttonStyle(.link).font(.system(size: 11))
                }
            }
            Spacer(minLength: 0)
            if commento, let eid = v.eid, sopra == v.id, voce.eliminata != true {
                Button { Task { await store.gestoTask("commento-togli", [eid]); await leggi() } } label: {
                    Image(systemName: "xmark").font(.system(size: 10))
                }
                .buttonStyle(.borderless).foregroundStyle(.secondary).help(cose.t("aiuto_togli_commento"))
            }
        }
        .contentShape(Rectangle())
        .onHover { sopra = $0 ? v.id : (sopra == v.id ? nil : sopra) }
    }


    private func leggi() async {
        let r = await store.motore.chiedi(["cose", "commenti", voce.id], scadenza: 15)
        if let d = try? JSONDecoder().decode(RispostaCommenti.self, from: r.dati), d.ok { risposta = d }
    }
}
