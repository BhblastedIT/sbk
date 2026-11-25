import AppKit
import SwiftUI



extension Notification.Name {

    static let sbCerca = Notification.Name("local.sbk.secondbrain.cerca")

    static let sbNuovaTask = Notification.Name("local.sbk.secondbrain.nuovatask")
}

struct Principale: View {
    @Environment(Store.self) private var store
    @FocusState private var ricercaAttiva: Bool

    var body: some View {
        @Bindable var store = store
        NavigationSplitView {
            BarraLaterale()
                .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
        } detail: {



            HStack(spacing: 0) {
                Contenuto()


                if store.pannelloFiltriAVista {
                    Rectangle().fill(Superficie.separatore).frame(width: 1)
                    PannelloFiltriBacheca()
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
                if store.ispettore {
                    Rectangle().fill(Superficie.separatore).frame(width: 1)
                    Ispettore()
                        .frame(width: 320)
                        .frame(maxHeight: .infinity)
                        .background(Superficie.scheda)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            .animation(.smooth(duration: 0.25), value: store.ispettore)
            .animation(.smooth(duration: 0.25), value: store.pannelloFiltriAVista)
            .toolbar(removing: .title)
            .toolbar { BarraInAlto() }
        }


        .searchable(text: $store.ricerca, placement: .sidebar, prompt: "Search sources, runs and commands")
        .searchFocused($ricercaAttiva)
        .onReceive(NotificationCenter.default.publisher(for: .sbCerca)) { _ in ricercaAttiva = true }
        .navigationTitle("SBK")


        .background(SegnaFinestraPrincipale())
        .background(AperturaImpostazioni())
        .sheet(item: $store.foglio) { foglio in
            FoglioView(foglio: foglio)
        }
    }
}



struct SegnaFinestraPrincipale: NSViewRepresentable {
    final class Vista: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let w = window { Store.finestraPrincipale = w }
        }
    }
    func makeNSView(context: Context) -> Vista { Vista() }
    func updateNSView(_ nsView: Vista, context: Context) {}
}


struct Contenuto: View {
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            if store.cartellaMancante && store.stato == nil {
                CartellaMancante()
            } else if let stato = store.stato, !store.ricerca.trimmingCharacters(in: .whitespaces).isEmpty {
                PaginaRicerca(stato: stato)
            } else if let stato = store.stato {
                switch store.sezione {
                case .cose: PaginaCose(stato: stato)
                case .panoramica: Panoramica(stato: stato)
                case .fonti: PaginaFonti(stato: stato)
                case .pipeline: PaginaPipeline(stato: stato)
                case .run: PaginaRun(stato: stato)
                case .spesa: PaginaSpesa(stato: stato)
                case .regole: PaginaRegole(stato: stato)
                case .strumenti: PaginaStrumenti(stato: stato)
                case .posta: PaginaPosta(stato: stato)
                case .firme: PaginaFirme(stato: stato)
                case .pagine: PaginaPagine(stato: stato)
                case .inspiration: PaginaInspiration(stato: stato)
                case .plaud: PaginaPlaud(stato: stato)
                }
            } else {
                Caricamento()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Superficie.pagina)
    }
}


struct PaginaScorrevole<Contenuto: View>: View {
    let stato: Stato
    let titolo: String
    let sottotitolo: String

    var vaiA: String? = nil
    @ViewBuilder var contenuto: () -> Contenuto

    var body: some View {
        ScrollViewReader { lettore in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Fasce(stato: stato)
                    TitoloPagina(titolo: titolo, sottotitolo: sottotitolo)
                    contenuto()
                }
                .padding(.horizontal, 28)
                .padding(.top, 18)
                .padding(.bottom, 28)
                .frame(maxWidth: 1240, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onChange(of: vaiA) { _, nuovo in
                if let nuovo { withAnimation(.smooth(duration: 0.3)) { lettore.scrollTo(nuovo, anchor: .top) } }
            }
        }





        .frame(minWidth: 380, idealWidth: 560, maxWidth: .infinity)
    }
}



struct BarraLaterale: View {
    @Environment(Store.self) private var store

    var body: some View {

        let scelta = Binding<Sezione?>(get: { store.sezione }, set: { if let s = $0 { store.sezione = s; store.ricerca = "" } })
        List(selection: scelta) {

            Section {
                VoceBarra(sezione: .cose)
                    .tag(Sezione.cose)
            }
            Section {
                ForEach(Sezione.allCases.filter { $0 != .cose }) { s in
                    VoceBarra(sezione: s)
                        .tag(s)
                }
            } header: {
                Text("SBK")
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            PiedeBarra()
        }
    }
}

struct VoceBarra: View {
    let sezione: Sezione
    @Environment(Store.self) private var store

    var body: some View {
        let vivo = sezione == .run && (store.runVivo != nil || store.stato?.da_fuori.attivo == true)
        Label {
            HStack(spacing: 5) {
                Text(sezione.nome)
                if sezione == .cose, let segno = store.voceSegno {

                    Image(systemName: segno == "registra" ? "mic.fill" : (segno == "chiede" ? "questionmark.circle.fill" : "waveform"))
                        .font(.system(size: 10))
                        .foregroundStyle(segno == "registra" ? Color.red : (segno == "chiede" ? Salute.attenzione.colore : Color.secondary))
                        .symbolEffect(.pulse, options: .repeating, isActive: segno != "chiede")
                        .help(store.t(segno == "registra" ? "aiuto_voce_registra" : (segno == "chiede" ? "aiuto_voce_chiede" : "aiuto_voce_lavora")))
                }
            }
        } icon: {
            Image(systemName: sezione.simbolo)
                .symbolEffect(.pulse, options: .repeating, isActive: vivo)
        }
        .badge(conteggio)

        .help(sezione == .cose ? (store.cose?.testi?["aiuto_barra"]
                                  ?? store.cose?.aiuto_numero.map { "\(store.t("sottotitolo")) \($0) (⌘T)" } ?? sezione.aiuto) : sezione.aiuto)
    }


    private var conteggio: Int {

        if sezione == .cose { return store.cose?.davanti ?? 0 }
        guard let s = store.stato else { return 0 }
        switch sezione {
        case .fonti:
            return s.fonti.filter {
                ["a_mano", "da_sole", "inventari"].contains($0.gruppo) && ["attenzione", "errore"].contains($0.salute)
            }.count
        case .pipeline:

            return s.stadi.filter { $0.salute == "errore" }.count
        case .panoramica:



            return s.da_sistemare.filter { $0.livello == "errore" }.count
        case .inspiration:


            return store.inspiration?.aspettano_te_nuovi ?? store.inspiration?.aspettano_te
                ?? store.inspiration?.fasi?.first { $0.id == "tutti" }?.aspettano_te ?? 0
        default:
            return 0
        }
    }
}



struct PiedeBarra: View {
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let m = store.stato?.memoria {
                RigaMac(memoria: m, sonno: store.stato?.sonno)
            }
            rigaLettura
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    private var rigaLettura: some View {
        HStack(spacing: 6) {
            if store.leggendo {
                ProgressView().controlSize(.mini)
            } else {
                Image(systemName: store.errore == nil ? "checkmark.circle" : Simbolo.attenzione)
                    .foregroundStyle(store.errore == nil ? Color.secondary : Salute.attenzione.colore)
            }
            Text(riga).lineLimit(2)
                .help("When the app last read the state from the engine. While it is open it re-reads it on its own.")
            Spacer(minLength: 0)
            Button {
                Task { await store.aggiorna(fresco: true) }
            } label: {
                Image(systemName: Simbolo.aggiorna)
            }
            .buttonStyle(.borderless)
            .help("Reread now (⌘R)")
            .disabled(store.leggendo)
            Button {
                store.foglio = .guida
            } label: {
                Image(systemName: "questionmark.circle")
            }
            .buttonStyle(.borderless)
            .help("How to read SBK")
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private var riga: String {
        guard let quando = store.lettoAlle else { return "Not read yet" }
        let ora = Quando.ora24(quando)
        if store.daCache { return "State as of \(ora), checking…" }
        if store.errore != nil { return "Not updated, read at \(ora)" }
        return "Updated at \(ora)"
    }
}


struct RigaMac: View {
    let memoria: Memoria
    let sonno: Sonno?

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "laptopcomputer").foregroundStyle(colore)
            Text(testo).lineLimit(1)
            Spacer(minLength: 0)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .help("Memory is how close the compressor is to the limit, the measure that foreshadows Mac freezes. Below 50% it's calm, above 80% a long run is risky.")
    }


    private var testo: String {
        var pezzi: [String] = []
        if let p = memoria.pressione_pct { pezzi.append("Memory \(p)%") }
        if let s = sonno, s.alimentazione == "batteria" {
            pezzi.append("battery\(s.carica.map { " \($0)%" } ?? "")")
        } else if let libero = memoria.disco_libero_gb {
            pezzi.append("\(libero) GB free")
        }
        return pezzi.isEmpty ? "Mac" : pezzi.joined(separator: " · ")
    }

    private var colore: Color {
        guard let p = memoria.pressione_pct else { return .secondary }
        if p >= 80 { return Salute.errore.colore }
        if p >= 50 { return Salute.attenzione.colore }
        return Salute.ok.colore
    }
}



struct BarraInAlto: ToolbarContent {
    @Environment(Store.self) private var store

    var body: some ToolbarContent {



        ToolbarItem(placement: .principal) {
            HStack(spacing: Spazio.fratelli) {
                Capsula()
                SegnoAvvisi()
            }
        }
        .prioritaBarra(.alta)




        ToolbarItemGroup(placement: .primaryAction) {
            MenuRun()
        }
        .prioritaBarra(.alta)
        ToolbarSpacer(.fixed, placement: .primaryAction)
        ToolbarItem(placement: .primaryAction) {
            Button {

                if store.sezione == .cose {
                    if store.dettaglioCose { store.dettaglioCose = false }
                    else if let id = store.idsAzione.first { store.cosaAperta = id; store.dettaglioCose = true }
                } else {
                    store.ispettore.toggle()
                }
            } label: {
                Label("Detail", systemImage: Simbolo.ispettore)
            }
            .help("Shows or hides the detail of the selected thing (⌥⌘I)")
        }
        .prioritaBarra(.bassa)




        ToolbarItem(placement: .primaryAction) {
            PulsanteCompleta()
        }
    }
}



enum PrioritaBarra { case alta, bassa }

extension ToolbarContent {



    @ToolbarContentBuilder
    func prioritaBarra(_ p: PrioritaBarra) -> some ToolbarContent {
        #if compiler(>=6.4)
        if #available(macOS 26.1, *) {
            self.visibilityPriority(p == .alta ? .high : .low)
        } else {
            self
        }
        #else
        self
        #endif
    }
}


struct PulsanteCompleta: View {
    @Environment(Store.self) private var store

    var body: some View {
        if store.runVivo == nil, let stato = store.stato {
            Button {
                store.apriSpesa()
            } label: {
                Label {
                    Text(stato.c("bottone"))
                } icon: {
                    Image(systemName: Simbolo.completa).foregroundStyle(.purple)
                }
            }
            .labelStyle(.titleAndIcon)
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(store.occupato)
            .help(aiuto(stato))
        }
    }

    private func aiuto(_ stato: Stato) -> String {
        if store.occupato { return store.daCache ? "Checking what's running, one moment." : stato.azioni.perche }
        var t = stato.c("aiuto_bottone")
        if let totale = store.stima?.totale {
            t += " " + stato.c("aiuto_bottone_stima", ["cifra": stato.c("cifra", ["n": Cifre.conPunti(totale)])])
        }
        return t
    }
}



enum Cifre {
    static func conPunti(_ x: Double) -> String { conPunti(Int(x.rounded())) }

    static func conPunti(_ n: Int) -> String {
        let cifre = String(abs(n))
        var gruppi: [String] = []
        var fine = cifre.endIndex
        while fine > cifre.startIndex {
            let inizio = cifre.index(fine, offsetBy: -3, limitedBy: cifre.startIndex) ?? cifre.startIndex
            gruppi.insert(String(cifre[inizio..<fine]), at: 0)
            fine = inizio
        }
        return (n < 0 ? "-" : "") + gruppi.joined(separator: ".")
    }
}




struct Capsula: View {
    @Environment(Store.self) private var store

    var body: some View {
        Button {
            store.sezione = .run
        } label: {
            HStack(spacing: Spazio.fratelli) {
                contenuto
            }
            .lineLimit(1)
            .font(.callout)
            .padding(.horizontal, 12)

            .frame(maxWidth: store.runVivo != nil || store.stato?.da_fuori.attivo == true ? 460 : 340)
            .overlay(alignment: .bottomLeading) { lineaAvanzamento }
        }
        .buttonStyle(.plain)
        .help(aiutoCapsula)
    }


    private var aiutoCapsula: String {
        let c = store.stato?.capsula
        if store.runVivo != nil { return c?.aiuto_run ?? "" }
        if store.stato?.da_fuori.attivo == true { return c?.aiuto_terminale ?? "" }
        return c?.aiuto ?? ""
    }


    @ViewBuilder private var lineaAvanzamento: some View {
        let frazione = store.runVivo != nil
            ? (store.avanzamento ?? store.runVivo?.avanzamento)?.previsione?.frazione_tempo
            : (store.stato?.da_fuori.attivo == true ? store.stato?.da_fuori.giro?.previsione?.frazione_tempo : nil)
        if let f = frazione {
            GeometryReader { g in
                Capsule().fill(Salute.inCorso.colore)
                    .frame(width: max(4, g.size.width * min(1, max(0, f))), height: 2)
                    .frame(maxHeight: .infinity, alignment: .bottom)
            }
            .padding(.horizontal, 12)
            .accessibilityHidden(true)
        }
    }

    @ViewBuilder private var contenuto: some View {
        if let r = store.runVivo {
            if (store.comandiRun ?? r.comandi)?.continua.possibile == true {
                Image(systemName: "pause.circle.fill").foregroundStyle(.orange)
            } else {
                ProgressView().controlSize(.small)
            }
            Text(r.nome ?? "Run").fontWeight(.semibold)

            let pausa = (store.comandiRun ?? r.comandi)?.frase ?? ""
            Text(store.fermoRichiesto.contains(r.run_id) ? "stopping" : (pausa.isEmpty ? (store.rigaRun ?? r.riga ?? "") : pausa))
                .foregroundStyle(.secondary)
        } else if let s = store.stato, s.da_fuori.attivo {
            ProgressView().controlSize(.small)
            Text(s.capsula?.da_terminale ?? "").fontWeight(.semibold)
            Text(s.da_fuori.frase).foregroundStyle(.secondary)
        } else if let c = store.stato?.capsula {
            let salute = Salute(motore: c.salute)
            Image(systemName: Simbolo.da(c.simbolo) ?? salute.simbolo).foregroundStyle(salute.colore)
            Text(c.frase)
        } else if let g = store.stato?.ultimo_full_run, let inizio = g.inizio {

            let (segnale, coda) = Self.esito(g)
            Image(systemName: segnale.simbolo).foregroundStyle(segnale.salute.colore)
            Text(g.frase ?? "last full run \(Quando.frase(inizio))\(coda)")
        }
    }
}

extension Capsula {
    static func esito(_ g: Giro) -> (Segnale, String) {
        if let esito = g.esito, let parola = g.parola {
            let salute = Salute(motore: g.salute ?? "neutra")
            let simbolo = esito == "finito" ? "checkmark.circle.fill" : (esito == "fermato" ? Simbolo.fermato : salute.simbolo)
            return (Segnale(salute: salute, simbolo: simbolo, parola: parola), ", \(parola)")
        }
        if g.fine == nil && g.vivo != true {
            return (Segnale(salute: .attenzione, parola: "not finished"), ", not finished")
        }
        if g.fermato == true {
            return (Segnale(salute: .neutra, simbolo: Simbolo.fermato, parola: "stopped by you"), ", stopped by you")
        }

        if let nc = g.non_chiusi, !nc.isEmpty, nc != "nessuno" {
            return (Segnale(salute: .attenzione, parola: "with unclosed steps"), ", with unclosed steps")
        }
        return (Segnale(salute: .ok, simbolo: "checkmark.circle.fill", parola: "finished"), "")
    }
}




struct PulsantiRun: View {
    @Environment(Store.self) private var store

    var body: some View {
        if let r = store.runVivo {
            PulsantePausa(run: r)
            Button(role: .destructive) {
                store.foglio = .ferma(r)
            } label: {
                Label(store.fermoRichiesto.contains(r.run_id) ? "Stopping" : "Stop", systemImage: Simbolo.ferma)
            }
            .labelStyle(.titleAndIcon)
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .disabled(store.fermoRichiesto.contains(r.run_id))
            .help("Stop the run (⌘.)")
        }
    }
}





struct Fasce: View {



    enum Quali { case tutte, pagina, segno }

    let stato: Stato

    var quali: Quali? = nil

    var pulsantiSotto = false
    @Environment(Store.self) private var store

    @AppStorage("lavoriNascosti") private var nascosti = ""

    var body: some View {
        let q = quali ?? (store.avvisiInteri ? .tutte : .pagina)

        let diSistema = q != .pagina

        let diPagina = q != .segno


        VStack(alignment: .leading, spacing: Spazio.fratelli) {



            if diSistema, let lav = stato.lavori, lav.letto, let primo = lav.errori.first, !lav.frase.isEmpty,
               !chiavi(lav).allSatisfy(nascoste.contains) {
                Fascia(salute: .errore, testo: lav.frase, dettaglio: nil, pulsantiSotto: pulsantiSotto) {
                    if let azione = primo.azione {
                        Button(azione.etichetta) { store.esegui(azione, oggetto: primo.oggetto) }
                    }
                    Button("Hide until the next error") { nascosti = chiavi(lav).joined(separator: "\n") }
                }
            }
            if diSistema, let errore = store.errore {

                Fascia(salute: .attenzione,
                       testo: store.lettoAlle.map { "\(errore) What you see is from \(Quando.ora24($0))." }
                           ?? "\(errore) What you see is the last saved copy.",
                       dettaglio: store.dettaglioErrore, pulsantiSotto: pulsantiSotto) {
                    Button("Retry") { Task { await store.aggiorna(fresco: true) } }
                }
            }
            if diSistema, (stato.contratto ?? 0) != contrattoAtteso {
                Fascia(salute: .attenzione, testo: Self.fraseContratto, dettaglio: nil, pulsantiSotto: pulsantiSotto) { EmptyView() }
            } else if store.aggiornando {

                if diPagina {
                    Fascia(salute: .inCorso,
                           testo: "Updating SBK. In a minute or two it closes and reopens on its own, runs in progress continue.",
                           dettaglio: store.logAggiornamento, pulsantiSotto: pulsantiSotto) { EmptyView() }
                }
            } else if diSistema, store.aggiornamentoDisponibile {
                let mia = Bundle.main.object(forInfoDictionaryKey: "SBCommitApp") as? String ?? ""
                Fascia(salute: .neutra, testo: Self.fraseVersioneNuova,
                       dettaglio: "This app comes from commit \(mia), the latest one that changed it is \(stato.impronta?.app ?? "").",
                       pulsantiSotto: pulsantiSotto) {
                    Button("Update now") { Task { await store.aggiornaApp() } }
                        .buttonStyle(.borderedProminent)
                }
            }


            if diPagina, let avviso = store.avviso {
                Fascia(salute: .attenzione, testo: avviso, dettaglio: nil, pulsantiSotto: pulsantiSotto) {
                    Button("Close") { store.avviso = nil }
                }
            }
            if diPagina, let notizia = store.notizia {
                FasciaNotizia(notizia: notizia)
            }
            if diSistema, let r = store.mentreEriVia.last {
                Fascia(salute: Segnale.run(r).salute, testo: Self.fraseMentreEriVia(r), dettaglio: r.frase, pulsantiSotto: pulsantiSotto) {
                    Button("See") {
                        store.sezione = .run
                        store.mentreEriVia = []
                    }
                    Button("Close") { store.mentreEriVia = [] }
                }
            }
        }

        .task(id: stato.lavori.map(chiavi)?.joined(separator: "|") ?? "") {
            guard !store.modoIstantanea, let lav = stato.lavori, lav.letto else { return }
            await Avvisi.lavori(lav.errori)
        }
    }

    private func chiavi(_ lav: Lavori) -> [String] { lav.errori.map(\.chiave_avviso) }
    private var nascoste: Set<String> { Set(nascosti.split(separator: "\n").map(String.init)) }


    static let fraseContratto =
        "The engine speaks a different version from this app. What you see may be incomplete. The app needs to be reinstalled."
    static let fraseVersioneNuova =
        "There's a new version of SBK. Runs in progress continue even during the update."
    static func fraseMentreEriVia(_ r: Run) -> String {
        "While you were away \(r.nome ?? "the run") \(Segnale.run(r).parola) \(Quando.frase(r.fine))."
    }




    struct Avviso {
        let salute: Salute
        let frase: String
        var corto: String? = nil
    }






    static func avvisi(_ stato: Stato, _ store: Store, nascoste: Set<String>) -> [Avviso] {
        var fuori: [Avviso] = []
        if let lav = stato.lavori, lav.letto, !lav.errori.isEmpty, !lav.frase.isEmpty,
           !lav.errori.map(\.chiave_avviso).allSatisfy(nascoste.contains) {


            let corto = lav.errori.count == 1 ? lav.errori.first?.avviso?.titolo : nil
            fuori.append(Avviso(salute: .errore, frase: lav.frase, corto: (corto ?? "").isEmpty ? nil : corto))
        }
        if let errore = store.errore { fuori.append(Avviso(salute: .attenzione, frase: errore)) }
        if (stato.contratto ?? 0) != contrattoAtteso { fuori.append(Avviso(salute: .attenzione, frase: fraseContratto)) }
        else if store.aggiornando { /* nella pagina */ }
        else if store.aggiornamentoDisponibile { fuori.append(Avviso(salute: .neutra, frase: fraseVersioneNuova)) }
        if let r = store.mentreEriVia.last { fuori.append(Avviso(salute: Segnale.run(r).salute, frase: fraseMentreEriVia(r))) }
        return fuori
    }
}




struct FasciaNotizia: View {
    let notizia: String
    @Environment(Store.self) private var store

    var body: some View {
        Fascia(salute: .ok, testo: notizia, dettaglio: nil) {



            if let t = store.notiziaTask, t.frase == notizia {
                Button(store.inspiration?.testi["apri_in_attivita"].flatMap { $0.isEmpty ? nil : $0 } ?? "Open in Activities") {
                    store.notizia = nil
                    Task { await store.apriTaskInAttivita(t.id) }
                }
            }
            Button("Close") { store.notizia = nil }
        }
        .task(id: notizia) {

            try? await Task.sleep(for: .seconds(10))
            if store.notizia == notizia { store.notizia = nil }
        }
    }
}

struct Fascia<Azioni: View>: View {
    let salute: Salute
    let testo: String
    let dettaglio: String?

    var pulsantiSotto = false
    @ViewBuilder let azioni: () -> Azioni
    @State private var mostraDettaglio = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.fratelli) {
            if pulsantiSotto {
                HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
                    Image(systemName: salute.simbolo).foregroundStyle(salute.colore)
                    Text(testo).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }
                HStack(spacing: Spazio.fratelli) {
                    Spacer(minLength: 0)
                    if dettaglio != nil {
                        Button(mostraDettaglio ? "Hide detail" : "Details") { mostraDettaglio.toggle() }
                    }
                    azioni()
                }
                .fixedSize(horizontal: false, vertical: true)
            } else {
                HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
                    Image(systemName: salute.simbolo).foregroundStyle(salute.colore)
                    Text(testo).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: Spazio.fratelli)
                    if dettaglio != nil {
                        Button(mostraDettaglio ? "Hide detail" : "Details") { mostraDettaglio.toggle() }
                    }
                    azioni()
                }
            }
            if mostraDettaglio, let dettaglio {
                Text(dettaglio)
                    .font(Testo.log)
                    .textSelection(.enabled)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .scheda(interno: 12, tinta: salute.colore)
    }
}



struct Caricamento: View {
    var body: some View {
        VStack(spacing: Spazio.interno) {
            ProgressView()
            Text("Reading the state of sources and steps…").foregroundStyle(.secondary)
        }
    }
}

struct CartellaMancante: View {
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: Spazio.interno) {
            TesseraIcona(simbolo: "folder.fill", colore: .blue, lato: 64)
            Text("Can't find SBK").font(.title2.weight(.bold))
            Text("SBK reads the state from the folder where you cloned the repo, which installa.py records when it installs the app. In \(store.radice) it isn't there today.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .frame(maxWidth: 420)
            Button("Choose the folder…") { store.scegliCartella() }
                .buttonStyle(.borderedProminent)
            Text("The sources and the pipeline appear as soon as the folder is the right one. Nothing is moved or deleted.")
                .font(Testo.secondario)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
        }
    }
}


struct IconaFonte: View {
    let fonte: Fonte
    var lato: CGFloat = 28

    var body: some View {
        TesseraIcona(simbolo: Self.simbolo(fonte), colore: Self.colore(fonte), lato: lato)
    }
}
