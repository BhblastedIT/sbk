import AppKit
import SwiftUI








struct RegolaDiOwner: Decodable, Hashable {
    let regola: String
    let perche: String
    let quando: String
    let fonte: String

    let rispettata: String
    let prova: String
    let dove_nel_codice: String
}

struct PassoGiro: Decodable, Hashable {
    let nome: String
    let tetto_s: Int
    let comando: String
}

struct RegoleFonte: Decodable, Identifiable {
    let id: String
    let nome: String
    let a_mano: Bool

    let chiusa: Bool?
    let come_a_mano: String
    let natura: String
    let ritmo_giorni: Int?
    let passi: [PassoGiro]
    let tentativi: Int
    let corsia: String
    let leggera: Bool
    let cosa_scarica: String
    let incrementale: String
    let cosa_salta: [String]
    let limiti: [String]
    let dove_scrive: [String]
    let regole_di_owner: [RegolaDiOwner]
    let conteggio: [String: Int]
    let errori: [String]
    let prove: [String]
    let note: String
    let con_regole: Bool
}

struct RegoleStadio: Decodable, Identifiable {
    let id: String
    let numero: Int
    let nome: String
    let nome_tecnico: String
    let frase: String
    let strato: String
    let pagato: Bool
    let fuori_ciclo: Bool
    let perimetri: [String]
    let tetto_s: Int?
    let script: String
    let argomenti: String
    let cosa_fa: String
    let incrementale: String
    let memoria: String
    let se_fallisce: String
    let legge: [String]
    let scrive: [String]
    let dipende_da: String
    let chi_lo_usa: String
    let spesa: [VoceSpesa]
    let regole_di_owner: [RegolaDiOwner]
    let conteggio: [String: Int]
    let prove: [String]
    let note: String
    let con_regole: Bool
}


struct VoceSpesa: Decodable, Hashable {
    let voce: String
    let testo: String
}

struct SenzaRegole: Decodable {
    let fonti: [String]
    let stadi: [String]
}

struct Regole: Decodable {
    let ok: Bool?
    let verificate: String?
    let ricontrollate: String?
    let come: String?
    let generali: [RegolaDiOwner]
    let fonti: [RegoleFonte]
    let stadi: [RegoleStadio]
    let senza_regole: SenzaRegole
    let conteggio: [String: Int]
}

enum VistaRegole: String, CaseIterable, Identifiable {
    case fonti, stadi, generali

    var id: String { rawValue }

    var nome: String {
        switch self {
        case .fonti: "Sources"
        case .stadi: "Step"
        case .generali: "General rules"
        }
    }
}


enum EsitoRegola {
    static func segnale(_ esito: String) -> Segnale {
        if let s = Vocabolario.segnale("regola", esito) { return s }
        return switch esito {
        case "sì": Segnale(salute: .ok, simbolo: "checkmark.circle.fill", parola: "rispettata")
        case "in parte": Segnale(salute: .attenzione, simbolo: "circle.lefthalf.filled", parola: "in parte")
        case "no": Segnale(salute: .errore, simbolo: "xmark.circle.fill", parola: "non rispettata")
        default: Segnale(salute: .neutra, simbolo: Simbolo.nonMisurata, parola: "non verificata")
        }
    }


    static func daSistemare(_ r: RegolaDiOwner) -> Bool { r.rispettata == "no" || r.rispettata == "in parte" }
}

extension Quando {

    static func giorno(_ s: String) -> String {
        let pezzi = s.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard pezzi.count == 3, (1...12).contains(pezzi[1]) else { return s }
        let anno = Calendar.current.component(.year, from: Date())
        return "\(pezzi[2]) \(mesi[pezzi[1] - 1])" + (pezzi[0] == anno ? "" : " \(pezzi[0])")
    }


    static func tetto(_ secondi: Int) -> String {
        if secondi % 3600 == 0 { return secondi == 3600 ? "an hour" : "\(secondi / 3600) hours" }
        if secondi < 3600 { return "\(secondi / 60) minutes" }
        return durata(Double(secondi))
    }
}



struct PaginaRegole: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        PaginaScorrevole(stato: stato, titolo: "Rules", sottotitolo: "How it downloads each source and what each step does, with your rules and whether the code follows them",
                         vaiA: store.regolaVaiA) {
            if let r = store.regole {
                RiepilogoRegole(regole: r)
                Picker("View", selection: $store.vistaRegole) {
                    ForEach(VistaRegole.allCases) { v in Text(v.nome).tag(v) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 420)
                switch store.vistaRegole {
                case .fonti: ElencoRegoleFonti(regole: r, stato: stato)
                case .stadi: ElencoRegoleStadi(regole: r, stato: stato)
                case .generali: ElencoRegoleGenerali(regole: r)
                }
            } else if let errore = store.erroreRegole {
                Fascia(salute: .attenzione, testo: errore, dettaglio: nil) {
                    Button("Retry") { Task { await store.caricaRegole() } }
                }
            } else {
                HStack(spacing: Spazio.fratelli) {
                    ProgressView().controlSize(.small)
                    Text("Reading the rules…").foregroundStyle(.secondary)
                }
                .scheda()
            }
        }

        .task { await store.caricaRegole() }
    }
}


struct RiepilogoRegole: View {
    let regole: Regole
    @Environment(Store.self) private var store

    var body: some View {
        @Bindable var store = store
        let si = regole.conteggio["sì"] ?? 0, parte = regole.conteggio["in parte"] ?? 0, no = regole.conteggio["no"] ?? 0
        VStack(alignment: .leading, spacing: 12) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 28) { cifre(si, parte, no) }
                VStack(alignment: .leading, spacing: 10) { cifre(si, parte, no) }
            }
            Text(riga)
                .font(Testo.secondario)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            let senza = regole.senza_regole.fonti.count + regole.senza_regole.stadi.count
            if senza > 0 {
                Label(senza == 1 ? "One step or source does not have its rules written yet." : "\(senza) of the steps and sources do not have their rules written yet.",
                      systemImage: Simbolo.attenzione)
                    .font(Testo.secondario)
                    .foregroundStyle(Salute.attenzione.colore)
            }
            Toggle("Only the rules to fix", isOn: $store.soloDaSistemare)
                .toggleStyle(.switch)
                .controlSize(.small)
                .help("Shows only your rules that the code partly follows or does not follow, with the sources and steps that have them")
        }
        .scheda()
    }

    @ViewBuilder private func cifre(_ si: Int, _ parte: Int, _ no: Int) -> some View {
        Contatore(numero: si + parte + no, parola: "your rules about the software", segnale: nil)
        Contatore(numero: si, parola: "rispettate", segnale: EsitoRegola.segnale("sì"))
        Contatore(numero: parte, parola: "in parte", segnale: EsitoRegola.segnale("in parte"))
        Contatore(numero: no, parola: "non rispettate", segnale: EsitoRegola.segnale("no"))
    }

    private var riga: String {
        let quando = (regole.verificate.map { "Verified against the code on \(Quando.giorno($0))." } ?? "Verified against the code.")
            + (regole.ricontrollate.map { " The ones to fix, again on \(Quando.giorno($0))." } ?? "")
        return "\(quando) Timings, lanes and the runs each step runs in are read by the engine now, from the code. A rule is counted once for each source or step it touches."
    }
}

struct Contatore: View {
    let numero: Int
    let parola: String
    let segnale: Segnale?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            if let segnale {
                Image(systemName: segnale.simbolo).foregroundStyle(segnale.salute.colore)
            }
            Cifra(testo: "\(numero)", dimensione: 24)
            Text(parola).font(Testo.secondario).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}



struct ElencoRegoleFonti: View {
    let regole: Regole
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        let fonti = regole.fonti.filter { !store.soloDaSistemare || $0.regole_di_owner.contains(where: EsitoRegola.daSistemare) }
        let giro = fonti.filter { !$0.a_mano && $0.chiusa != true }, aMano = fonti.filter(\.a_mano)
        let chiuse = fonti.filter { $0.chiusa == true }
        if fonti.isEmpty {
            Text("No source has rules to fix.").foregroundStyle(.secondary).scheda()
        }
        if !giro.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "In the download cycle", conteggio: "\(giro.count)") {
                    Text("one after another, Drive last").font(.callout).foregroundStyle(.secondary)
                }
                ForEach(giro) { f in CartaRegoleFonte(fonte: f, stato: stato).id("fonte:\(f.id)") }
            }
        }
        if !aMano.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "By hand", conteggio: "\(aMano.count)") {
                    Text("you bring them, outside the cycle").font(.callout).foregroundStyle(.secondary)
                }
                ForEach(aMano) { f in CartaRegoleFonte(fonte: f, stato: stato).id("fonte:\(f.id)") }
            }
        }
        if !chiuse.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "Closed", conteggio: "\(chiuse.count)") {
                    Text("no longer downloaded, the archives remain").font(.callout).foregroundStyle(.secondary)
                }
                ForEach(chiuse) { f in CartaRegoleFonte(fonte: f, stato: stato).id("fonte:\(f.id)") }
            }
        }
    }
}

struct CartaRegoleFonte: View {
    let fonte: RegoleFonte
    let stato: Stato
    @Environment(Store.self) private var store

    private var chiave: String { "fonte:\(fonte.id)" }

    var body: some View {
        let aperta = store.regoleAperte.contains(chiave)
        VStack(alignment: .leading, spacing: 14) {
            TestaCarta(aperta: aperta, chiave: chiave, titolo: fonte.nome,
                       sotto: fonte.incrementale.isEmpty ? "" : "Only the new? " + primaFrase(fonte.incrementale),
                       conteggio: fonte.conteggio) {
                if let f = stato.fonti.first(where: { $0.id == fonte.id }) {
                    IconaFonte(fonte: f, lato: 32)
                } else {
                    TesseraIcona(simbolo: Simbolo.manuale, colore: .teal, lato: 32)
                }
            } distintivi: {
                if fonte.a_mano { Distintivo.aMano.help("You bring it: not downloaded in the full run.") }
                if fonte.leggera {
                    Distintivo(testo: "downloads even during a full run", simbolo: "arrow.down.circle", tinta: .blue)
                        .help("It is light, so you can download it on its own even while a full run is going, without waiting.")
                }
                if !fonte.corsia.isEmpty && fonte.corsia != "base" {
                    Distintivo(testo: "has its own lane", simbolo: "arrow.triangle.branch", tinta: .teal)
                        .help("In the full run it downloads alongside the other sources, in a lane of its own, if the Mac's memory allows. Otherwise it waits its turn.")
                }
                if let tetto = fonte.passi.map(\.tetto_s).max() {
                    Distintivo(testo: "up to \(Quando.tetto(tetto)) per attempt", simbolo: "timer")
                        .help("Each download attempt stops after \(Quando.tetto(tetto)). There are three attempts.")
                }
            }
            if aperta {
                CorpoRegoleFonte(fonte: fonte)
                    .transition(.opacity)
            }
        }
        .scheda()
    }
}

struct CorpoRegoleFonte: View {
    let fonte: RegoleFonte
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if !fonte.con_regole {
                Label("This source's rules are not written yet.", systemImage: Simbolo.attenzione)
                    .foregroundStyle(Salute.attenzione.colore)
            }
            if fonte.a_mano && !fonte.come_a_mano.isEmpty { Paragrafo(titolo: "How it enters", testo: fonte.come_a_mano) }
            if !fonte.cosa_scarica.isEmpty { Paragrafo(titolo: "What it downloads", testo: fonte.cosa_scarica) }
            if !fonte.incrementale.isEmpty { Paragrafo(titolo: "How it avoids re-downloading", testo: fonte.incrementale) }
            if !fonte.cosa_salta.isEmpty { Puntato(titolo: "What it skips", voci: fonte.cosa_salta) }
            if !fonte.limiti.isEmpty { Puntato(titolo: "Limits", voci: fonte.limiti) }
            RegoleDiOwner(regole: fonte.regole_di_owner)
            if !fonte.passi.isEmpty { Tabellina(titolo: "How it runs, read now from the code", voci: voci) }
            PerChiRipara {
                Elenco(titolo: "Where it writes", voci: fonte.dove_scrive)
                Elenco(titolo: fonte.passi.count > 1 ? "Commands" : "Command", voci: fonte.passi.map(\.comando))
                Elenco(titolo: "Errors the app recognizes", voci: fonte.errori)
                Elenco(titolo: "Tests in the code", voci: fonte.prove)
                if !fonte.note.isEmpty { Elenco(titolo: "Notes", voci: [fonte.note]) }
            }
        }
    }

    private var voci: [Voce] {
        var v: [Voce] = fonte.passi.map { p in
            Voce(etichetta: p.nome, valore: "up to \(Quando.tetto(p.tetto_s)), \(fonte.tentativi) attempts")
        }
        v.append(Voce(etichetta: "Lane", valore: fonte.corsia == "base" ? "with the other sources, in line" : "its own, alongside the others"))
        v.append(Voce(etichetta: "On its own during a full run", valore: fonte.leggera ? "yes" : "no, waits for it to finish"))
        if !fonte.natura.isEmpty { v.append(Voce(etichetta: "How it arrives", valore: fonte.natura)) }
        if let r = fonte.ritmo_giorni { v.append(Voce(etichetta: "Should be checked after", valore: r == 1 ? "one day" : "\(r) days")) }
        return v
    }
}



struct ElencoRegoleStadi: View {
    let regole: Regole
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        let stadi = regole.stadi.filter { !store.soloDaSistemare || $0.regole_di_owner.contains(where: EsitoRegola.daSistemare) }
        if stadi.isEmpty {
            Text("No step has rules to fix.").foregroundStyle(.secondary).scheda()
        }

        ForEach(stato.fasi) { fase in
            let dentro = stadi.filter { fase.stadi.contains($0.id) }
            if !dentro.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    TitoloGruppo(titolo: fase.nome, conteggio: "\(dentro.count)") {
                        Text(fase.etichetta).font(.callout).foregroundStyle(.secondary)
                    }
                    ForEach(dentro) { s in CartaRegoleStadio(stadio: s).id("stadio:\(s.id)") }
                }
            }
        }
        let fuori = stadi.filter { s in !stato.fasi.contains(where: { $0.stadi.contains(s.id) }) }
        if !fuori.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "Other steps", conteggio: "\(fuori.count)")
                ForEach(fuori) { s in CartaRegoleStadio(stadio: s).id("stadio:\(s.id)") }
            }
        }
    }
}

struct CartaRegoleStadio: View {
    let stadio: RegoleStadio
    @Environment(Store.self) private var store

    private var chiave: String { "stadio:\(stadio.id)" }

    var body: some View {
        let aperta = store.regoleAperte.contains(chiave)
        VStack(alignment: .leading, spacing: 14) {
            TestaCarta(aperta: aperta, chiave: chiave, titolo: stadio.nome,
                       sotto: stadio.frase.isEmpty ? primaFrase(stadio.cosa_fa) : stadio.frase, conteggio: stadio.conteggio) {
                Image(systemName: stadio.numero <= 50 ? "\(stadio.numero).circle.fill" : "circle.fill")
                    .font(.system(size: 26))
                    .foregroundStyle(stadio.pagato ? Color.purple : Color.secondary)
                    .frame(width: 32)
            } distintivi: {
                Etichetta(testo: stadio.strato)
                if stadio.pagato { Distintivo.aPagamento.help("Calls the model on a metered basis. It starts only with the Full run complete, when you choose it.") }
                if let tetto = stadio.tetto_s {
                    Distintivo(testo: "up to \(Quando.tetto(tetto))", simbolo: "timer")
                        .help("If it lasts more than \(Quando.tetto(tetto)) the step stops and retries.")
                }
            }
            if aperta {
                CorpoRegoleStadio(stadio: stadio)
                    .transition(.opacity)
            }
        }
        .scheda()
    }
}

struct CorpoRegoleStadio: View {
    let stadio: RegoleStadio
    @Environment(Store.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if stadio.fuori_ciclo {
                HStack(spacing: Spazio.fratelli) {
                    Text("The download has rules source by source.").foregroundStyle(.secondary)
                    Button("Go to sources") { store.vistaRegole = .fonti }
                        .buttonStyle(.link)
                }
            }
            if !stadio.con_regole {
                Label("This step's rules are not written yet.", systemImage: Simbolo.attenzione)
                    .foregroundStyle(Salute.attenzione.colore)
            }
            if !stadio.cosa_fa.isEmpty { Paragrafo(titolo: "What it does", testo: stadio.cosa_fa) }
            if !stadio.incrementale.isEmpty { Paragrafo(titolo: "Redoes everything or only the new", testo: stadio.incrementale) }
            if !stadio.memoria.isEmpty { Paragrafo(titolo: "Mac memory", testo: stadio.memoria) }
            if !stadio.se_fallisce.isEmpty { Paragrafo(titolo: "If it doesn't close", testo: stadio.se_fallisce) }
            if !stadio.dipende_da.isEmpty { Paragrafo(titolo: "What it depends on", testo: stadio.dipende_da) }
            if !stadio.chi_lo_usa.isEmpty { Paragrafo(titolo: "Who uses it", testo: stadio.chi_lo_usa) }
            if !stadio.spesa.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Label("How it spends", systemImage: Simbolo.aPagamento)
                        .font(Testo.secondario.weight(.semibold)).foregroundStyle(.purple)
                    ForEach(stadio.spesa, id: \.self) { v in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(v.voce).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                            Text(v.testo).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        }
                    }
                }
                .padding(10)
                .background(Color.purple.opacity(0.08), in: RoundedRectangle(cornerRadius: Raggio.piccolo))
            }
            RegoleDiOwner(regole: stadio.regole_di_owner)
            Tabellina(titolo: "How it runs, read now from the code", voci: voci)
            PerChiRipara {
                Elenco(titolo: "Script", voci: [stadio.script, stadio.argomenti].filter { !$0.isEmpty })
                Elenco(titolo: "Reads", voci: stadio.legge)
                Elenco(titolo: "Writes", voci: stadio.scrive)
                Elenco(titolo: "Tests in the code", voci: stadio.prove)
                if !stadio.note.isEmpty { Elenco(titolo: "Notes", voci: [stadio.note]) }
                Text("\(stadio.nome_tecnico) · \(stadio.id)").font(Testo.log).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
    }

    private var voci: [Voce] {
        var v = [Voce(etichetta: "Step", valore: "\(stadio.numero) of \(store.regole?.stadi.count ?? 0)")]
        v.append(Voce(etichetta: "Runs in", valore: stadio.perimetri.isEmpty ? "no re-read run" : stadio.perimetri.joined(separator: ", ")))
        if let t = stadio.tetto_s {
            v.append(Voce(etichetta: "Cap", valore: stadio.strato == "L1" ? "\(Quando.tetto(t)) per script, Drive more" : Quando.tetto(t)))
        }
        v.append(Voce(etichetta: "Paid", valore: stadio.pagato ? "yes, only with your spend confirmation" : "no"))
        return v
    }
}



struct ElencoRegoleGenerali: View {
    let regole: Regole
    @Environment(Store.self) private var store

    var body: some View {
        let elenco = regole.generali.filter { !store.soloDaSistemare || EsitoRegola.daSistemare($0) }
        if regole.generali.isEmpty {
            Text("The general rules are not written yet.").foregroundStyle(.secondary).scheda()
        } else if elenco.isEmpty {
            Text("No general rule to fix.").foregroundStyle(.secondary).scheda()
        } else {
            VStack(alignment: .leading, spacing: 10) {
                TitoloGruppo(titolo: "Apply to the whole pipeline", conteggio: "\(elenco.count)")
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(elenco.enumerated()), id: \.offset) { i, r in
                        if i > 0 { Separatore() }
                        RigaRegola(regola: r, grande: true)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)
                    }
                }
                .scheda(interno: 0)
            }
        }
    }
}




struct TestaCarta<Icona: View, Distintivi: View>: View {
    let aperta: Bool
    let chiave: String
    let titolo: String
    let sotto: String
    let conteggio: [String: Int]
    @ViewBuilder var icona: () -> Icona
    @ViewBuilder var distintivi: () -> Distintivi
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        Button {
            withAnimation(Movimento.cambio(ridotto)) {
                if aperta { store.regoleAperte.remove(chiave) } else { store.regoleAperte.insert(chiave) }
            }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .center, spacing: 12) {
                    icona()
                    VStack(alignment: .leading, spacing: 2) {
                        Text(titolo).font(.headline)
                        if !sotto.isEmpty {
                            Text(sotto).font(Testo.secondario).foregroundStyle(.secondary)
                                .lineLimit(aperta ? nil : 2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Spacer(minLength: Spazio.fratelli)
                    ContoRegole(conteggio: conteggio)
                    Image(systemName: "chevron.right")
                        .rotationEffect(.degrees(aperta ? 90 : 0))
                        .foregroundStyle(.secondary)
                }
                FlowDistintivi { distintivi() }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint(aperta ? "Closes the rules" : "Opens the rules")
    }
}


struct ContoRegole: View {
    let conteggio: [String: Int]

    var body: some View {
        HStack(spacing: 8) {
            ForEach(["sì", "in parte", "no"], id: \.self) { esito in
                let n = conteggio[esito] ?? 0
                if n > 0 {
                    let s = EsitoRegola.segnale(esito)
                    HStack(spacing: 3) {
                        Image(systemName: s.simbolo).foregroundStyle(s.salute.colore)
                        Text("\(n)").monospacedDigit()
                    }
                    .help("\(n) \(n == 1 ? "regola" : "regole") \(s.parola == "rispettata" ? (n == 1 ? "rispettata" : "rispettate") : (s.parola == "non rispettata" ? (n == 1 ? "non rispettata" : "non rispettate") : s.parola))")
                }
            }
        }
        .font(.subheadline)
    }
}


struct FlowDistintivi<Contenuto: View>: View {
    @ViewBuilder var contenuto: () -> Contenuto

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 6) { contenuto() }
            VStack(alignment: .leading, spacing: 4) { contenuto() }
        }
    }
}


struct RegoleDiOwner: View {
    let regole: [RegolaDiOwner]
    @Environment(Store.self) private var store

    var body: some View {
        let elenco = regole.filter { !store.soloDaSistemare || EsitoRegola.daSistemare($0) }
        if !elenco.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Your rules").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(elenco.enumerated()), id: \.offset) { i, r in
                        if i > 0 { Separatore() }
                        RigaRegola(regola: r, grande: false).padding(10)
                    }
                }
                .background(Superficie.riquadro, in: RoundedRectangle(cornerRadius: Raggio.piccolo))
            }
        }
    }
}

struct RigaRegola: View {
    let regola: RegolaDiOwner
    let grande: Bool
    @State private var prova = false

    var body: some View {
        let s = EsitoRegola.segnale(regola.rispettata)
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: s.simbolo).foregroundStyle(s.salute.colore).help(s.parola)
            VStack(alignment: .leading, spacing: 4) {
                Text(regola.regola)
                    .font(grande ? .body.weight(.semibold) : .body)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if !regola.perche.isEmpty {
                    Text(regola.perche).font(Testo.secondario).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 6) {
                    Text(s.parola.prima()).foregroundStyle(s.salute == .neutra ? Color.secondary : s.salute.colore)
                    if !regola.quando.isEmpty { Text("· since \(Quando.giorno(regola.quando))").foregroundStyle(.secondary) }
                    if !regola.prova.isEmpty || !regola.fonte.isEmpty {
                        Button(prova ? "Hide where it comes from" : "Where it comes from and the proof") { prova.toggle() }
                            .buttonStyle(.link)
                    }
                }
                .font(Testo.secondario)
                if prova {
                    VStack(alignment: .leading, spacing: 4) {
                        if !regola.fonte.isEmpty { Text(regola.fonte) }
                        if !regola.prova.isEmpty { Text(regola.prova).font(Testo.log) }
                        if !regola.dove_nel_codice.isEmpty { Text(regola.dove_nel_codice).font(Testo.log) }
                    }
                    .font(Testo.secondario)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
    }
}

struct Puntato: View {
    let titolo: String
    let voci: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(titolo).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(Array(voci.enumerated()), id: \.offset) { _, v in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("•").foregroundStyle(.secondary)
                    Text(v.prima()).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
            }
        }
    }
}


struct PerChiRipara<Contenuto: View>: View {
    @ViewBuilder var contenuto: () -> Contenuto

    var body: some View {
        DisclosureGroup("For whoever fixes it, files and tests") {
            VStack(alignment: .leading, spacing: 10) { contenuto() }
                .padding(.top, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(Testo.secondario)
    }
}

struct Elenco: View {
    let titolo: String
    let voci: [String]

    var body: some View {
        if !voci.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                Text(titolo).font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                ForEach(Array(voci.enumerated()), id: \.offset) { _, v in
                    Text(v).font(Testo.log).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }
        }
    }
}


func primaFrase(_ testo: String) -> String {
    guard let fine = testo.firstIndex(where: { ".!?".contains($0) }) else { return testo }
    return String(testo[...fine])
}




struct ComeLavoraFonte: View {
    let id: String
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            if let f = store.regole?.fonti.first(where: { $0.id == id }), f.con_regole {
                VStack(alignment: .leading, spacing: 6) {
                    Text("How it works").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    if !f.incrementale.isEmpty { Text(f.incrementale).fixedSize(horizontal: false, vertical: true) }
                    if !f.cosa_salta.isEmpty {
                        Text("Skips \(f.cosa_salta.prefix(3).joined(separator: ", "))\(f.cosa_salta.count > 3 ? " and more" : "").")
                            .font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    RigaVaiRegole(chiave: "fonte:\(f.id)", vista: .fonti, conteggio: f.conteggio)
                }
            }
        }
        .task { if store.regole == nil { await store.caricaRegole() } }
    }
}

struct ComeLavoraStadio: View {
    let id: String
    @Environment(Store.self) private var store

    var body: some View {
        Group {
            if let s = store.regole?.stadi.first(where: { $0.id == id }), s.con_regole {
                VStack(alignment: .leading, spacing: 6) {
                    Text("How it works").font(Testo.secondario.weight(.semibold)).foregroundStyle(.secondary)
                    if !s.incrementale.isEmpty { Text(s.incrementale).fixedSize(horizontal: false, vertical: true) }
                    if !s.se_fallisce.isEmpty {
                        Text(primaFrase(s.se_fallisce)).font(Testo.secondario).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    RigaVaiRegole(chiave: "stadio:\(s.id)", vista: .stadi, conteggio: s.conteggio)
                }
            }
        }
        .task { if store.regole == nil { await store.caricaRegole() } }
    }
}

struct RigaVaiRegole: View {
    let chiave: String
    let vista: VistaRegole
    let conteggio: [String: Int]
    @Environment(Store.self) private var store

    var body: some View {
        HStack(spacing: 8) {
            Button("All the rules") { store.apriRegola(chiave, vista: vista) }
                .buttonStyle(.link)
            ContoRegole(conteggio: conteggio)
        }
    }
}
