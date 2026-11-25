import AppKit
import SwiftUI


struct Ispettore: View {
    @Environment(Store.self) private var store

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spazio.griglia) {
                switch store.selezione {
                case .fonte(let id):
                    if let f = store.stato?.fonti.first(where: { $0.id == id }) { DettaglioFonte(fonte: f) }
                case .stadio(let id):
                    if let s = store.stato?.stadi.first(where: { $0.id == id }) { DettaglioStadio(stadio: s) }
                case .fase(let id):
                    if let f = store.stato?.fasi.first(where: { $0.id == id }) { DettaglioFase(fase: f) }
                case nil:
                    Text("Choose a source, a step or a phase to see its detail.")
                        .foregroundStyle(.secondary)
                        .padding(.top, 40)
                }
            }
            .padding(Spazio.margine)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct Testata: View {
    let titolo: String
    let sottotitolo: String

    var body: some View {
        VStack(alignment: .leading, spacing: Spazio.righeTesto) {
            Text(titolo).font(Testo.titoloSezione)
            Text(sottotitolo).font(Testo.secondario).foregroundStyle(.secondary)
        }
        .textSelection(.enabled)
    }
}

struct RiquadroStato: View {
    let segnale: Segnale
    let testo: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
            SegnaleView(segnale: segnale, compatto: true)
            Text(testo.isEmpty ? segnale.parola.prima() + "." : testo)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .padding(Spazio.interno)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(segnale.salute.colore.opacity(segnale.salute == .neutra ? 0.08 : 0.12),
                    in: RoundedRectangle(cornerRadius: Raggio.piccolo))
    }
}

struct Voce: Identifiable {
    let etichetta: String
    let valore: String
    var id: String { etichetta }
}


struct Tabellina: View {
    let titolo: String
    let voci: [Voce]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(titolo).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 0) {
                ForEach(Array(voci.enumerated()), id: \.element.id) { i, v in
                    if i > 0 { Separatore() }
                    HStack(alignment: .firstTextBaseline) {
                        Text(v.etichetta).foregroundStyle(.secondary)
                        Spacer(minLength: Spazio.fratelli)
                        Text(v.valore).multilineTextAlignment(.trailing).textSelection(.enabled)
                    }
                    .font(Testo.secondario)
                    .padding(.vertical, 6)
                }
            }
            .padding(.horizontal, 10)
            .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
        }
    }
}

struct Paragrafo: View {
    let titolo: String
    let testo: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(titolo).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            Text(testo).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        }
    }
}

struct DettaglioFonte: View {
    let fonte: Fonte
    @Environment(Store.self) private var store

    var body: some View {
        HStack(spacing: Spazio.interno) {
            IconaFonte(fonte: fonte).scaleEffect(1.4).frame(width: 34, height: 34)
            Testata(titolo: fonte.nome, sottotitolo: fonte.descrizione)
        }

        RiquadroStato(segnale: .fonte(fonte), testo: fonte.diagnosi == nil ? fonte.motivo : "")
        if let d = fonte.diagnosi {
            SchedaDiagnosi(diagnosi: d, oggetto: Oggetto(tipo: "fonte", id: fonte.id), pulsanteFonte: fonte.azione)
        }
        if !["chiuse", "da_collegare"].contains(fonte.gruppo) {
            Tabellina(titolo: "When", voci: voci)
        }
        Paragrafo(titolo: "How it updates", testo: fonte.come_si_aggiorna)
        if fonte.id == "gdrive" { SchedaDrive() }
        ComeLavoraFonte(id: fonte.id)
        if let entra = fonte.entra_in {
            VStack(alignment: .leading, spacing: 4) {
                Text("Enters the pipeline").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                Button(entra.nome) { store.scegli(Oggetto(tipo: "stadio", id: entra.id)) }
                    .buttonStyle(.link)
            }
        }
        if let s = store.scarichiVivi.first(where: { $0.sorgente == fonte.id }) {
            RigaScarico(scarico: s, compatta: true).scheda(interno: 0)
        } else if let azione = fonte.azione, azione.tipo != "copia_per_claude" || fonte.diagnosi == nil {


            if let perche = store.fermo(azione) {
                Text(perche).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let d = fonte.diagnosi, d.ritenta == false {

                Button(azione.etichetta) { store.esegui(azione, oggetto: Oggetto(tipo: "fonte", id: fonte.id)) }
                    .buttonStyle(.bordered)
                Text("Retrying now would give the same error. Once it is fixed, it re-downloads from here.")
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Button(azione.etichetta) { store.esegui(azione, oggetto: Oggetto(tipo: "fonte", id: fonte.id)) }
                    .buttonStyle(.borderedProminent)
                if azione.tipo == "da_sola" {
                    Text("It downloads on its own, even while a full run is going. It does not re-read; new data enters the brain with the next reading.")
                        .font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        DisclosureGroup("Technical details") {
            VStack(alignment: .leading, spacing: 4) {
                Text("id \(fonte.id) · \(fonte.natura)")
                if let senza = fonte.passi_senza_traccia, !senza.isEmpty {
                    Text("Steps with no recorded successful download, \(senza.joined(separator: ", ")).")
                }
            }
            .font(Testo.log)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var voci: [Voce] {
        var v = [Voce(etichetta: "Data as of", valore: datiDel)]
        if let wa = fonte.import_whatsapp {

            if let c = wa.completo {
                v.append(Voce(etichetta: "Last full update",
                              valore: "\(Quando.frase(c.quando)), data up to \(Quando.breve(c.dati_fino_al))"))
            } else {
                v.append(Voce(etichetta: "Last full update", valore: "not found"))
            }
            if let k = wa.chat, let n = k.chat, n > 0 {
                v.append(Voce(etichetta: "Last chat loaded",
                              valore: "\(n == 1 ? "one chat" : "\(n) chats"), \(Quando.frase(k.quando))"))
            }
        }
        if fonte.gruppo != "a_mano" {
            v.append(Voce(etichetta: "Last successful download", valore: fonte.scaricata.map { Quando.frase($0) } ?? "not recorded"))
            if let t = fonte.ultimo_tentativo, t.esito != "ok" {
                v.append(Voce(etichetta: "Last attempt", valore: "failed, \(Quando.frase(t.quando))"))
            }
        }
        v.append(Voce(etichetta: "Last reading", valore: Quando.frase(fonte.lettura)))
        if !fonte.soglia.isEmpty { v.append(Voce(etichetta: "Threshold", valore: fonte.soglia)) }
        return v
    }

    private var datiDel: String {
        guard let d = fonte.dato_del else { return "not measured" }
        if let g = fonte.giorni, g >= 2 { return "\(Quando.frase(d)), \(Int(g)) days ago" }
        return Quando.frase(d)
    }
}

struct DettaglioStadio: View {
    let stadio: Stadio
    @Environment(Store.self) private var store

    var body: some View {
        Testata(titolo: stadio.nome, sottotitolo: "Step \(stadio.numero) of \(store.stato?.stadi.count ?? 0)\(fase.map { " · \($0.nome)" } ?? "")")
        if !stadio.frase.isEmpty {
            Text(stadio.frase).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true)
        }

        RiquadroStato(segnale: .stadio(stadio), testo: (stadio.perche ?? "").isEmpty ? (stadio.ultimo.nota ?? "") : stadio.perche!)
        Tabellina(titolo: "When", voci: voci)
        ComeLavoraStadio(id: stadio.id)
        if let membri = stadio.ultimo.membri, !membri.isEmpty {
            Tabellina(titolo: "The sources it reads", voci: membri.keys.sorted().map { k in
                Voce(etichetta: k, valore: Quando.breve(membri[k] ?? nil))
            })
        }
        if !stadio.gira_con.isEmpty {
            Paragrafo(titolo: "Runs with", testo: stadio.gira_con.joined(separator: " · "))
        }

        if stadio.id == "l2_merge", let v = store.stato?.verifiche {
            VStack(alignment: .leading, spacing: 6) {
                Text("Contacts to verify").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                Text(v.frase).fixedSize(horizontal: false, vertical: true)
                if v.totale > 0 {
                    Button("Verify the contacts") { store.foglio = .verifiche }
                        .buttonStyle(.bordered)
                        .help("It opens the list, the contacts with the most messages and contracts at the top.")
                }
            }
        }
        VStack(alignment: .leading, spacing: 6) {
            Text("On its own").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            if stadio.da_solo.possibile {
                Text(stadio.da_solo.frase ?? "It can be redone on its own.").fixedSize(horizontal: false, vertical: true)
            } else {
                Text(stadio.da_solo.perche).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true)
            }
            if let azione = stadio.da_solo.azione {
                if let perche = store.fermo(azione) {
                    Text(perche).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Button(azione.etichetta) { store.esegui(azione) }
                        .buttonStyle(.bordered)
                        .tint(stadio.pagato ? .purple : .accentColor)
                }
            }
        }
        DisclosureGroup("Technical details") {
            Text("\(stadio.nome_tecnico) · \(stadio.id) · \(stadio.strato) · \(stadio.tipo)")
                .font(Testo.log)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var fase: Fase? { store.stato?.fasi.first(where: { $0.stadi.contains(stadio.id) }) }

    private var voci: [Voce] {
        var v = [Voce(etichetta: "Last time", valore: Quando.frase(stadio.ultimo.quando))]
        if let d = stadio.ultimo.durata_s { v.append(Voce(etichetta: "Duration", valore: Quando.durata(d))) }
        v.append(Voce(etichetta: "How I know", valore: stadio.ultimo.fonte))
        return v
    }
}

struct DettaglioFase: View {
    let fase: Fase
    @Environment(Store.self) private var store

    var body: some View {
        Testata(titolo: fase.nome, sottotitolo: "Phase \(fase.etichetta) · \(fase.stadi.count) step")
        Text(fase.descrizione).foregroundStyle(.primary).fixedSize(horizontal: false, vertical: true)
        RiquadroStato(segnale: .fase(fase), testo: fase.perche ?? "")

        if let azione = fase.azione {
            if let fermo = store.fermo(azione) {
                Text(fermo).font(Testo.secondario).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Button(azione.etichetta) { store.esegui(azione) }.buttonStyle(.bordered)
            }
        }
        VStack(alignment: .leading, spacing: 4) {
            ForEach(store.stato?.stadi.filter { fase.stadi.contains($0.id) } ?? []) { s in
                Button {
                    store.scegli(Oggetto(tipo: "stadio", id: s.id))
                } label: {
                    HStack {
                        SegnaleView(segnale: .stadio(s), compatto: true)
                        Text(s.nome)
                        Spacer()
                        Text(Quando.breve(s.ultimo.quando)).foregroundStyle(.secondary).monospacedDigit()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .font(Testo.secondario)
    }
}

extension String {

    func prima() -> String { prefix(1).uppercased() + dropFirst() }
}


struct Separatore: View {
    var body: some View {
        Rectangle().fill(Superficie.separatore).frame(height: 1)
    }
}





struct SchedaDrive: View {
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let d = store.drive {
                if let av = d.avanzamento { avanzamento(av) }
                VStack(alignment: .leading, spacing: 6) {
                    Text("Adjustments").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    ForEach(store.soglie.filter { $0.sezione == "drive" }) { s in
                        RigaSoglia(soglia: s)
                    }
                    if let e = store.erroreSoglia {
                        Text(e).font(Testo.secondario).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
                    }
                    Text("Three attempts per cycle. They apply from the next run launched from the app.")
                        .font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !d.caselle.isEmpty {
                    Paragrafo(titolo: "The mailboxes, in order",
                              testo: d.caselle.joined(separator: ", ") + ". A shared folder seen by several mailboxes is taken once.")
                }
            } else if let e = store.erroreDrive {
                Text(e).font(Testo.secondario).foregroundStyle(.secondary)
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .task {
            while !Task.isCancelled {
                await store.caricaDrive()
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }

    @ViewBuilder private func avanzamento(_ av: AvanzamentoDrive) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(av.vivo == true ? "Where it is now" : "Where the last attempt got to")
                .font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            Text("Attempt \(av.tentativo), from \(av.dalle.suffix(8).prefix(5)) on \(av.dalle.prefix(5)).")
            if let c = av.casella {
                Text("Mailbox \(av.caselle_prima + 1) of \(av.caselle_tot), \(c).")
            }
            if let sezione = av.sezione {
                if sezione == "cartelle condivise", let tot = av.cartelle_tot {
                    Text("Shared folder \(av.cartella_n) of \(tot)" + (av.cartella.map { ", \($0)." } ?? "."))
                } else {
                    Text(sezione == "condivisi con te" ? "Files shared with you." : "Own files.")
                }
            }
            if let i = av.file_i, let n = av.file_n, n > 0 {
                BarraProgresso(frazione: Double(i) / Double(n), colore: .blue, altezza: 6)
                Text("File \(i.formatted()) of \(n.formatted()) in this part.").font(Testo.secondario).foregroundStyle(.secondary)
            }
            Text("In this attempt \(av.scaricati.formatted()) downloaded, \(av.invariati.formatted()) already taken and unchanged, \(av.saltati.formatted()) skipped by type or size.")
                .font(Testo.secondario).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let indice = av.indice {
                Text("The index counts \(indice.formatted()) files in total.").font(Testo.secondario).foregroundStyle(.secondary)
            }
        }
    }
}
