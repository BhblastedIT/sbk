import AppKit
import SwiftUI





struct Comando: Identifiable {
    let id: String
    let nome: String
    let frase: String
    let simbolo: String
    let tinta: Color

    let fermo: String?

    let lancia: Bool


    var pulsante: String? = nil
    let esegui: @MainActor () -> Void
}

@MainActor
enum ElencoComandi {

    static func tutti(_ store: Store) -> [Comando] {
        guard let stato = store.stato else { return [] }
        let occupato = store.occupato ? (store.daCache ? "Checking what's running, one moment." : stato.azioni.perche) : nil
        var out: [Comando] = []
        if let r = store.runVivo {
            out.append(Comando(id: "ferma", nome: "Stop the run", frase: "Closes the current step, with the consequences explained before confirming.",
                               simbolo: Simbolo.ferma, tinta: .red, fermo: nil, lancia: false, pulsante: "Stop…") { store.foglio = .ferma(r) })
        }
        if let r = store.runVivo, let c = store.comandiRun ?? r.comandi {
            if c.continua.possibile {
                out.append(Comando(id: "continua", nome: "Resume the run", frase: "The run restarts from the step where it was waiting.",
                                   simbolo: "play.fill", tinta: .green, fermo: nil, lancia: false, pulsante: "Resume") {
                    Task { await store.continua(r) }
                })
            } else if c.fase != "altro" {
                out.append(Comando(id: "pausa", nome: "Pause the run",
                                   frase: c.pausa.frase ?? "The current step finishes, then the run waits.",
                                   simbolo: "pause.fill", tinta: .orange,
                                   fermo: c.pausa.possibile ? nil : (c.pausa.perche ?? ""), lancia: false,
                                   pulsante: "Pause") {
                    Task { await store.pausa(r) }
                })
            }
        }
        if let rp = stato.ripresa {
            out.append(Comando(id: "riprendi", nome: rp.azione.etichetta, frase: rp.frase,
                               simbolo: "arrow.clockwise", tinta: rp.spende ? .purple : .blue,
                               fermo: store.fermo(rp.azione), lancia: true, pulsante: "Resume…") { store.foglio = .riprendi(rp) })
        }
        for s in store.scarichiVivi {
            out.append(Comando(id: "ferma-\(s.run_id)", nome: "Stop \(s.nome ?? "the download")",
                               frase: "Closes the download of this source. The files already downloaded stay, the rest resumes at the next download.",
                               simbolo: Simbolo.ferma, tinta: .red,
                               fermo: store.fermoRichiesto.contains(s.run_id) ? "Stopping." : nil, lancia: false,
                               pulsante: "Stop") {
                Task { await store.fermaScarico(s) }
            })
        }
        for voce in stato.azioni.menu {
            let simbolo = voce.spesa ? Simbolo.completa : (voce.tipo == "l0" ? "arrow.down.circle.fill" : Simbolo.fullRun)
            out.append(Comando(id: "run-\(voce.id)", nome: voce.spesa ? "\(voce.nome)…" : voce.nome,
                               frase: "\(voce.frase) \(voce.step.prima()).", simbolo: simbolo,
                               tinta: voce.spesa ? .purple : (voce.id == "full" ? .blue : .teal),
                               fermo: occupato, lancia: true) { store.apri(voce) })
        }
        if store.aggiornamentoDisponibile {
            out.append(Comando(id: "aggiorna", nome: "Update SBK", frase: "Installs the new version and reopens the app. Running runs continue.",
                               simbolo: "arrow.down.app.fill", tinta: .green, fermo: store.aggiornando ? "Already updating." : nil,
                               lancia: false, pulsante: "Update and reopen") { Task { await store.aggiornaApp() } })
        }
        out.append(Comando(id: "stima", nome: "Recalculate the cost estimate", frase: "Counts the documents to read for the three paid steps, without spending anything.",
                           simbolo: "creditcard.fill", tinta: .purple,
                           fermo: store.stimaInCorso ? "Already calculating it." : (stato.da_fuori.attivo || store.runVivo != nil ? "The pipeline is running, the estimate waits for it to finish." : nil),
                           lancia: false, pulsante: "Recalculate") { Task { await store.preparaStima() } })
        let blocchi = Azione(tipo: "pulisci_lock", arg: "", etichetta: "Remove the leftover locks")
        out.append(Comando(id: "pulisci-lock", nome: "Remove the leftover locks",
                           frase: "Removes the locks left by steps that closed badly. Those of a live run are not touched.",
                           simbolo: "lock.open.fill", tinta: .orange, fermo: store.fermo(blocchi), lancia: false, pulsante: "Remove") {
            store.esegui(blocchi)
        })
        out.append(Comando(id: "rileggi", nome: "Re-read the state now", frase: "Asks the engine for the state of sources, steps and runs without waiting for the 20-second cycle.",
                           simbolo: Simbolo.aggiorna, tinta: .gray, fermo: store.leggendo ? "Already reading." : nil, lancia: false,
                           pulsante: "Re-read") {
            Task { await store.aggiorna(fresco: true) }
        })
        for f in stato.fonti {
            guard let a = f.azione else { continue }
            if a.tipo == "l0" || a.tipo == "da_sola" {
                let anche = a.tipo == "da_sola" ? " It can also run while a full run is going." : ""
                out.append(Comando(id: "scarica-\(f.id)", nome: "Download \(f.nome)", frase: "Only this source, without re-reading.\(anche) \(f.descrizione).",
                                   simbolo: IconaFonte.simbolo(f), tinta: IconaFonte.colore(f), fermo: store.fermo(a), lancia: true,
                                   pulsante: a.lungo == true ? "Download…" : "Download") {
                    store.esegui(a, oggetto: Oggetto(tipo: "fonte", id: f.id))
                })
            } else if a.tipo == "come_si_fa" {
                out.append(Comando(id: "come-\(f.id)", nome: "How to bring in \(f.nome)", frase: f.come_si_aggiorna,
                                   simbolo: "hand.point.up.left.fill", tinta: .teal, fermo: nil, lancia: false, pulsante: "See") {
                    store.esegui(a, oggetto: Oggetto(tipo: "fonte", id: f.id))
                })
            }
        }
        for s in stato.stadi where s.da_solo.possibile && s.id != "l0_download" {
            if let a = s.da_solo.azione {
                out.append(Comando(id: "stadio-\(s.id)", nome: "Redo only \(s.nome)",
                                   frase: s.da_solo.frase ?? s.frase,
                                   simbolo: s.pagato ? Simbolo.completa : "arrow.clockwise.circle",
                                   tinta: s.pagato ? .purple : .blue, fermo: store.fermo(a), lancia: true, pulsante: "Redo…") {
                    store.esegui(a)
                })
            }
        }
        out.append(Comando(id: "cartella", nome: "Open the runs folder in Finder", frase: "The journals and logs of each full run, one per folder.",
                           simbolo: "folder.fill", tinta: .blue, fermo: nil, lancia: false) {
            let c = (stato.ultimo_full_run?.cartella).map { URL(fileURLWithPath: $0).deletingLastPathComponent() }
                ?? URL(fileURLWithPath: NSHomeDirectory() + "/.sbk-data/work/sbk/pipeline-fullrun")
            NSWorkspace.shared.activateFileViewerSelecting([c])
        })
        for s in Sezione.allCases {
            out.append(Comando(id: "vai-\(s.rawValue)", nome: "Go to \(s.nome)", frase: "Opens the \(s.nome) section.", simbolo: s.simbolo,
                               tinta: .accentColor, fermo: nil, lancia: false, pulsante: "Go") { store.sezione = s })
        }
        return out
    }
}


private func corrisponde(_ testo: String, _ parole: [String]) -> Bool {
    let t = testo.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "it_IT"))
    return parole.allSatisfy { t.contains($0) }
}

private func parole(_ ricerca: String) -> [String] {
    ricerca.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "it_IT"))
        .split(separator: " ").map(String.init)
}


struct PaginaRicerca: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        corpo
            .task { if store.regole == nil { await store.caricaRegole() } }
    }

    @ViewBuilder private var corpo: some View {
        let p = parole(store.ricerca)
        let comandi = ElencoComandi.tutti(store).filter { corrisponde("\($0.nome) \($0.frase)", p) }
        let fonti = stato.fonti.filter { corrisponde("\($0.nome) \($0.descrizione) \($0.id) \($0.parola)", p) }
        let stadi = stato.stadi.filter { corrisponde("\($0.nome) \($0.nome_tecnico) \($0.id) \($0.frase)", p) }
        let runs = stato.runs.reversed().filter { corrisponde("\($0.nome ?? "") \(Quando.frase($0.inizio)) \($0.esito ?? "")", p) }

        let regoleFonti = (store.regole?.fonti ?? []).filter { $0.con_regole && corrisponde(Self.testi($0).joined(separator: " "), p) }
        let regoleStadi = (store.regole?.stadi ?? []).filter { $0.con_regole && corrisponde(Self.testi($0).joined(separator: " "), p) }
        PaginaScorrevole(stato: stato, titolo: "Search", sottotitolo: "«\(store.ricerca)»") {
            NeiTuoiDati()
            if comandi.isEmpty && fonti.isEmpty && stadi.isEmpty && runs.isEmpty && regoleFonti.isEmpty && regoleStadi.isEmpty {
                Text("Nothing for «\(store.ricerca)». Try the name of a source, a step, a command, or a word from the rules, for example «full run», «drive», «incremental».")
                    .foregroundStyle(.secondary)
                    .scheda()
            }
            if !comandi.isEmpty {
                GruppoRisultati(titolo: "Commands", conteggio: comandi.count) {
                    ForEach(comandi) { c in RigaComando(comando: c) }
                }
            }
            if !fonti.isEmpty {
                GruppoRisultati(titolo: "Sources", conteggio: fonti.count) {
                    ForEach(fonti) { f in
                        RigaRisultato(simbolo: nil, fonte: f, titolo: f.nome, sotto: f.descrizione, segnale: .fonte(f)) {
                            store.selezione = .fonte(f.id)
                            store.ispettore = true
                        }
                    }
                }
            }
            if !stadi.isEmpty {
                GruppoRisultati(titolo: "Pipeline steps", conteggio: stadi.count) {
                    ForEach(stadi) { s in
                        RigaRisultato(simbolo: "\(s.numero).circle.fill", fonte: nil, titolo: s.nome, sotto: s.frase, segnale: .stadio(s)) {
                            store.selezione = .stadio(s.id)
                            store.ispettore = true
                        }
                    }
                }
            }
            if !regoleFonti.isEmpty || !regoleStadi.isEmpty {
                GruppoRisultati(titolo: "Rules", conteggio: regoleFonti.count + regoleStadi.count) {
                    ForEach(regoleFonti) { f in
                        RigaRisultato(simbolo: Sezione.regole.simbolo, fonte: nil, titolo: "How \(f.nome) works",
                                      sotto: Self.estratto(Self.testi(f), p), segnale: Self.segnale(f.conteggio)) {
                            store.apriRegola("fonte:\(f.id)", vista: .fonti)
                        }
                    }
                    ForEach(regoleStadi) { s in
                        RigaRisultato(simbolo: Sezione.regole.simbolo, fonte: nil, titolo: "How \(s.nome) works",
                                      sotto: Self.estratto(Self.testi(s), p), segnale: Self.segnale(s.conteggio)) {
                            store.apriRegola("stadio:\(s.id)", vista: .stadi)
                        }
                    }
                }
            }
            if !runs.isEmpty {
                GruppoRisultati(titolo: "Run", conteggio: runs.count) {
                    ForEach(Array(runs.prefix(10))) { r in
                        RigaRisultato(simbolo: Simbolo.fullRun, fonte: nil, titolo: r.nome ?? "Run",
                                      sotto: "started \(Quando.frase(r.inizio))", segnale: .run(r)) {
                            store.ricerca = ""
                            store.sezione = .run
                        }
                    }
                }
            }
        }
    }
}

extension PaginaRicerca {
    static func testi(_ f: RegoleFonte) -> [String] {
        [f.nome, f.incrementale, f.cosa_scarica] + f.cosa_salta + f.limiti + f.regole_di_owner.map(\.regola)
    }

    static func testi(_ s: RegoleStadio) -> [String] {
        [s.nome, s.nome_tecnico, s.cosa_fa, s.incrementale, s.memoria, s.se_fallisce] + s.regole_di_owner.map(\.regola)
    }


    static func estratto(_ testi: [String], _ parole: [String]) -> String {
        let testo = testi.dropFirst().first(where: { corrisponde($0, parole) })
            ?? testi.dropFirst().first(where: { t in parole.contains(where: { corrisponde(t, [$0]) }) })
            ?? testi.dropFirst().first ?? ""
        return testo.prima()
    }


    static func segnale(_ conteggio: [String: Int]) -> Segnale {
        let no = conteggio["no"] ?? 0, parte = conteggio["in parte"] ?? 0, si = conteggio["sì"] ?? 0

        if no > 0 { return Segnale(salute: .errore, simbolo: "xmark.circle.fill", parola: "\(no) no") }
        if parte > 0 { return Segnale(salute: .attenzione, simbolo: "circle.lefthalf.filled", parola: "\(parte) partial") }
        if si > 0 { return Segnale(salute: .ok, simbolo: "checkmark.circle.fill", parola: "met") }
        return Segnale(salute: .neutra, simbolo: Sezione.regole.simbolo, parola: "rules")
    }
}

struct GruppoRisultati<Righe: View>: View {
    let titolo: String
    let conteggio: Int
    @ViewBuilder var righe: () -> Righe

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: titolo, conteggio: "\(conteggio)")
            VStack(spacing: 0) { righe() }
                .scheda(interno: 0)
        }
    }
}


struct RigaComando: View {
    let comando: Comando

    var body: some View {
        HStack(spacing: 14) {
            TesseraIcona(simbolo: comando.simbolo, colore: comando.tinta, lato: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(comando.nome).font(.headline)
                Text(comando.fermo ?? comando.frase)
                    .font(Testo.secondario)
                    .foregroundStyle(comando.fermo == nil ? Color.secondary : Salute.attenzione.colore)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            Button(comando.pulsante ?? (comando.lancia ? "Start…" : "Open")) { comando.esegui() }
                .buttonStyle(.borderedProminent)
                .tint(comando.tinta)
                .disabled(comando.fermo != nil)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}

struct RigaRisultato: View {
    let simbolo: String?
    let fonte: Fonte?
    let titolo: String
    let sotto: String
    let segnale: Segnale
    let azione: () -> Void
    @State private var sopra = false

    var body: some View {
        Button(action: azione) {
            HStack(spacing: 14) {
                if let fonte {
                    IconaFonte(fonte: fonte, lato: 30)
                } else if let simbolo {
                    Image(systemName: simbolo).font(.system(size: 22)).foregroundStyle(.secondary).frame(width: 30)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(titolo).font(.headline)
                    Text(sotto).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: Spazio.fratelli)

                Pillola(segnale: segnale).fixedSize()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(sopra ? Superficie.incasso : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { sopra = $0 }
    }
}


struct SezioneComandiRun: View {
    @Environment(Store.self) private var store

    var body: some View {
        let comandi = ElencoComandi.tutti(store).filter { $0.lancia && $0.id.hasPrefix("run-") }
        if !comandi.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "What you can run", conteggio: "\(comandi.count)")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 12)], spacing: 12) {
                    ForEach(comandi) { c in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(spacing: 10) {
                                TesseraIcona(simbolo: c.simbolo, colore: c.tinta, lato: 30)
                                Text(c.nome).font(.headline)
                                Spacer(minLength: 0)
                            }
                            Text(c.frase).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            HStack {
                                if let fermo = c.fermo {
                                    Label(fermo, systemImage: "pause.circle")
                                        .font(.caption)
                                        .foregroundStyle(Salute.attenzione.colore)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                Spacer(minLength: 0)
                                Button("Start…") { c.esegui() }
                                    .buttonStyle(.borderedProminent)
                                    .tint(c.tinta)
                                    .disabled(c.fermo != nil)
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
                        .scheda(interno: 14)
                    }
                }
            }
        }
    }
}




struct NeiTuoiDati: View {
    @Environment(Store.self) private var store

    var body: some View {
        let q = store.ricerca.trimmingCharacters(in: .whitespaces)
        let fatta = store.datiDomanda == q
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "In your data", conteggio: fatta && store.datiErrore == nil ? "\(store.datiRisultati.count)" : "") {
                if fatta, let s = store.datiSecondi {
                    Text("in \(s) seconds, no cost").font(.callout).foregroundStyle(.secondary)
                }
            }
            if store.cercandoDati {
                HStack(spacing: Spazio.fratelli) {
                    ProgressView().controlSize(.small)
                    Text("Searching mail, Slack, WhatsApp, calls, documents and brain. Usually about twenty seconds.")
                        .foregroundStyle(.secondary)
                }
                .scheda()
            } else if !fatta {
                HStack(spacing: 14) {
                    TesseraIcona(simbolo: "text.magnifyingglass", colore: .indigo, lato: 30)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Search «\(q)» in your data").font(.headline)
                        Text("Mail, Slack, WhatsApp, calls, documents and brain. No synthesis and no cost, about twenty seconds.")
                            .font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: Spazio.fratelli)
                    Button("Search") { Task { await store.cercaNeiDati(q) } }
                        .buttonStyle(.borderedProminent)
                        .tint(.indigo)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .scheda(interno: 0)
            } else if let errore = store.datiErrore {
                Text(errore).foregroundStyle(Salute.attenzione.colore).scheda()
            } else if store.datiRisultati.isEmpty {
                Text("Nothing for «\(q)» in your data. Try other words or a name.").foregroundStyle(.secondary).scheda()
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(store.datiRisultati.enumerated()), id: \.offset) { i, r in
                        if i > 0 { Separatore().padding(.leading, 58) }
                        RigaDato(risultato: r)
                    }
                }
                .scheda(interno: 0)
            }
        }
    }
}

struct RigaDato: View {
    let risultato: RisultatoDati

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            TesseraIcona(simbolo: Self.simbolo(risultato.nome_fonte), colore: Self.colore(risultato.nome_fonte), lato: 30)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(titolo).font(.headline).lineLimit(1)
                    Spacer(minLength: Spazio.fratelli)
                    Text(risultato.data.isEmpty ? risultato.nome_fonte : "\(risultato.nome_fonte) · \(Quando.giorno(risultato.data))")
                        .font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
                }
                Text(risultato.testo)
                    .font(Testo.secondario)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .contextMenu {
            Button("Copy the snippet") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString("\(titolo), \(risultato.nome_fonte) \(risultato.data)\n\(risultato.testo)", forType: .string)
            }
        }
    }


    private var titolo: String {
        let c = risultato.contesto
        if let a = c.firstIndex(of: "'"), let b = c[c.index(after: a)...].firstIndex(of: "'") {
            return String(c[c.index(after: a)..<b])
        }
        return c.isEmpty ? risultato.nome_fonte : String(c.prefix(80))
    }

    static func simbolo(_ nome: String) -> String {
        switch nome {
        case "Email": "envelope.fill"
        case "Slack": "number"
        case "WhatsApp": "bubble.left.fill"
        case "Plaud": "waveform"
        case "Tactiq": "captions.bubble"
        case "Attio": "person.text.rectangle"
        case "Google Drive": "folder.fill"
        case "Calendario": "calendar"
        case "ClickUp": "checklist"
        case "Notion": "doc.text"
        case "Cervello": "brain.head.profile"
        default: "doc.fill"
        }
    }

    static func colore(_ nome: String) -> Color {
        switch nome {
        case "Email": .blue
        case "Slack": .purple
        case "WhatsApp": .green
        case "Plaud", "Tactiq": .orange
        case "Attio", "ClickUp": .indigo
        case "Google Drive": .yellow
        case "Calendario": .red
        case "Cervello": .pink
        default: Color(nsColor: .systemGray)
        }
    }
}
