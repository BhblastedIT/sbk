import AppKit
import SwiftUI



struct PaginaRun: View {
    let stato: Stato
    @Environment(Store.self) private var store

    private enum Mostrato {
        case app(Run)
        case daFuori(DaFuori)
        case vuoto
    }

    private var mostrato: Mostrato {
        if let id = store.runScelto, let r = stato.runs.first(where: { $0.run_id == id }) { return .app(r) }
        if let r = stato.run_app { return .app(r) }
        if stato.da_fuori.attivo { return .daFuori(stato.da_fuori) }
        if let r = stato.runs.last { return .app(r) }
        return .vuoto
    }

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Run", sottotitolo: sottotitolo) {
            if stato.run_app == nil, let r = stato.ripresa {
                SchedaRipresa(ripresa: r)
            }
            if let id = store.runScelto, stato.runs.contains(where: { $0.run_id == id }) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.circlepath").foregroundStyle(.secondary)
                    Text("You are viewing a past run.").foregroundStyle(.secondary)
                    Spacer()
                    Button(stato.run_app != nil || stato.da_fuori.attivo ? "Back to the current run" : "Back to the last run") {
                        store.runScelto = nil
                    }
                    .buttonStyle(.borderedProminent)
                }
                .scheda(interno: 12)
            }
            switch mostrato {
            case .app(let r):
                let av = store.runSeguito == r.run_id
                    ? (store.avanzamento ?? r.avanzamento) : (r.avanzamento ?? store.passiFiniti[r.run_id])
                SchedaRun(run: r, avanzamento: av)
                if r.vivo, let c = stato.codice_cambiato { AvvisoCodiceCambiato(cambi: c) }
                if r.vivo, let av {
                    CruscottoRun(av: av, inizio: r.inizio)
                }
                HStack(alignment: .top, spacing: 14) {
                    RiquadroPassi(avanzamento: av, run: r)
                        .frame(minWidth: 240, idealWidth: 330, maxWidth: 330)
                    RiquadroRegistro(run: r)
                }
                .frame(height: 400)
                .task(id: r.run_id) {
                    if !r.vivo { await store.caricaPassi(r.run_id) }
                }
            case .daFuori(let df):
                SchedaDaFuori(daFuori: df, stato: stato)
                if let c = stato.codice_cambiato { AvvisoCodiceCambiato(cambi: c) }
                if let giro = df.giro {
                    CruscottoRun(av: giro, inizio: stato.ultimo_full_run?.inizio)
                }
                HStack(alignment: .top, spacing: 14) {
                    RiquadroPassi(avanzamento: df.giro, run: nil)
                        .frame(minWidth: 240, idealWidth: 330, maxWidth: 330)
                    if let percorso = registroDaFuori {
                        RiquadroRegistroDaFuori(percorso: percorso, cartella: stato.ultimo_full_run?.cartella)
                    } else {
                        VStack(spacing: Spazio.fratelli) {
                            Image(systemName: Simbolo.terminale).font(.system(size: 26)).foregroundStyle(.secondary)
                            Text("This run started from a terminal").font(.headline)
                            Text("The app shows its steps from the download diary, but doesn't control it. It stops from where it started.")
                                .multilineTextAlignment(.center)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: 360)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .scheda()
                    }
                }
                .frame(height: 400)
            case .vuoto:
                VStack(spacing: Spazio.fratelli) {
                    TesseraIcona(simbolo: "play.fill", colore: .blue, lato: 44)
                    Text("No run yet").font(.headline)
                    Text("The first starts from Full run free or Full run completa, top right.").foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 30)
                .scheda()
            }
            ScarichiDaSoli(scarichi: stato.scarichi_soli ?? [])
            RunRecenti(runs: stato.runs)
            SezioneComandiRun()
        }
    }


    private var registroDaFuori: String? {
        guard let g = stato.ultimo_full_run, let passo = g.passo_in_corso else { return nil }
        let percorso = g.cartella + "/log/\(passo).log"
        return FileManager.default.fileExists(atPath: percorso) ? percorso : nil
    }

    private var sottotitolo: String {
        switch mostrato {
        case .app(let r): r.vivo ? "In progress" : "Nothing in progress, the app's last run"
        case .daFuori: "In progress, started from a terminal"
        case .vuoto: "Nothing in progress"
        }
    }
}



struct SchedaRun: View {
    let run: Run
    let avanzamento: Avanzamento?
    @Environment(Store.self) private var store

    var body: some View {
        let comandi = store.comandiRun ?? run.comandi
        let inPausa = run.vivo && comandi?.continua.possibile == true
        let segnale = inPausa ? Segnale(salute: .attenzione, simbolo: "pause.fill", parola: "paused") : Segnale.run(run)
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 14) {
                TesseraIcona(simbolo: spende ? Simbolo.completa : Simbolo.fullRun, colore: spende ? .purple : .blue, lato: 44)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Text(run.nome ?? "Run").font(.title3.weight(.bold))
                        Pillola(segnale: segnale)
                    }
                    Text(sottotitolo).font(.callout).foregroundStyle(.secondary)
                }
                Spacer(minLength: Spazio.fratelli)
                Button {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: run.log)])
                } label: {
                    Image(systemName: Simbolo.mostraNelFinder)
                }
                .buttonStyle(.bordered)
                .help("Show the log in Finder")
                .accessibilityLabel("Show the log in Finder")
                Button {
                    Resoconto.copia(run: run, stato: store.stato)
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .buttonStyle(.bordered)
                .help("Copy the run report, to paste where needed")
                .accessibilityLabel("Copy the run report")
                if run.vivo {
                    PulsantePausa(run: run)
                    Button(role: .destructive) {
                        store.foglio = .ferma(run)
                    } label: {
                        Label(store.fermoRichiesto.contains(run.run_id) ? "Stopping" : "Stop", systemImage: Simbolo.ferma)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .disabled(store.fermoRichiesto.contains(run.run_id))
                }
            }

            if run.vivo, (comandi?.frase ?? "").isEmpty, let riga = store.rigaRun ?? run.riga, !riga.isEmpty {
                Text(riga).font(.callout).foregroundStyle(.secondary)
            }
            if run.vivo {
                RigaPausa(run: run)
            }
            if let spesa = run.spesa, !spesa.isEmpty {
                Label(rigaSpesa(spesa), systemImage: "creditcard.fill")
                    .font(Testo.secondario)
                    .foregroundStyle(.secondary)
            }
            if !run.vivo, let frase = esitoInParole {
                HStack(spacing: Spazio.fratelli) {
                    Image(systemName: segnale.simbolo).foregroundStyle(segnale.salute.colore)
                        .help(segnale.aiuto ?? segnale.parola)
                    Text(frase).fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    if let rimasti = run.rimasti, !rimasti.isEmpty {
                        Text("This run still has \(rimasti.count) processes running.").foregroundStyle(.secondary)
                        Button("Close them") { Task { await store.pulisci(run) } }
                    }
                }
                .font(Testo.secondario)
                .padding(10)
                .background(segnale.salute.colore.opacity(0.10), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
        }
        .scheda(interno: 18, tinta: run.vivo ? Salute.inCorso.colore : nil)
    }

    private var spende: Bool { !(run.spesa ?? []).isEmpty || run.comando?.contains("--consenti-spesa") == true }

    private func rigaSpesa(_ spesa: [String]) -> String {
        let nomi = spesa.map { id in store.stato?.stadi.first(where: { $0.id == id })?.nome ?? id }
        let chiave = run.chiave.map { ", pays the key «\($0)»" } ?? ""
        return "With the spend for \(nomi.joined(separator: ", "))\(chiave)."
    }

    private var sottotitolo: String {
        var pezzi = ["started \(Quando.frase(run.inizio))"]
        if run.vivo, let inizio = Quando.data(run.inizio) {
            pezzi.append("for \(Quando.durata(Date().timeIntervalSince(inizio)))")
        } else if let fine = run.fine, let a = Quando.data(run.inizio), let b = Quando.data(fine) {
            pezzi.append("lasted \(Quando.durata(b.timeIntervalSince(a)))")
        }
        return pezzi.joined(separator: " · ")
    }

    private var esitoInParole: String? {
        guard let esito = run.esito else { return nil }
        let quando = Quando.frase(run.fine)


        if let racconto = run.racconto, !racconto.isEmpty {
            switch esito {
            case "ok", "incompleto": return "Finished \(quando). \(racconto)"
            case "fermato": return "Stopped \(quando). \(racconto)"
            default: return racconto
            }
        }

        if let parola = Vocabolario.parola("run", esito) {
            let perche = (esito == "interrotto" ? (run.motivo ?? run.frase) : run.frase)?.prima()
            let coda = perche.map { $0.hasSuffix(".") ? " \($0)" : " \($0)." } ?? ""
            return "\(parola.prima()) \(quando).\(coda)"
        }
        switch esito {
        case "ok": return "Finished \(quando)." + (run.frase.map { " \($0.prima())." } ?? "")
        case "incompleto": return "Finished \(quando), incomplete. \(run.frase?.prima() ?? "")"
        case "fallito": return "Not finished. \(run.frase?.prima() ?? "")"
        case "fermato": return "Stopped by you \(quando)."
        case "interrotto": return "Interrupted. \(run.motivo?.prima() ?? run.frase?.prima() ?? "")"
        case "non_partito": return "It didn't start. \(run.frase?.prima() ?? "")"
        default: return nil
        }
    }
}


struct BarraDelRun: View {
    let avanzamento: Avanzamento
    let riga: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            barra(avanzamento, etichetta: avanzamento.tipo == "giro" ? "full run steps" : "step")
            if let dentro = avanzamento.dentro?.first {
                barra(dentro, etichetta: "re-read steps")
            }
            if let riga, !riga.isEmpty {
                Text(riga).font(.callout).foregroundStyle(.secondary)
            }
        }
    }

    private func barra(_ av: Avanzamento, etichetta: String) -> some View {
        let fatti = av.passi.filter { ["fatto", "fallito", "saltato"].contains($0.stato) }.count
        let totale = max(1, av.passi.count)
        return VStack(alignment: .leading, spacing: 4) {
            ProgressView(value: Double(fatti), total: Double(totale))
                .progressViewStyle(.linear)
                .tint(Salute.inCorso.colore)
            HStack {
                Text("\(fatti) of \(av.passi.count) \(etichetta)").monospacedDigit()
                Spacer()
                if let c = av.corrente {
                    Text("now \(c.nome)").lineLimit(1)
                }
            }
            .font(Testo.secondario)
            .foregroundStyle(.secondary)
        }
    }
}


struct CruscottoRun: View {
    let av: Avanzamento
    let inizio: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SchedaAvanzamento(av: av, inizio: inizio)
            if av.tipo == "giro" {
                PercorsoRun(av: av)
            }
        }
        .scheda(interno: 20)
        SchedaCorsie(av: av)
    }
}


struct SchedaDaFuori: View {
    let daFuori: DaFuori
    let stato: Stato

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                TesseraIcona(simbolo: Simbolo.terminale, colore: Color(nsColor: .darkGray), lato: 44)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Text(stato.ultimo_full_run?.inizio != nil ? "Full run from a terminal" : "Run from a terminal")
                            .font(.title3.weight(.bold))
                        Pillola(segnale: Segnale(salute: .inCorso, parola: "in progress"))
                    }
                    Text(daFuori.frase).font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
        .scheda(interno: 18, tinta: Salute.inCorso.colore)
    }
}




struct RiquadroRegistroDaFuori: View {
    let percorso: String
    let cartella: String?
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Log of the current step").font(.headline)
                Spacer()
                if let cartella {
                    Button("Diary in Finder") {
                        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: cartella + "/esiti.tsv")])
                    }
                    .buttonStyle(.link)
                    .font(Testo.secondario)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            Separatore()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(store.righeLog) { r in RigaLog(testo: r.testo).id(r.id) }
                }
                .padding(10)
                .textSelection(.enabled)
            }
            .defaultScrollAnchor(.bottom)
            .background(Superficie.incasso)
        }
        .frame(maxHeight: .infinity)
        .scheda(interno: 0)
        .clipShape(RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous))
        .onAppear { if store.percorsoLog != percorso { store.apriLog(percorso: percorso) } }
        .onChange(of: percorso) { _, nuovo in store.apriLog(percorso: nuovo) }
    }
}

struct RiquadroPassi: View {
    let avanzamento: Avanzamento?
    let run: Run?

    var body: some View {
        ElencoPassi(avanzamento: avanzamento, run: run)
            .frame(maxHeight: .infinity)
            .scheda(interno: 0)
    }
}

struct RiquadroRegistro: View {
    let run: Run
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Log").font(.headline)
                Spacer()
                Toggle("Follow", isOn: Bindable(store).seguiRegistro)
                    .toggleStyle(.switch)
                    .controlSize(.mini)
                    .font(Testo.secondario)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            Separatore()
            RegistroRun(run: run)
                .background(Superficie.incasso)
        }
        .frame(maxHeight: .infinity)
        .scheda(interno: 0)
        .clipShape(RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous))
    }
}

struct ElencoPassi: View {
    let avanzamento: Avanzamento?
    let run: Run?
    @Environment(Store.self) private var store

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let av = avanzamento {
                    intestazione(av.tipo == "giro" ? "Source download" : "Step", av.denominatore)
                    ForEach(av.passi) { p in riga(p, av: av) }
                    daSapere(av.diagnosi_run)
                    if let dentro = av.dentro?.first {
                        intestazione("Re-read", dentro.denominatore).padding(.top, 8)
                        ForEach(dentro.passi) { p in riga(p, av: dentro) }
                        daSapere(dentro.diagnosi_run)
                    }
                    if let eventi = av.eventi, !eventi.isEmpty {
                        intestazione("Events", "").padding(.top, 8)
                        ForEach(eventi, id: \.self) { e in
                            Text(e).font(Testo.secondario).foregroundStyle(.secondary)
                                .padding(.horizontal, 14).padding(.vertical, 2)
                        }
                    }
                } else {

                    Text(run?.vivo == false ? "This run didn't write its steps." : "The steps arrive in a few seconds.")
                        .font(Testo.secondario).foregroundStyle(.secondary)
                        .padding(14)
                }
            }
            .padding(.vertical, 6)
        }
    }


    @ViewBuilder private func daSapere(_ voci: [DiagnosiStadio]?) -> some View {
        if let voci, !voci.isEmpty {
            intestazione("To know about this run", "").padding(.top, 8)
            DiagnosiPasso(diagnosi: nil, avvisi: voci.map(\.diagnosi).filter { $0.gravita != "errore" })
                .padding(.leading, -26)
            ForEach(voci.filter { $0.diagnosi.gravita == "errore" }, id: \.diagnosi.id) { v in
                DiagnosiPasso(diagnosi: v.diagnosi, avvisi: []).padding(.leading, -26)
            }
        }
    }

    private func intestazione(_ titolo: String, _ conto: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(titolo).font(.headline)
            Spacer()
            Text(conto).font(Testo.secondario).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
    }

    @ViewBuilder private func riga(_ p: PassoRun, av: Avanzamento) -> some View {
        let corrente = av.corrente?.id == p.id && p.stato == "in_corso"
        Button {
            if let run, av.tipo == "giro" {
                store.apriLog(percorso: store.registroDi(run, passo: p.id))
            }
        } label: {
            HStack(spacing: Spazio.fratelli) {
                SegnaleView(segnale: .passo(p.stato), compatto: true)
                Text(nome(p)).lineLimit(1)
                Spacer()
                Text(dettaglio(p, corrente: corrente, av: av))
                    .font(Testo.secondario.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 4)
            .background {
                if corrente {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(Salute.inCorso.colore.opacity(0.12))
                        .padding(.horizontal, 6)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        if corrente, let frase = av.corrente?.come_va, !frase.isEmpty {

            Text(frase)
                .font(Testo.secondario)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 40)
                .padding(.trailing, 14)
                .padding(.bottom, 4)
        }
        if p.diagnosi != nil || !(p.avvisi ?? []).isEmpty {
            DiagnosiPasso(diagnosi: p.diagnosi, avvisi: p.avvisi ?? [])
        }
    }


    private func nome(_ p: PassoRun) -> String {
        store.stato?.stadi.first(where: { $0.id == p.id })?.nome ?? p.nome
    }

    private func dettaglio(_ p: PassoRun, corrente: Bool, av: Avanzamento) -> String {
        if corrente, let c = av.corrente {

            var pezzi: [String] = []
            if let d = Quando.data(c.partito) {
                pezzi.append("for \(Quando.durata(Date().timeIntervalSince(d)))")
            } else if let da = c.da_s {
                pezzi.append("for \(Quando.durata(da))")
            }
            if let segno = c.ultimo_segno_s, segno > 15 * 60 {

                pezzi.append(c.al_lavoro != nil ? "working" : "idle for \(Quando.durata(Double(segno)))")
            }
            return pezzi.isEmpty ? "now" : pezzi.joined(separator: " · ")
        }
        if p.ripreso == true { return "closed in the previous run" }
        var pezzi: [String] = []
        if let d = p.durata_s, d > 0 { pezzi.append(Quando.durata(d)) }
        if let t = p.tentativi, t > 1 { pezzi.append("attempt \(t)") }
        if p.stato == "fallito" { pezzi.append("not closed") }
        if p.stato == "saltato" { pezzi.append("out") }
        return pezzi.joined(separator: " · ")
    }
}

struct RegistroRun: View {
    let run: Run
    @Environment(Store.self) private var store

    var body: some View {
        ScrollViewReader { lettore in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(store.righeLog) { r in
                        RigaLog(testo: r.testo).id(r.id)
                    }
                }
                .padding(10)
                .textSelection(.enabled)
            }
            .defaultScrollAnchor(.bottom)
            .onChange(of: store.righeLog.last?.id) { _, ultimo in
                guard store.seguiRegistro, let ultimo else { return }
                lettore.scrollTo(ultimo, anchor: .bottom)
            }
        }
        .overlay {
            if store.righeLog.isEmpty {
                Text(Quando.data(run.inizio) == nil ? "" : "This run's log is still empty.")
                    .foregroundStyle(.secondary)
            }
        }
        .onAppear {
            if store.percorsoLog == nil || (store.runSeguito != run.run_id && store.percorsoLog != run.log) {
                store.apriLog(percorso: run.log)
            }
        }
        .onChange(of: run.run_id) { _, _ in store.apriLog(percorso: run.log) }
    }
}




struct ScarichiDaSoli: View {
    let scarichi: [Run]

    var body: some View {
        let vivi = scarichi.filter(\.vivo)
        let mostrati = vivi + scarichi.filter { !$0.vivo }.suffix(5).reversed()
        if !mostrati.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "Sources downloaded on their own", conteggio: vivi.isEmpty ? "\(mostrati.count)" : "\(vivi.count) in progress") {
                    Text("Light sources download even while a full run is running.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                VStack(spacing: 0) {
                    ForEach(Array(mostrati.enumerated()), id: \.element.id) { i, s in
                        if i > 0 { Separatore().padding(.leading, 48) }
                        RigaScarico(scarico: s)
                    }
                }
                .scheda(interno: 0)
            }
        }
    }
}


struct RigaScarico: View {
    let scarico: Run
    var compatta = false
    @Environment(Store.self) private var store
    @State private var aperto = false
    @State private var righe: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                if let f = fonte {
                    IconaFonte(fonte: f, lato: 26)
                } else {
                    SegnaleView(segnale: .run(scarico), compatto: true).frame(width: 22)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(scarico.nome ?? "Download").font(.headline)
                    Text(dettaglio).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(2)
                }
                Spacer(minLength: Spazio.fratelli)
                if scarico.vivo {
                    ProgressView().controlSize(.small)
                    Button {
                        Task { await store.fermaScarico(scarico) }
                    } label: {
                        Label(store.fermoRichiesto.contains(scarico.run_id) ? "Stopping" : "Stop", systemImage: Simbolo.ferma)
                    }
                    .buttonStyle(.bordered)
                    .tint(.red)
                    .disabled(store.fermoRichiesto.contains(scarico.run_id))
                } else if !compatta {
                    Text(Quando.frase(scarico.inizio))
                        .font(Testo.secondario.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                Button {
                    aperto.toggle()
                } label: {
                    Image(systemName: aperto ? "chevron.up" : "chevron.down")
                }
                .buttonStyle(.borderless)
                .help(aperto ? "Close the log" : "Open the log")
                .accessibilityLabel(aperto ? "Close the log" : "Open the log")
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            if aperto {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(righe.enumerated()), id: \.offset) { _, r in RigaLog(testo: r) }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                }
                .defaultScrollAnchor(.bottom)
                .frame(height: 180)
                .background(Superficie.incasso)
                .overlay { if righe.isEmpty { Text("The log is still empty.").foregroundStyle(.secondary) } }
            }
        }
        .contentShape(Rectangle())
        .task(id: aperto ? "\(scarico.run_id)-\(scarico.vivo)-\(store.stato?.generato ?? "")" : "") {
            if aperto { righe = await store.righeScarico(scarico) }
        }
        .contextMenu {
            Button("Show the log in Finder") {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: scarico.log)])
            }
        }
    }

    private var fonte: Fonte? { store.stato?.fonti.first { $0.id == scarico.sorgente } }

    private var dettaglio: String {
        var pezzi = [Segnale.run(scarico).parola]
        if let frase = scarico.frase, !frase.isEmpty, !scarico.vivo, scarico.esito != "ok" { pezzi.append(frase) }
        if scarico.vivo, let a = Quando.data(scarico.inizio) {
            pezzi.append("for \(Quando.durata(Date().timeIntervalSince(a)))")
        } else if let fine = scarico.fine, let a = Quando.data(scarico.inizio), let b = Quando.data(fine) {
            pezzi.append("lasted \(Quando.durata(b.timeIntervalSince(a)))")
        }
        return pezzi.joined(separator: " · ")
    }
}



struct RunRecenti: View {
    let runs: [Run]

    var body: some View {
        if !runs.isEmpty {
            let recenti = Array(runs.suffix(8).reversed())
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "Recent runs", conteggio: "\(recenti.count)")
                VStack(spacing: 0) {
                    ForEach(Array(recenti.enumerated()), id: \.element.id) { i, r in
                        if i > 0 { Separatore().padding(.leading, 48) }
                        RigaRun(run: r)
                    }
                }
                .scheda(interno: 0)
            }
        }
    }
}

struct RigaRun: View {
    let run: Run
    @Environment(Store.self) private var store
    @State private var sopra = false

    var body: some View {
        Button {
            store.runScelto = run.vivo ? nil : run.run_id
        } label: {
            riga
        }
        .buttonStyle(.plain)
        .onHover { sopra = $0 }
        .background(store.runScelto == run.run_id ? Superficie.selezione : (sopra ? Superficie.incasso : .clear))
        .help("Show the steps and log of this run")
    }

    private var riga: some View {
        HStack(spacing: 12) {
            SegnaleView(segnale: .run(run), compatto: true)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 1) {
                Text(run.nome ?? "Run").font(.headline)
                Text(dettaglio).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: Spazio.fratelli)
            Text(Quando.frase(run.inizio))
                .font(Testo.secondario.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .contentShape(Rectangle())
        .contextMenu {
            Button("Show the log in Finder") {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: run.log)])
            }
            Button("Copy the report") { Resoconto.copia(run: run, stato: store.stato) }
        }
    }

    private var dettaglio: String {
        var pezzi = [Segnale.run(run).parola]
        if let fine = run.fine, let a = Quando.data(run.inizio), let b = Quando.data(fine) {
            pezzi.append("lasted \(Quando.durata(b.timeIntervalSince(a)))")
        }
        if let spesa = run.spesa, !spesa.isEmpty {
            pezzi.append("\(spesa.count) paid steps" + (run.chiave.map { ", key «\($0)»" } ?? ""))
        }
        return pezzi.joined(separator: " · ")
    }
}



@MainActor
enum Resoconto {
    static func testo(run: Run, stato: Stato?) -> String {
        var righe = ["\(run.nome ?? "Run") · \(Segnale.run(run).parola)"]
        var tempo = "started \(Quando.frase(run.inizio))"
        if let fine = run.fine, let a = Quando.data(run.inizio), let b = Quando.data(fine) {
            tempo += ", lasted \(Quando.durata(b.timeIntervalSince(a)))"
        }
        righe.append(tempo)
        if let frase = run.frase, !frase.isEmpty { righe.append(frase.prima()) }
        if let av = run.avanzamento {
            let chiusi = av.passi.filter { $0.stato == "fatto" }.count
            righe.append("Steps: \(chiusi) done of \(av.passi.count)")
            let problemi = av.passi.filter { ["fallito", "interrotto", "ritento"].contains($0.stato) }
            if !problemi.isEmpty {
                righe.append("Not closed: " + problemi.map { "\($0.nome) (\(Segnale.passo($0.stato).parola))" }.joined(separator: ", "))
            }
        }
        if let spesa = run.spesa, !spesa.isEmpty {
            let nomi = spesa.map { id in stato?.stadi.first { $0.id == id }?.nome ?? id }
            righe.append("Paid steps: \(nomi.joined(separator: ", "))" + (run.chiave.map { ", key «\($0)»" } ?? ""))
        }
        righe.append("Log: \(run.log)")
        if let c = run.cartella { righe.append("Run folder: \(c)") }
        return righe.joined(separator: "\n")
    }

    static func copia(run: Run, stato: Stato?) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(testo(run: run, stato: stato), forType: .string)
    }
}



struct AvvisoCodiceCambiato: View {
    let cambi: CodiceCambiato
    @State private var aperto = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
                Image(systemName: "chevron.left.forwardslash.chevron.right").foregroundStyle(Salute.attenzione.colore)
                Text(frase).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: Spazio.fratelli)
                Button(aperto ? "Hide" : "What changed") { aperto.toggle() }
            }
            if aperto {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(cambi.commit, id: \.hash) { c in
                        Text("\(c.quando.map { Quando.ora($0) } ?? "")  \(c.messaggio)")
                    }
                    ForEach(cambi.file, id: \.file) { f in
                        Text("\(Quando.breve(f.quando))  \(f.file), not saved")
                    }
                }
                .font(Testo.log)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .scheda(interno: 12, tinta: Salute.attenzione.colore)
    }

    private var frase: String {
        var pezzi: [String] = []
        if !cambi.commit.isEmpty { pezzi.append(cambi.commit.count == 1 ? "one saved change" : "\(cambi.commit.count) saved changes") }
        if !cambi.file.isEmpty { pezzi.append(cambi.file.count == 1 ? "one changed and unsaved file" : "\(cambi.file.count) changed and unsaved files") }
        return "During this run the code it uses changed, \(pezzi.joined(separator: " and ")), the last \(Quando.frase(cambi.ultimo)). Steps that start after a change use the new code."
    }
}
