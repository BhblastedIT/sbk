import AppKit
import SwiftUI


struct FoglioView: View {
    let foglio: Foglio
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            switch foglio {
            case .fullRun: FoglioFullRun()
            case .altroRun(let voce): FoglioAltroRun(voce: voce)
            case .completa(let tipo): FoglioCompleta(tipo: tipo)
            case .ferma(let r): FoglioFerma(run: r)
            case .riprendi(let r): FoglioRiprendi(ripresa: r)
            case .stadio(let s): FoglioStadio(stadio: s)
            case .comeSiFa(let f): FoglioComeSiFa(fonti: f)
            case .guida: FoglioGuida()
            case .copie: FoglioCopie()
            case .verifiche: FoglioVerifiche()
            }
        }
        .padding(Spazio.sezioni)
        .frame(width: 600)
    }
}


struct AvvisoSonno: View {
    @Environment(Store.self) private var store

    var body: some View {
        if let s = store.stato?.sonno {
            VStack(alignment: .leading, spacing: 4) {
                if s.alimentazione == "batteria" {
                    Label("The Mac is on battery\(s.carica.map { " (\($0)%)" } ?? ""). Plug in the charger, the run takes hours.",
                          systemImage: Simbolo.batteria)
                }
                if s.coperchio == "dorme" {
                    Label("If you close the lid the Mac sleeps and the run stops until you reopen it.",
                          systemImage: Simbolo.coperchio)
                }
                Label("While the run is going the Mac will not sleep on its own. When it finishes it goes back to normal.",
                      systemImage: "moon.zzz")
            }
            .font(Testo.secondario)
            .foregroundStyle(.secondary)
        }
    }
}

struct TitoloFoglio: View {
    let simbolo: String
    let tinta: Color
    let titolo: String
    let sottotitolo: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            TesseraIcona(simbolo: simbolo, colore: tinta, lato: 40)
            VStack(alignment: .leading, spacing: 4) {
                Text(titolo).font(.title2.weight(.bold))
                Text(sottotitolo).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}


struct PassiDelRun: View {
    let passi: [PassoConferma]
    let tinta: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(passi.enumerated()), id: \.offset) { i, p in
                HStack(alignment: .top, spacing: 12) {
                    Text("\(i + 1)")
                        .font(.callout.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(width: 24, height: 24)
                        .background(tinta.gradient, in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.titolo).font(Testo.nome)
                        Text(p.frase).font(Testo.secondario).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct FoglioFullRun: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        let c = store.stato?.azioni.conferma_full
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: Simbolo.fullRun, tinta: .blue, titolo: "Full run free",
                         sottotitolo: "No spending. It usually takes hours, and you can close the window, the run keeps going anyway.")
            PassiDelRun(passi: c?.passi ?? [], tinta: .blue)
            if let fuori = c?.fuori, !fuori.isEmpty {
                VStack(alignment: .leading, spacing: 6) {

                    Text("Left out of this run").font(Testo.nome)
                    ForEach(fuori, id: \.self) { f in
                        Label(f, systemImage: Simbolo.saltato).font(Testo.secondario)
                    }
                }
            }
            if let ultima = c?.ultima_volta, !ultima.isEmpty {
                Text(ultima).font(Testo.secondario).foregroundStyle(.secondary)
            }
            PrimaDiPartire()
            AvvisoSonno()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button("Start the full run free") {
                    chiudi()
                    Task { await store.lancia(tipo: "full") }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(store.occupato)
            }
        }
    }
}

struct FoglioAltroRun: View {
    let voce: VoceMenu
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: Simbolo.fullRun, tinta: .blue, titolo: "Start «\(voce.nome)»?",
                         sottotitolo: "\(voce.frase) \(voce.step.prima()).")
            Text("You can close the window, the run keeps going anyway.").foregroundStyle(.secondary)
            AvvisoSonno()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button("Start") {
                    chiudi()
                    Task { await store.lancia(tipo: voce.tipo, arg: voce.arg) }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(store.occupato)
            }
        }
    }
}








struct FoglioCompleta: View {
    let tipo: String
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi
    @State private var conferma = false

    private var completa: Bool { tipo != "tutto" }

    private func t(_ chiave: String, _ valori: [String: String] = [:]) -> String {
        store.stato?.c(chiave, valori) ?? chiave
    }

    var body: some View {
        let pagati = store.stato?.stadi.filter(\.pagato) ?? []
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: Simbolo.completa, tinta: .purple,
                         titolo: t(completa ? "titolo" : "titolo_tutto"),
                         sottotitolo: t(completa ? "sottotitolo" : "sottotitolo_tutto"))
            VStack(spacing: 0) {
                HStack {
                    Text(t("step_a_pagamento")).font(Testo.nome)
                    Spacer()
                    Button(t(store.spesaScelta.count == pagati.count ? "togli_tutti" : "scegli_tutti")) {
                        store.spesaScelta = store.spesaScelta.count == pagati.count ? [] : Set(pagati.map(\.id))
                    }
                    .buttonStyle(.link)
                    .font(Testo.secondario)
                }
                .padding(.vertical, 10)
                ForEach(pagati) { s in
                    Separatore()
                    rigaPagata(s)
                }
                Separatore()
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t("totale")).font(Testo.nome)
                        Text(t("conteggio", ["n": "\(store.spesaScelta.count)", "m": "\(pagati.count)"]))
                            .font(Testo.secondario).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Cifra(testo: totale, dimensione: 24)
                        .foregroundStyle(store.stimaInCorso ? .secondary : .primary)
                        .animation(.smooth(duration: 0.25), value: totale)
                }
                .padding(.vertical, 12)
            }
            .padding(.horizontal, 14)
            .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            if let fuori = store.stima?.fuori ?? store.stato?.fuori_stima, !fuori.isEmpty, !store.spesaScelta.isEmpty {
                FuoriDallaStima(voci: fuori)
            }
            if let chiavi = store.stato?.chiavi, !chiavi.isEmpty {
                Label(rigaChiavi(chiavi), systemImage: "key.fill")
                    .font(Testo.secondario)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(alignment: .firstTextBaseline, spacing: Spazio.griglia) {
                if !notaStima.isEmpty {
                    Text(notaStima).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Button(t("ricalcola")) { Task { await store.preparaStima() } }
                    .buttonStyle(.link)
                    .font(Testo.secondario)
                    .disabled(store.stimaInCorso || store.modoIstantanea || store.runVivo != nil
                              || store.stato?.da_fuori.attivo == true)
                    .help(t("aiuto_ricalcola"))
            }
            if completa {
                PrimaDiPartire()
                AvvisoSonno()
            }
            HStack {
                if store.spesaScelta.isEmpty {
                    Text(t("nessuno_scelto"))
                        .font(Testo.secondario).foregroundStyle(.secondary)
                }
                Spacer()

                Button(t("annulla"), role: .cancel) { chiudi() }
                    .keyboardShortcut(.defaultAction)
                Button("") { chiudi() }
                    .keyboardShortcut(.cancelAction)
                    .frame(width: 0, height: 0)
                    .opacity(0)
                    .accessibilityHidden(true)
                Button(etichettaAvanti) { conferma = true }
                    .buttonStyle(.borderedProminent)
                    .tint(.purple)
                    .disabled(store.spesaScelta.isEmpty || store.stimaInCorso || store.occupato)
            }
        }
        .secondaConferma($conferma, titolo: titoloConferma, messaggio: messaggioConferma(pagati),
                         pulsante: conStima ? t("conferma_si", ["cifra": totale]) : t("conferma_si_senza_stima")) {
            let scelti = pagati.map(\.id).filter { store.spesaScelta.contains($0) }
            chiudi()
            Task {
                await store.lancia(tipo: completa ? "full_completa" : "modo", arg: completa ? "" : "tutto",
                                   consentiSpesa: true, spesa: scelti)
            }
        }
        .task {

            if !store.modoIstantanea && store.stimaDaRifare { await store.preparaStima() }
        }
    }

    private func rigaPagata(_ s: Stadio) -> some View {
        let st = store.stima?.stadi.first(where: { $0.id == s.id })
        let scelto = Binding(get: { store.spesaScelta.contains(s.id) },
                             set: { if $0 { store.spesaScelta.insert(s.id) } else { store.spesaScelta.remove(s.id) } })
        return Toggle(isOn: scelto) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(s.nome).font(Testo.nome)
                    Text(sotto(s, st)).font(Testo.secondario).foregroundStyle(.secondary)
                    if let nota = st?.nota, !nota.isEmpty {
                        Text(nota).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer()
                if store.stimaInCorso { ProgressView().controlSize(.small) }
                Text(st?.dollari.map { t("cifra", ["n": Cifre.conPunti($0)]) } ?? (st?.errore ?? t("da_calcolare")))
                    .font(Testo.cifreInColonna.weight(.semibold))
                    .foregroundStyle(scelto.wrappedValue && !store.stimaInCorso ? .primary : .secondary)
            }
        }
        .toggleStyle(.checkbox)
        .padding(.vertical, 9)
    }

    private func sotto(_ s: Stadio, _ st: StadioStima?) -> String {
        let documenti = st?.documenti.map { t("documenti", ["n": Cifre.conPunti($0)]) } ?? t("documenti_mai")
        let fermo = s.ultimo.quando.map { t("fermo_dal", ["data": Quando.breve($0)]) } ?? t("mai_fatto")
        return "\(documenti) · \(fermo)"
    }


    private var conStima: Bool {
        guard let stima = store.stima, !store.spesaScelta.isEmpty else { return false }
        return stima.stadi.filter { store.spesaScelta.contains($0.id) }.compactMap(\.dollari).count == store.spesaScelta.count
    }


    private var totale: String {
        guard let stima = store.stima else { return t("da_calcolare") }
        if store.spesaScelta.isEmpty { return t("zero") }
        guard conStima else { return t("incompleto") }
        let somma = stima.stadi.filter { store.spesaScelta.contains($0.id) }.compactMap(\.dollari).reduce(0, +)
        return t("cifra", ["n": Cifre.conPunti(somma)])
    }

    private var titoloConferma: String {
        conStima ? t("conferma_titolo", ["cifra": totale]) : t("conferma_titolo_senza_stima")
    }

    private func messaggioConferma(_ pagati: [Stadio]) -> String {
        let nomi = pagati.filter { store.spesaScelta.contains($0.id) }.map(\.nome)
        let fila = nomi.count > 1 ? nomi.dropLast().joined(separator: ", ") + " \(t("e")) " + (nomi.last ?? "") : (nomi.first ?? "")
        let chiave = store.chiavePaga.map { t("conferma_chiave", ["nome": $0]) } ?? ""
        return t("conferma_messaggio", ["step": fila, "chiave": chiave])
    }

    private var etichettaAvanti: String {
        conStima ? t("avanti", ["cifra": totale]) : t("avanti_senza_stima")
    }

    private func rigaChiavi(_ chiavi: [Chiave]) -> String {
        guard let chiave = chiavi.first(where: { $0.presente != false && $0.errore == nil }) else {
            return t("chiave_nessuna")
        }
        return t("chiave_paga", ["nome": chiave.nome])
    }

    private var notaStima: String {
        if let errore = store.erroreStima {
            return store.stima.map { t("nota_errore", ["errore": errore, "quando": Quando.frase($0.quando)]) } ?? errore
        }
        if store.stimaInCorso {
            return store.stima.map { t("nota_in_corso", ["quando": Quando.frase($0.quando)]) } ?? t("nota_in_corso_prima")
        }
        guard let s = store.stima else { return "" }
        var pezzi = [t(store.stimaDaRifare ? "stima" : "stima_dopo_run", ["quando": Quando.frase(s.quando)])]
        if completa { pezzi.append(t("nota_scarico")) }
        pezzi.append(t("nota"))

        if let pct = s.margine_tetto_pct { pezzi.append(t("nota_tetto", ["pct": "\(pct)"])) }
        return pezzi.joined(separator: " ")
    }
}

struct FoglioFerma: View {
    let run: Run
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {

            let conseguenze = (store.comandiRun ?? run.comandi)?.ferma.frase ?? ""
            TitoloFoglio(simbolo: Simbolo.ferma, tinta: .red, titolo: "Stop \(run.nome ?? "the run")?",
                         sottotitolo: conseguenze.isEmpty
                             ? "The running step first gets a gentle interruption, so it closes its files. If that is not enough, it is force-closed after a minute. The interrupted step will have to be redone, what is already downloaded stays."
                             : conseguenze)
            if conseguenze.isEmpty, let c = (store.avanzamento ?? run.avanzamento)?.corrente, c.pagato == true, c.lotti_salvati != true {
                Label("A paid step is working and may be sending. If you stop it now, what it has already sent can be lost and would be paid for again. Better to wait for the sending to finish.",
                      systemImage: Simbolo.attenzione)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                Button("Stop the run", role: .destructive) {
                    chiudi()
                    Task { await store.ferma(run) }
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
            }
        }
    }
}


struct FoglioRiprendi: View {
    let ripresa: Ripresa
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    @State private var conferma = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: "arrow.clockwise.circle.fill", tinta: ripresa.spende ? .purple : .blue,
                         titolo: "Resume from where you were?", sottotitolo: ripresa.frase)
            if !ripresa.salta.isEmpty {
                Label("\(ripresa.salta.count) already closed downloads are not redone, the sources keep the date from back then.",
                      systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if ripresa.spende {
                Label("It spends like the Full run complete you stopped, with the same paid steps.",
                      systemImage: "creditcard.fill")
                    .foregroundStyle(.purple)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let perche = store.fermo(ripresa.azione) {
                Label(perche, systemImage: Simbolo.attenzione)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                if ripresa.spende {


                    Button("Resume and spend") { conferma = true }
                        .buttonStyle(.borderedProminent)
                        .tint(.purple)
                        .disabled(store.fermo(ripresa.azione) != nil)
                } else {
                    Button("Resume") {
                        chiudi()
                        Task { await store.riprendi(ripresa) }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(store.fermo(ripresa.azione) != nil)
                }
            }
        }
        .secondaConferma($conferma, titolo: "Resume and spend?",
                         messaggio: "This is the second confirmation. The Full run complete you stopped restarts, with the same paid steps."
                             + (store.chiavePaga.map { " It is charged to the key in \($0)." } ?? "") + " After this click the spending begins.",
                         pulsante: "Yes, resume and spend") {
            chiudi()
            Task { await store.riprendi(ripresa) }
        }
    }
}



struct FoglioStadio: View {
    let stadio: Stadio
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    private var azione: Azione { Azione(tipo: "stadio", arg: stadio.id, etichetta: "") }
    @State private var conferma = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: stadio.pagato ? Simbolo.completa : "arrow.clockwise.circle.fill",
                         tinta: stadio.pagato ? .purple : .blue,
                         titolo: "Redo only «\(stadio.nome)»?",
                         sottotitolo: stadio.da_solo.frase ?? "")
            if let d = stadio.ultimo.durata_s, d > 0 {
                Label("Last time it took \(Quando.durata(d)).", systemImage: "clock")
                    .foregroundStyle(.secondary)
            }
            if stadio.pagato {
                Label(costo, systemImage: "creditcard.fill")
                    .foregroundStyle(.purple)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let perche = store.fermo(azione) {
                Label(perche, systemImage: Simbolo.attenzione)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { chiudi() }
                    .keyboardShortcut(.cancelAction)
                if stadio.pagato {


                    Button("Redo and spend") { conferma = true }
                        .buttonStyle(.borderedProminent)
                        .tint(.purple)
                        .disabled(store.fermo(azione) != nil)
                } else {
                    Button("Redo") {
                        chiudi()
                        Task { await store.rifaiStadio(stadio) }
                    }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(store.fermo(azione) != nil)
                }
            }
        }
        .secondaConferma($conferma, titolo: dollari.map { "Really spend about \($0) $?" } ?? "Really spend, without an estimate?",
                         messaggio: "This is the second confirmation. Only «\(stadio.nome)» restarts, paid."
                             + (store.chiavePaga.map { " It is charged to the key in \($0)." } ?? "") + " After this click the spending begins.",
                         pulsante: dollari.map { "Yes, spend about \($0) $" } ?? "Yes, redo and spend") {
            chiudi()
            Task { await store.rifaiStadio(stadio) }
        }
    }

    private var dollari: Int? {
        store.stima?.stadi.first(where: { $0.id == stadio.id })?.dollari.map { Int($0.rounded()) }
    }

    private var costo: String {
        if let s = store.stima?.stadi.first(where: { $0.id == stadio.id }), let d = s.dollari {
            return "Estimated cost about \(Int(d.rounded())) $, from the estimate \(Quando.frase(store.stima?.quando))."
        }
        return "The estimated cost is not there yet. The estimate is computed with the pipeline stopped, from Spend and keys."
    }
}

struct FoglioComeSiFa: View {
    let fonti: [Fonte]
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: "hand.point.up.left.fill", tinta: .teal,
                         titolo: fonti.count == 1 ? fonti[0].nome : "The sources you bring",
                         sottotitolo: fonti.count == 1 ? fonti[0].come_si_aggiorna
                             : "These do not download on their own. Each has its own way, and the pipeline reads them at the next full run.")
            ForEach(fonti) { f in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: Spazio.fratelli) {
                        IconaFonte(fonte: f)
                        Text(f.nome).font(Testo.nome)
                        Spacer()
                        Pillola(segnale: .fonte(f))
                    }
                    if let passi = f.passi_a_mano, !passi.isEmpty {
                        Text(passi).fixedSize(horizontal: false, vertical: true)
                    } else {
                        Text(f.come_si_aggiorna).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(12)
                .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            HStack {
                Spacer()
                Button("Got it") { chiudi() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }
}



struct FoglioGuida: View {
    @Environment(\.dismiss) private var chiudi
    @Environment(Store.self) private var store

    var body: some View {


        let g = store.stato?.guida
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: "questionmark.circle.fill", tinta: .blue, titolo: g?.titolo ?? "How to read SBK",
                         sottotitolo: g?.sottotitolo ?? "Everything has a color, a symbol and a word. The color alone is never enough.")


            VStack(alignment: .leading, spacing: 8) {
                if let g {
                    ForEach(g.legenda, id: \.self) { v in
                        voce(Segnale(salute: Salute(motore: v.salute), simbolo: Simbolo.da(v.simbolo), parola: v.parola), v.frase)
                    }
                } else {
                voce(Segnale(salute: .ok, parola: "Done"), "Green only with proof, a successful download or a step that read the current data.")
                voce(Segnale(salute: .neutra, simbolo: Simbolo.nonGira, parola: "Not running since…"), "Grey, new data arrived after its last run. It says since when it has not run, and brings it in with Re-read and update.")
                voce(Segnale(salute: .attenzione, parola: "To check"), "Orange, stopped for longer than its cadence, or new data waiting for more than a day.")
                voce(Segnale(salute: .errore, parola: "Failed"), "Red, the last attempt did not go through. There is always a way to redo it.")
                voce(Segnale(salute: .inCorso, parola: "Running"), "Blue, it is running right now.")
                voce(Segnale(salute: .neutra, simbolo: Simbolo.aPagamento, parola: "You decide"), "The card, it calls the pay-per-use model and starts only if you choose it.")
                voce(Segnale(salute: .neutra, simbolo: Simbolo.manuale, parola: "Manual"), "The hand, you bring it in yourself, or it is stopped because you decided so.")
                }
            }
            .padding(12)
            .background(Superficie.incasso, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 6) {
                Text("The sections").font(Testo.nome)
                Text(g?.sezioni ?? "Overview tells you whether you can trust the data and what to fix. Sources shows where the data comes from and how fresh it is. Pipeline shows all the steps, phase by phase, with the last time of each. Run follows what is running, with the lanes and the log. Spending and API key holds the estimate of the paid steps and whether your ANTHROPIC_API_KEY is set. Rules tells how each source is downloaded and what each step does. Tools holds the alerts, the settings, the Mac's memory and the disk.")
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("The runs").font(Testo.nome)
                Text(g?.run ?? "Full run free downloads all the sources, makes a copy of the brain and re-reads without spending. Full run complete does the same plus the paid steps you choose, with the expected cost. The download runs in lanes, base, Slack, ClickUp and Drive together, if the Mac's memory allows it. One run at a time, and you can close the window, the run keeps going.")
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(g?.nota ?? "Hover over a symbol, a colored word or a number and it tells you what it means. Search for anything with ⌘F, commands too. From ⌘1 to ⌘7 you move from one section to another.")
                .font(Testo.secondario).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Got it") { chiudi() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private func voce(_ segnale: Segnale, _ frase: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Pillola(segnale: segnale).frame(width: 140, alignment: .leading)
            Text(frase).font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
        }
    }
}


struct FuoriDallaStima: View {
    let voci: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("The figure does not count", systemImage: Simbolo.attenzione)
                .font(Testo.nome)
                .foregroundStyle(Salute.attenzione.colore)
            ForEach(voci, id: \.self) { v in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("•").foregroundStyle(.secondary)
                    Text(v).font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Salute.attenzione.colore.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}



struct FoglioCopie: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        let c = store.stato?.copie
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: "externaldrive.fill", tinta: Salute(motore: c?.salute ?? "neutra").colore,
                         titolo: "Backups", sottotitolo: c?.frase ?? "I can't find the backup status.")
            if let c {
                Tabellina(titolo: "The last backup, by level", voci: c.livelli.map { l in
                    Voce(etichetta: l.nome, valore: Quando.frase(l.quando))
                } + [Voce(etichetta: "Off this Mac", valore: c.fuori_dal_mac ? "yes" : "no backup")])
                VStack(alignment: .leading, spacing: 4) {
                    Text("The weekly run").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    Text(giro(c.giro_settimanale)).fixedSize(horizontal: false, vertical: true)
                }

                Text("A copy on an external disk or off the Mac is up to you. Before every re-read the full run also makes a copy of the brain, separate from these.")
                    .font(Testo.secondario).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()

                if let c, c.salute != "ok" {
                    Button("Open agent in the terminal") { apri(c) }
                        .disabled(store.apriAgenteInCorso)
                }
                Button("Close") { chiudi() }
                    .keyboardShortcut(.cancelAction)
            }
        }
    }

    private func giro(_ g: GiroCopie) -> String {


        switch g.esito {
        case 0: return "It went well."
        case nil: return "I don't know how the last run went."
        default:
            let quando = g.quando.map { " Last attempt \(Quando.frase($0))." } ?? ""
            return (g.frase.isEmpty ? "It fails." : g.frase) + quando
        }
    }




    private func apri(_ c: Copie) {
        var righe = ["SBK · backups", c.frase]
        righe += c.livelli.map { "\($0.nome), \($0.quando)" }
        righe.append("Weekly run, exit \(c.giro_settimanale.esito.map(String.init) ?? "?"). \(c.giro_settimanale.frase)")
        righe.append("A copy on an external disk or off the Mac is up to you.")
        Task {
            await store.apriAgente(testo: righe.joined(separator: "\n"))
            if case .copie = store.foglio { chiudi() }
        }
    }
}




struct PrimaDiPartire: View {
    @Environment(Store.self) private var store

    var body: some View {
        let ferme = (store.stato?.fonti ?? []).filter {
            ["da_sole", "inventari"].contains($0.gruppo) && $0.salute == "errore" && $0.diagnosi?.ritenta == false
        }
        if !ferme.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Label(ferme.count == 1 ? "One source will not download" : "\(ferme.count) sources will not download",
                      systemImage: Simbolo.attenzione)
                    .font(Testo.nome)
                    .foregroundStyle(Salute.attenzione.colore)
                ForEach(ferme) { f in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text("•").foregroundStyle(.secondary)
                        Text("\(f.nome). \(f.diagnosi?.rimedio ?? f.motivo)")
                            .font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
                    }
                }
                Text("It is the last attempt that says so, not a check done now. The other sources download anyway.")
                    .font(Testo.secondario).foregroundStyle(.secondary)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Salute.attenzione.colore.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }
}




struct FoglioVerifiche: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var chiudi

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.griglia) {
            TitoloFoglio(simbolo: "person.2.fill", tinta: .orange, titolo: "Contacts to verify", sottotitolo: sottotitolo)
            if let v = store.verifiche {
                if v.casi.isEmpty {
                    Text(v.frase ?? "Nothing to verify. The merge matches by name only when it is sure.")
                        .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Spazio.fratelli) {
                            ForEach(v.casi) { caso in RigaVerifica(caso: caso) }
                        }
                    }
                    .frame(maxHeight: 460)
                    if v.totale > v.casi.count {
                        Text("Here are the first \(v.casi.count) of \(v.totale). The others arrive as you answer.")
                            .font(Testo.secondario).foregroundStyle(.secondary)
                    }
                }
            } else {
                Text(store.erroreVerifiche ?? "Reading the contacts to verify.").foregroundStyle(.secondary)
            }
            HStack {
                if store.ultimaVerifica != nil {
                    Button("Undo the last answer") { Task { await store.annullaUltimaVerifica() } }
                        .help("Removes the last answer you gave and puts that contact back in the list.")
                }
                Spacer()
                Button("Close") { chiudi() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .task { await store.caricaVerifiche() }
    }

    private var sottotitolo: String {
        "The merge does not match a contact by name when it is not sure, for example with a one-word name, a name "
            + "that is only similar, or several people with the same name. Tell me who it is and from the next run it takes their messages."
    }
}


struct RigaVerifica: View {
    let caso: CasoVerifica
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.righeTesto * 3) {
            HStack(alignment: .firstTextBaseline, spacing: Spazio.simboloTesto) {
                Text(caso.nome).font(Testo.nome)
                Text("· \(caso.nome_fonte)").foregroundStyle(.secondary)
                Spacer()
                if !caso.dettagli.isEmpty {
                    Text(caso.dettagli).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
                        .help(caso.dettagli)
                }
            }
            Text(caso.motivo).font(Testo.secondario).foregroundStyle(.secondary)
                .help("Why the merge did not match it on its own.")
            ForEach(caso.candidati, id: \.email) { c in
                Button { Task { await store.rispondi(caso, esito: "si", email: c.email) } } label: {
                    Label("It's \(c.nome.isEmpty ? c.email : c.nome), \(c.email)", systemImage: "checkmark.circle")
                }
                .buttonStyle(.bordered)
                .help("From the next run \(caso.nome) of \(caso.nome_fonte) matches this contact.")
            }
            if let altri = caso.altri_candidati, altri > 0 {
                Text(altri == 1 ? "And one more contact with the same name." : "And \(altri) more contacts with the same name.")
                    .font(Testo.secondario).foregroundStyle(.secondary)
            }
            Button { Task { await store.rispondi(caso, esito: "no") } } label: {
                Label("None of these", systemImage: "xmark.circle")
            }
            .buttonStyle(.bordered)
            .tint(.secondary)
            .help("It does not match any of these contacts, and I won't ask you again.")
        }
        .padding(Spazio.interno)
        .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }
}
