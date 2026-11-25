import AppKit
import SwiftUI


struct Panoramica: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Overview", sottotitolo: oggi) {
            if let r = stato.run_app, let av = store.runSeguito == r.run_id ? (store.avanzamento ?? r.avanzamento) : r.avanzamento {
                SchedaRunInCorso(titolo: "\(r.nome ?? "Run") in progress", av: av, inizio: r.inizio)
            } else if stato.da_fuori.attivo, let giro = stato.da_fuori.giro {
                SchedaRunInCorso(titolo: "Full run in progress, started from a terminal", av: giro,
                                 inizio: stato.ultimo_full_run?.inizio)
            }
            if stato.run_app == nil, let r = stato.ripresa {
                SchedaRipresa(ripresa: r)
            }
            SchedaLottiSospesi(lotti: stato.lotti_in_sospeso ?? [])
            if !store.scarichiVivi.isEmpty {
                VStack(spacing: 0) {
                    ForEach(Array(store.scarichiVivi.enumerated()), id: \.element.id) { i, s in
                        if i > 0 { Separatore().padding(.leading, 48) }
                        RigaScarico(scarico: s, compatta: true)
                    }
                }
                .scheda(interno: 0, tinta: Salute.inCorso.colore)
            }
            SchedaVerdetto(verdetto: stato.verdetto)


            if !stato.da_sistemare.isEmpty {
                SezioneDaSistemare(righe: stato.da_sistemare, altri: stato.altri_da_sistemare ?? 0)
            }
            Tessere(stato: stato)
            StrisciaFasi(stato: stato)
        }
    }

    private var oggi: String {
        Date().formatted(.dateTime.weekday(.wide).day().month(.wide).locale(Locale.current)).prima()
    }
}




struct SchedaRunInCorso: View {
    let titolo: String
    let av: Avanzamento
    let inizio: String?
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text(titolo).font(.headline)
                Spacer()
                Button {
                    store.sezione = .run
                } label: {
                    Label("Open the run", systemImage: "arrow.right.circle")
                }
                .buttonStyle(.bordered)
            }
            SchedaAvanzamento(av: av, inizio: inizio, compatta: true)
        }
        .scheda(interno: 16, tinta: Salute.inCorso.colore)
    }
}




struct SchedaVerdetto: View {
    let verdetto: Verdetto
    @Environment(Store.self) private var store

    var body: some View {
        let salute = Salute(motore: verdetto.livello)
        HStack(alignment: .top, spacing: 18) {
            ZStack {
                Circle().fill(salute.colore.gradient)
                if salute == .inCorso {
                    ProgressView().controlSize(.small).tint(.white)
                } else {
                    Image(systemName: simbolo(salute))
                        .font(.system(size: 22, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .frame(width: 52, height: 52)
            .help("The color says how much to trust the data right now. Green you can trust, orange needs a look, red means something must be fixed first.")
            .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(verdetto.titolo)
                    .font(.system(size: 22, weight: .bold))
                    .fixedSize(horizontal: false, vertical: true)
                if !verdetto.frase.isEmpty {
                    Text(verdetto.frase).font(.body).foregroundStyle(.secondary)
                }
                if verdetto.scaricate != nil || verdetto.nel_cervello != nil {

                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 10) { orologi }
                        VStack(alignment: .leading, spacing: 6) { orologi }
                    }
                    .padding(.top, 6)
                } else {
                    Text(verdetto.orologi).font(Testo.secondario).foregroundStyle(.secondary)
                }
            }
            .textSelection(.enabled)
            Spacer(minLength: Spazio.fratelli)
            if let azione = verdetto.azione, store.fermo(azione) == nil {
                Button(azione.etichetta) { store.esegui(azione, oggetto: verdetto.oggetto) }
                    .buttonStyle(.borderedProminent)
                    .tint(salute == .neutra ? .accentColor : salute.colore)
                    .controlSize(.large)
            }
        }
        .scheda(interno: 20, tinta: salute.colore)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder private var orologi: some View {
        Orologio(simbolo: "arrow.down.circle.fill", etichetta: "Sources downloaded", quando: verdetto.scaricate)
            .help("The last time new data arrived from a source. It enters the brain later, with the re-read.")
        Orologio(simbolo: "brain.head.profile", etichetta: "In the brain", quando: verdetto.nel_cervello)
            .help("The last time data entered the brain, with Re-read and update or with a full run.")
    }

    private func simbolo(_ salute: Salute) -> String {
        switch salute {
        case .ok: "checkmark"
        case .attenzione: "exclamationmark"
        case .errore: "xmark"
        case .inCorso: "arrow.triangle.2.circlepath"
        case .neutra: "minus"
        }
    }
}


struct Orologio: View {
    let simbolo: String
    let etichetta: String
    let quando: String?

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: simbolo).foregroundStyle(.secondary)
            Text(etichetta).foregroundStyle(.secondary)
            Text(Quando.frase(quando)).fontWeight(.semibold)
        }
        .font(.callout)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Superficie.incasso, in: Capsule())
        .accessibilityElement(children: .combine)
    }
}




struct Tessere: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {

        LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: 14)], spacing: 14) {
            Tessera(titolo: "Sources", valore: "\(fontiOk) of \(fontiVive.count)", nota: "updated",
                    aiuto: "The live sources that have fresh data, out of the total that download or that you bring. Click to see them one by one.") {
                store.sezione = .fonti
            } visual: {
                Anello(frazione: frazione(fontiOk, fontiVive.count), colore: colore(fontiVive.map(\.salute))) {
                    Image(systemName: "tray.and.arrow.down.fill").font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(colore(fontiVive.map(\.salute)))
                }
            }



            Tessera(titolo: "Pipeline", valore: "\(stadiChiusi) of \(stadiGratuiti.count)",
                    nota: notaPipeline,
                    aiuto: "The free steps that last time closed without errors. The gray circle means new data arrived afterward, and the line below says since when they haven't run. Click for the Pipeline.") {
                store.sezione = .pipeline
            } visual: {
                Anello(frazione: frazione(stadiChiusi, stadiGratuiti.count), colore: colorePipeline) {
                    Image(systemName: "point.3.filled.connected.trianglepath.dotted").font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(colorePipeline)
                }
            }
            Tessera(titolo: ultimoFull.vivo ? "Full run in progress" : (stato.ultimo_full_run?.titolo ?? "Last full run"),
                    valore: ultimoFull.valore,
                    nota: ultimoFull.nota,
                    aiuto: "The last full run, that is download and re-read, how it ended and how long it took. Click for the Run section.") {
                store.sezione = .run
            } visual: {
                if ultimoFull.vivo {
                    Anello(frazione: 0.75, colore: Salute.inCorso.colore) { ProgressView().controlSize(.small) }
                } else {

                    TesseraIcona(simbolo: "play.fill", colore: coloreUltimoFull, lato: 52)
                }
            }
            Tessera(titolo: "Expected spend", valore: spesa.valore, nota: spesa.nota,
                    aiuto: "What the paid steps would cost if you chose them all, from the last estimate. Nothing starts from here. Click for Spend and keys.") {
                store.sezione = .spesa
            } visual: {
                TesseraIcona(simbolo: "creditcard.fill", colore: .purple, lato: 52)
            }
            if let c = stato.copie {
                Tessera(titolo: "Backups", valore: copie(c).valore, nota: copie(c).nota,
                        aiuto: "The data backups and how the last one went. Click for the detail.") {
                    store.foglio = .copie
                } visual: {
                    TesseraIcona(simbolo: "externaldrive.fill",
                                 colore: c.salute == "ok" ? .blue : Salute(motore: c.salute).colore, lato: 52)
                }
            }
        }
    }

    private var fontiVive: [Fonte] { stato.fonti.filter { ["a_mano", "da_sole", "inventari"].contains($0.gruppo) } }

    private var fontiOk: Int { fontiVive.filter { ["ok", "in_corso"].contains($0.salute) }.count }
    private var stadiGratuiti: [Stadio] { stato.stadi.filter { !$0.pagato } }
    private var stadiChiusi: Int {
        stadiGratuiti.filter { ["fatto", "aspetta", "da_rileggere"].contains($0.stato ?? ($0.salute == "ok" ? "fatto" : "")) }.count
    }
    private var stadiInAttesa: Bool { stadiGratuiti.contains { ["aspetta", "da_rileggere"].contains($0.stato ?? "") } }
    private var notaPipeline: String {
        let fermi = stadiGratuiti.filter { ["aspetta", "da_rileggere"].contains($0.stato ?? "") }
        guard let da = fermi.compactMap(\.da_quanto).first(where: { !$0.isEmpty }) else { return "steps on track" }

        return fermi.count == stadiGratuiti.count ? "not running \(da)" : "\(fermi.count) not running \(da)"
    }
    private var colorePipeline: Color {
        let saluti = stadiGratuiti.map(\.salute)
        if saluti.contains("errore") || saluti.contains("attenzione") || saluti.contains("in_corso") { return colore(saluti) }
        return stadiInAttesa ? Color(nsColor: .systemGray) : Salute.ok.colore
    }

    private func frazione(_ a: Int, _ b: Int) -> Double { b > 0 ? Double(a) / Double(b) : 0 }


    private func colore(_ saluti: [String]) -> Color {
        if saluti.contains("errore") { return Salute.errore.colore }
        if saluti.contains("attenzione") { return Salute.attenzione.colore }
        if saluti.contains("in_corso") { return Salute.inCorso.colore }
        return Salute.ok.colore
    }

    private var ultimoFull: (valore: String, nota: String, vivo: Bool) {
        if let r = stato.run_app, r.comando?.contains("sb-full.py") == true || r.comando?.contains("--poi-ingest") == true {
            return ("for \(durataDa(r.inizio))", "started \(Quando.breve(r.inizio))", true)
        }
        guard let g = stato.ultimo_full_run, let inizio = g.inizio else { return ("never", "no full run found", false) }
        if g.vivo == true || (g.fine == nil && stato.da_fuori.attivo) {
            return ("for \(durataDa(inizio))", "started \(Quando.breve(inizio))", true)
        }

        if let nota = g.nota { return (Quando.breve(inizio), nota, false) }
        if let fine = g.fine, let a = Quando.data(inizio), let b = Quando.data(fine) {
            let chiusi = (g.non_chiusi ?? "nessuno") == "nessuno" ? "finished" : "with unclosed steps"
            return (Quando.breve(inizio), "\(chiusi), \(Quando.durata(b.timeIntervalSince(a)))", false)
        }
        return (Quando.breve(inizio), "without the end line", false)
    }

    private var coloreUltimoFull: Color {
        let salute = Salute(motore: stato.ultimo_full_run?.salute ?? "neutra")
        return salute == .neutra ? Color(nsColor: .systemGray) : salute.colore
    }

    private func durataDa(_ ts: String) -> String {
        guard let d = Quando.data(ts) else { return "" }
        return Quando.durata(Date().timeIntervalSince(d))
    }


    private func copie(_ c: Copie) -> (valore: String, nota: String) {
        let l1 = c.livelli.filter { ["l1", "completo"].contains($0.tipo) }.max(by: { $0.quando < $1.quando })
        let valore = l1.map { "L1 \(Quando.breve($0.quando))" } ?? "none"

        if c.giro_settimanale.esito.map({ $0 != 0 }) == true {
            return (valore, c.giro_settimanale.frase.contains("spazio") ? "out of space" : "not on Sunday")
        }
        return (valore, "all on this Mac")
    }

    private var spesa: (valore: String, nota: String) {
        let pagati = stato.stadi.filter(\.pagato)
        let fermo = pagati.compactMap(\.ultimo.quando).min().map { "stopped since \(Quando.breve($0))" } ?? "never done"
        guard let s = store.stima, let totale = s.totale else {
            return ("to be calculated", fermo)
        }
        return ("about \(Int(totale.rounded()).formatted(.number.locale(Locale.current))) $",
                "\(pagati.count) steps, estimate \(Quando.breve(s.quando))")
    }
}

struct Tessera<Visual: View>: View {
    let titolo: String
    let valore: String
    let nota: String

    var aiuto: String = ""
    let azione: () -> Void
    @ViewBuilder var visual: () -> Visual
    @State private var sopra = false

    var body: some View {
        Button(action: azione) {
            HStack(spacing: 14) {
                visual()
                VStack(alignment: .leading, spacing: 1) {
                    Text(titolo).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                    Cifra(testo: valore, dimensione: 21)
                    Text(nota).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .opacity(sopra ? 1 : 0)
            }
            .scheda(interno: 14)
            .contentShape(RoundedRectangle(cornerRadius: Raggio.scheda))
        }
        .buttonStyle(.plain)
        .help(aiuto.isEmpty ? "Opens the \(titolo) section" : aiuto)
        .onHover { sopra = $0 }
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the \(titolo) section")
    }
}




struct StrisciaFasi: View {
    let stato: Stato
    @Environment(Store.self) private var store
    private let lato: CGFloat = 46

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "The chain", conteggio: "\(stato.stadi.count) steps in \(stato.fasi.count) phases") {
                Button("Open the pipeline") { store.sezione = .pipeline }
                    .buttonStyle(.link)
            }
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(stato.fasi.enumerated()), id: \.element.id) { i, fase in
                    NodoFase(fase: fase, numero: i + 1, stato: stato, lato: lato)
                        .frame(minWidth: 0, maxWidth: .infinity)
                }
            }
            .background(alignment: .top) {
                GeometryReader { g in
                    let passo = g.size.width / CGFloat(max(1, stato.fasi.count))
                    Path { p in
                        p.move(to: CGPoint(x: passo / 2, y: lato / 2))
                        p.addLine(to: CGPoint(x: g.size.width - passo / 2, y: lato / 2))
                    }
                    .stroke(Superficie.traccia, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                }
            }
            .scheda(interno: 18)
        }
    }
}

struct NodoFase: View {
    let fase: Fase
    let numero: Int
    let stato: Stato
    let lato: CGFloat
    @Environment(Store.self) private var store
    @State private var sopra = false

    var body: some View {
        let colore = Self.colore(fase)
        Button {
            store.fasiChiuse.remove(fase.id)
            store.selezione = .fase(fase.id)
            store.sezione = .pipeline
        } label: {
            VStack(spacing: 6) {
                Anello(frazione: Self.frazione(fase, stato: stato), colore: colore, lato: lato, spessore: 5) {
                    if fase.salute == "in_corso" {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: IconaFase.simbolo(fase.id))
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(colore)
                    }
                }
                .background(Circle().fill(Superficie.scheda))
                .scaleEffect(sopra ? 1.06 : 1)

                Text(fase.nome)
                    .font(.callout.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(fase.nome.contains(" ") ? 2 : 1)
                    .minimumScaleFactor(0.7)


                if ["da_rileggere", "aspetta", "errore", "incompleto"].contains(fase.stato ?? "") {
                    Label(fase.frase, systemImage: Segnale.fase(fase).simbolo)
                        .labelStyle(.titleAndIcon)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                } else {
                    Text(fase.data)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.smooth(duration: 0.15)) { sopra = h } }
        .help("\(numero). \(fase.nome), \(Segnale.fase(fase).parola). \(fase.descrizione)")
        .accessibilityLabel("Phase \(numero), \(fase.nome), \(Segnale.fase(fase).parola), \(fase.data)")
    }


    static func frazione(_ fase: Fase, stato: Stato) -> Double {
        if fase.id == "scarico" {
            let vive = stato.fonti.filter { ["a_mano", "da_sole", "inventari"].contains($0.gruppo) }
            let ok = vive.filter { ["ok", "in_corso"].contains($0.salute) }.count
            return vive.isEmpty ? 0 : Double(ok) / Double(vive.count)
        }
        let membri = stato.stadi.filter { fase.stadi.contains($0.id) }


        let chiusi = membri.filter { ["fatto", "aspetta", "da_rileggere"].contains($0.stato ?? ($0.salute == "ok" ? "fatto" : "")) }
        return membri.isEmpty ? 0 : Double(chiusi.count) / Double(membri.count)
    }


    static func colore(_ fase: Fase) -> Color {
        if fase.pagata && fase.salute != "in_corso" && fase.salute != "errore" { return .purple }
        let salute = Salute(motore: fase.salute)
        return salute == .neutra ? Color(nsColor: .systemGray) : salute.colore
    }
}



struct SezioneDaSistemare: View {
    let righe: [RigaDaSistemare]
    let altri: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "To fix", conteggio: "\(righe.count + altri)")
            VStack(spacing: 0) {
                ForEach(Array(righe.enumerated()), id: \.element.id) { i, riga in
                    if i > 0 { Separatore().padding(.leading, 62) }
                    RigaSistemare(riga: riga)
                }
                if altri > 0 {
                    Separatore().padding(.leading, 62)
                    Text(altri == 1 ? "And one more thing, you'll see it in the pipeline." : "And \(altri) more things, you'll see them in the pipeline.")
                        .font(Testo.secondario).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 10).padding(.leading, 62)
                }
            }
            .scheda(interno: 0)
        }
    }
}

struct RigaSistemare: View {
    let riga: RigaDaSistemare
    @Environment(Store.self) private var store
    @State private var sopra = false

    var body: some View {
        HStack(spacing: 14) {
            icona
            VStack(alignment: .leading, spacing: 2) {
                Text(riga.titolo).font(.headline)
                if !riga.frase.isEmpty {
                    Text(riga.frase).font(Testo.secondario).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: Spazio.fratelli)
            if let azione = riga.azione, store.fermo(azione) == nil {
                Button(azione.etichetta) { store.esegui(azione, oggetto: riga.oggetto) }
                    .buttonStyle(.bordered)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(sopra ? Superficie.incasso : .clear)
        .contentShape(Rectangle())
        .onTapGesture { store.scegli(riga.oggetto) }
        .onHover { sopra = $0 }
        .accessibilityAddTraits(.isButton)
        .accessibilityAction(named: "Show the detail") { store.scegli(riga.oggetto) }
    }

    @ViewBuilder private var icona: some View {
        if riga.oggetto.tipo == "fonte", let f = store.stato?.fonti.first(where: { $0.id == riga.oggetto.id }) {
            IconaFonte(fonte: f, lato: 32)
        } else if riga.oggetto.tipo == "gruppo" || riga.livello == "neutra" && riga.oggetto.tipo != "fase" {
            TesseraIcona(simbolo: "hand.point.up.left.fill", colore: .teal, lato: 32)
        } else if riga.oggetto.tipo == "fase" && riga.oggetto.id == "estrazione" {
            TesseraIcona(simbolo: "creditcard.fill", colore: .purple, lato: 32)
        } else if riga.oggetto.tipo == "strumenti" && riga.oggetto.id == "disco" {
            TesseraIcona(simbolo: "internaldrive.fill", colore: Salute(motore: riga.livello).colore, lato: 32)
        } else if riga.oggetto.tipo == "copie" {
            TesseraIcona(simbolo: "externaldrive.fill", colore: Salute(motore: riga.livello).colore, lato: 32)
        } else if riga.oggetto.tipo == "run" {
            TesseraIcona(simbolo: "play.fill", colore: Salute(motore: riga.livello).colore, lato: 32)
        } else {
            let salute = Salute(motore: riga.livello)
            TesseraIcona(simbolo: salute == .errore ? "xmark" : "exclamationmark.triangle.fill",
                         colore: salute == .neutra ? Color(nsColor: .systemGray) : salute.colore, lato: 32)
        }
    }
}
