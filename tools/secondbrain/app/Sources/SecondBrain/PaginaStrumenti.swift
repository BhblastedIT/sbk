import AppKit
import SwiftUI




struct PaginaStrumenti: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Tools",
                         sottotitolo: "The functions we built, and the thresholds you change from here") {
            if let d = stato.disco { SchedaDisco(disco: d) }
            SchedaAvvisi()
            SchedaSoglie(soglie: store.soglie)
            if let s = store.strumenti {
                SchedaGuardiano(g: s.guardiano)
                SchedaAutomatismi(automatismi: s.automatismi)
            } else if let e = store.erroreStrumenti {
                Text(e).foregroundStyle(.secondary).scheda()
            } else {
                ProgressView().frame(maxWidth: .infinity).scheda()
            }
        }
        .task {
            await store.caricaSoglie()

            while !Task.isCancelled {
                await store.caricaStrumenti()
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }
}



struct SchedaAvvisi: View {
    @AppStorage(Avvisi.chiaveFine) private var fine = true
    @AppStorage(Avvisi.chiaveFasi) private var fasi = true
    @AppStorage(Avvisi.chiaveMeta) private var meta = true
    @AppStorage(Avvisi.chiaveLavori) private var lavori = true
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {

            TitoloGruppo(titolo: "Notifications") { EmptyView() }
            VStack(spacing: 0) {
                if store.permessoAvvisi == .daChiedere || store.permessoAvvisi == .negato {
                    rigaPermesso
                    Separatore()
                }
                riga("Run finished", "When a run finishes, stops or fails, including one launched from the terminal.",
                     "flag.checkered", .green, $fine)
                Separatore().padding(.leading, 56)

                riga("Each phase", "When a phase closes, with how many steps are fine and how much is left. A step that fails is reported right away.",
                     "checklist", .blue, $fasi)
                Separatore().padding(.leading, 56)
                riga("Halfway", "When the run is halfway, with how much is left and the expected finish time.",
                     "circle.lefthalf.filled", .orange, $meta)
                Separatore().padding(.leading, 56)


                riga("Notify me when an automation fails",
                     "The backup and the other jobs that start on their own on the Mac. One alert per failure. Until it works again it stays red, at the top of the bar and in Overview.",
                     "exclamationmark.arrow.triangle.2.circlepath", .red, $lavori)
            }
            .scheda(interno: 0)

            Text("The Slack briefing is off. The automations that still write to you are below, in «What starts on its own on the Mac».")
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .task { await store.aggiornaPermesso() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await store.aggiornaPermesso() }
        }
    }


    @ViewBuilder private var rigaPermesso: some View {
        let negato = store.permessoAvvisi == .negato
        HStack(spacing: 14) {
            TesseraIcona(simbolo: "bell.slash.fill", colore: .red, lato: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(negato ? "macOS is blocking SBK's notifications" : "macOS has not granted permission yet")
                    .font(Testo.nome)
                Text(negato ? "They are re-enabled in System Settings, Notifications, SBK." :
                        "Without it, notifications do not arrive. If you do not grant it now, the first run alert will ask for it.")
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            if negato {
                Button("Open Notifications") {
                    let id = Bundle.main.bundleIdentifier ?? ""
                    if let url = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=\(id)") {
                        NSWorkspace.shared.open(url)
                    }
                }
                .buttonStyle(.bordered)
            } else {
                Button("Allow notifications") { Task { await store.permettiAvvisi() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(store.modoIstantanea)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private func riga(_ titolo: String, _ frase: String, _ simbolo: String, _ colore: Color,
                      _ valore: Binding<Bool>) -> some View {
        HStack(spacing: 14) {
            TesseraIcona(simbolo: simbolo, colore: colore, lato: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(titolo).font(Testo.nome)
                Text(frase).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Spazio.fratelli)
            Toggle(titolo, isOn: valore).toggleStyle(.switch).labelsHidden()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}





struct SchedaSoglie: View {
    let soglie: [Soglia]
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "Adjustments", conteggio: soglie.isEmpty ? "" : "\(soglie.count)") { EmptyView() }
            if soglie.isEmpty {
                Text("The adjustments cannot be read yet.").foregroundStyle(.secondary).scheda()
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(sezioni.enumerated()), id: \.element) { i, sezione in
                        if i > 0 { Separatore() }
                        Text(nomeSezione(sezione)).font(Testo.titoloGruppo)
                            .padding(.horizontal, 14).padding(.top, 12).padding(.bottom, 2)
                        ForEach(soglie.filter { $0.sezione == sezione }) { s in
                            RigaSoglia(soglia: s).padding(.horizontal, 14).padding(.vertical, 8)
                        }
                    }
                }
                .scheda(interno: 0)
                if let e = store.erroreSoglia {
                    Label(e, systemImage: Simbolo.attenzione).foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Text("Drive changes from the next Drive download, including one launched from the terminal. The guardian changes from the next step, Plaud from the next Plaud download, the noise and the new data from the next re-read, the spend margin from the next run that spends.")
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var sezioni: [String] {
        var viste: [String] = []
        for s in soglie where !viste.contains(s.sezione) { viste.append(s.sezione) }
        return viste
    }

    private func nomeSezione(_ s: String) -> String {
        switch s {
        case "drive": "Google Drive"
        case "guardiano": "Memory guardian"
        default: s.prefix(1).uppercased() + s.dropFirst()
        }
    }
}


struct RigaSoglia: View {
    let soglia: Soglia
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
                Text(soglia.nome).font(Testo.nome)
                Spacer(minLength: Spazio.fratelli)
                controllo
            }
            Text(soglia.spiegazione).font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if soglia.cambiata {
                Button("Back to \(testo(soglia.partenza))") {
                    Task { await store.imposta(soglia, soglia.partenza) }
                }
                .buttonStyle(.link)
                .font(Testo.secondario)
                .disabled(store.sogliaInScrittura != nil || store.modoIstantanea)
            }
        }
    }

    @ViewBuilder private var controllo: some View {
        let occupato = store.sogliaInScrittura != nil || store.modoIstantanea
        switch soglia.valore {
        case .acceso(let b):
            Toggle(soglia.nome, isOn: Binding(get: { b }, set: { nuovo in
                Task { await store.imposta(soglia, .acceso(nuovo)) }
            }))
            .toggleStyle(.switch).labelsHidden().disabled(occupato)
        case .numero(let n):
            HStack(spacing: 6) {
                Text(testo(.numero(n))).font(Testo.cifreInColonna.weight(.semibold))
                Stepper(soglia.nome, value: Binding(get: { n }, set: { nuovo in
                    Task { await store.imposta(soglia, .numero(nuovo)) }
                }), in: (soglia.minimo ?? 0)...(soglia.massimo ?? Int.max), step: passo)
                .labelsHidden()
                .disabled(occupato)
            }
        }
    }


    private var passo: Int { soglia.chiave == "giorni" ? 7 : 1 }

    private func testo(_ v: ValoreSoglia) -> String {
        switch v {
        case .acceso(let b): return b ? "on" : "off"
        case .numero(let n):
            if soglia.chiave == "giorni" { return n == 0 ? "all history" : "last \(n) days" }
            return soglia.unita.isEmpty ? "\(n)" : "\(n) \(soglia.unita)"
        }
    }
}



struct SchedaGuardiano: View {
    let g: Guardiano

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "Memory guardian") { EmptyView() }
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 16) {
                    AnelloPercentuale(frazione: Double(g.pressione.pct ?? 0) / 100, lato: 64)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(frasePressione).font(Testo.nome)
                        Text("It is the measure that raises the alarm before reboots: how close the memory compressor is to the wall.")
                            .font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if let b = g.budget {
                            Text(fraseBudget(b)).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                Separatore()
                VStack(alignment: .leading, spacing: 6) {
                    Text("How it works").font(Testo.titoloGruppo)
                    ForEach(g.regole, id: \.self) { r in
                        Label { Text(r).fixedSize(horizontal: false, vertical: true) } icon: {
                            Image(systemName: "shield.lefthalf.filled").foregroundStyle(.teal)
                        }
                    }
                    if !g.numeri_letti {
                        Text("Some numbers were not found in the code, so they are missing here.")
                            .font(Testo.secondario).foregroundStyle(.orange)
                    }
                }
                Separatore()
                VStack(alignment: .leading, spacing: 6) {
                    Text("The pressure thresholds").font(Testo.titoloGruppo)
                    ForEach(g.soglie) { s in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("\(s.pct)%").font(Testo.cifreInColonna.weight(.semibold)).frame(width: 44, alignment: .trailing)
                            Text(s.cosa).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                Separatore()
                VStack(alignment: .leading, spacing: 6) {
                    Text(fraseInterventi).font(Testo.titoloGruppo)
                    ForEach(Array(g.interventi.prefix(6).enumerated()), id: \.offset) { _, i in
                        HStack(spacing: 8) {
                            Text(Quando.breve(i.quando)).font(Testo.cifreInColonna).foregroundStyle(.secondary)
                            Text(i.step ?? "a step")
                            Text(i.perche == "quota" ? "for quota" : (i.perche == "pericolo" ? "for danger" : i.perche))
                                .font(Testo.secondario).foregroundStyle(.secondary)
                        }
                    }
                }
                Separatore()
                Label {
                    Text(g.proposta).fixedSize(horizontal: false, vertical: true)
                } icon: {
                    if g.deciso == true {
                        Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                            .help("Decided by you.")
                    } else {
                        Image(systemName: "questionmark.circle.fill").foregroundStyle(.purple)
                            .help("It is a proposal, you decide.")
                    }
                }
            }
            .scheda()
        }
    }

    private var frasePressione: String {
        guard let pct = g.pressione.pct else { return "Pressure cannot be measured right now." }
        switch g.pressione.livello {
        case "ok": return "Pressure at \(pct)%, the Mac is calm."
        case "elevated": return "Pressure at \(pct)%, the Mac is working but holding."
        case "warn": return "Pressure at \(pct)%, new steps wait."
        case "critical": return "Pressure at \(pct)%, the Mac is in danger."
        default: return "Pressure at \(pct)%."
        }
    }

    private func fraseBudget(_ b: BudgetLavori) -> String {
        let lavori = b.lavori == 0 ? "no pipeline job recorded" :
            (b.lavori == 1 ? "one job recorded" : "\(b.lavori) jobs recorded")
        return "A step can now take about \(String(format: "%.1f", b.job_gb)) GB, \(lavori)."
    }

    private var fraseInterventi: String {
        let tot = g.per_quota + g.per_pericolo
        if tot == 0 { return "It never had to step in" }
        return "It stepped in \(tot) times, \(g.per_quota) for quota and \(g.per_pericolo) for danger"
    }
}



struct SchedaAutomatismi: View {
    let automatismi: [Automatismo]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "What starts on its own on the Mac", conteggio: "\(automatismi.filter(\.caricato).count) on") {
                EmptyView()
            }
            VStack(spacing: 0) {
                ForEach(Array(automatismi.enumerated()), id: \.element.id) { i, a in
                    if i > 0 { Separatore().padding(.leading, 56) }
                    HStack(alignment: .top, spacing: 14) {
                        TesseraIcona(simbolo: a.caricato ? "clock.arrow.circlepath" : "pause.circle",
                                     colore: a.caricato ? .teal : .gray, lato: 30)
                            .help(a.caricato ? "On, starts on its own." : "Off, does not start on its own.")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(a.cosa.isEmpty ? a.nome : a.cosa).fixedSize(horizontal: false, vertical: true)
                            Text(dettaglio(a)).font(Testo.secondario).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                }
            }
            .scheda(interno: 0)
            Text("They turn on and off by your decision, written in the automations inventory.")
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func dettaglio(_ a: Automatismo) -> String {
        var parti = [a.nome]
        if let il = a.spento_il {
            parti.append("off on \(il.suffix(2))/\(il.dropFirst(4).prefix(2))")
        } else if !a.caricato {
            parti.append("not loaded")
        } else {
            if !a.quando.isEmpty { parti.append(a.quando) }
            if a.gira_adesso { parti.append("running now") }


            if let r = a.registro { parti.append(r) }
            else if let rc = a.ultimo_esito, rc != 0 { parti.append("the last run exited with an error") }
        }
        return parti.joined(separator: " · ")
    }
}




struct SchedaDisco: View {
    let disco: Disco

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TitoloGruppo(titolo: "Disk space") { EmptyView() }
            HStack(spacing: 16) {
                AnelloPercentuale(frazione: Double(disco.totale_gb - disco.libero_gb) / Double(max(1, disco.totale_gb)),
                                  lato: 64)
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(disco.libero_gb) GB free of \(disco.totale_gb)").font(Testo.nome)

                    if disco.ritmo_gb_ora != nil || disco.salute != "ok" {
                        Text(disco.frase).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if disco.ritmo_gb_ora == nil {
                        Text("The rate is known after half an hour of measurements with the app open.")
                            .font(Testo.secondario).foregroundStyle(.secondary)
                    }
                }
            }
            .scheda(tinta: disco.salute == "ok" ? nil : Salute(motore: disco.salute).colore)
        }
    }
}
