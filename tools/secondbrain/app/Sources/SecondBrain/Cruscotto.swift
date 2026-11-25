import AppKit
import SwiftUI








struct BarraProgresso: View {
    let frazione: Double
    var colore: Color = Salute.inCorso.colore
    var altezza: CGFloat = 10
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Superficie.traccia)
                Capsule()
                    .fill(LinearGradient(colors: [colore.opacity(0.75), colore], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(altezza, g.size.width * min(1, max(0, frazione))))
                    .animation(ridotto ? nil : .smooth(duration: 0.6), value: frazione)
            }
        }
        .frame(height: altezza)
        .accessibilityElement()
        .accessibilityLabel("Progress")
        .accessibilityValue("\(Int((frazione * 100).rounded())) percent")
    }
}


struct AnelloPercentuale: View {
    let frazione: Double
    var colore: Color = Salute.inCorso.colore
    var lato: CGFloat = 76

    var passi: (Int, Int)?

    var body: some View {
        Anello(frazione: frazione, colore: colore, lato: lato, spessore: lato * 0.11) {
            VStack(spacing: 0) {
                Text(passi.map { "\($0.0)/\($0.1)" } ?? "\(Int((frazione * 100).rounded()))")
                    .font(.system(size: lato * (passi == nil ? 0.3 : 0.22), weight: .bold, design: .rounded).monospacedDigit())
                    .contentTransition(.numericText())
                Text(passi == nil ? "%" : "step").font(.system(size: lato * 0.14, weight: .semibold)).foregroundStyle(.secondary)
            }
        }
    }
}




struct LetturaRun {
    let av: Avanzamento

    static let chiusi: Set<String> = ["fatto", "fallito", "saltato", "interrotto"]

    var passiScarico: [PassoRun] { av.passi.filter { $0.sorgente != nil } }
    var copia: PassoRun? { av.passi.first { $0.id == "backup-kb" } }
    var rilettura: PassoRun? { av.passi.first { $0.id == "ingest" || $0.id == "tutto" } }

    var fatti: Int { av.passi.filter { Self.chiusi.contains($0.stato) }.count }
    var totale: Int { max(1, av.passi.count) }



    var sulTempo: Bool { av.previsione?.frazione_tempo != nil }


    var frazione: Double {
        if let f = av.previsione?.frazione_tempo { return f }
        guard av.tipo == "giro" else {
            return Double(av.passi.filter { Self.chiusi.contains($0.stato) }.count) / Double(max(1, av.passi.count))
        }
        var base = Double(fatti)
        if let dentro = av.dentro?.first, let r = rilettura, r.stato == "in_corso" {
            let f = Double(dentro.passi.filter { Self.chiusi.contains($0.stato) }.count) / Double(max(1, dentro.passi.count))
            base += f
        }
        return base / Double(totale)
    }

    enum Tappa: Int, CaseIterable {
        case scarico, copia, rilettura

        var nome: String {
            switch self {
            case .scarico: "Source download"
            case .copia: "Brain copy"
            case .rilettura: "Re-read"
            }
        }

        var simbolo: String {
            switch self {
            case .scarico: "arrow.down.circle.fill"
            case .copia: "externaldrive.fill.badge.checkmark"
            case .rilettura: "brain.head.profile"
            }
        }
    }

    func stato(_ tappa: Tappa) -> String {
        let passi: [PassoRun] = switch tappa {
        case .scarico: passiScarico
        case .copia: copia.map { [$0] } ?? []
        case .rilettura: rilettura.map { [$0] } ?? []
        }
        if passi.isEmpty { return "assente" }
        if passi.contains(where: { $0.stato == "in_corso" || $0.stato == "ritento" }) { return "in_corso" }
        if passi.allSatisfy({ Self.chiusi.contains($0.stato) }) {
            return passi.contains(where: { $0.stato == "fallito" }) ? "con_problemi" : "fatto"
        }
        return "da_fare"
    }

    var tappaAttuale: Tappa? { Tappa.allCases.first { stato($0) == "in_corso" } }
}


struct SchedaAvanzamento: View {
    let av: Avanzamento
    let inizio: String?
    var compatta = false

    var body: some View {
        let l = LetturaRun(av: av)
        HStack(alignment: .center, spacing: 20) {
            AnelloPercentuale(frazione: l.frazione, lato: compatta ? 60 : 84, passi: l.sulTempo ? nil : (l.fatti, av.passi.count))
                .help(l.sulTempo ? "The part done against the expected time." : "Without a complete forecast it counts closed steps, not time.")
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(l.fatti) of \(av.passi.count) steps")
                        .font(.title3.weight(.semibold).monospacedDigit())
                    if let t = l.tappaAttuale {
                        Text("· \(t.nome)").font(.title3).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let inizio, let d = Quando.data(inizio) {
                        Text("for \(Quando.durata(Date().timeIntervalSince(d)))")
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                BarraProgresso(frazione: l.frazione, altezza: compatta ? 8 : 12)
                RigaPrevisione(previsione: av.previsione)
            }
        }
    }
}


struct RigaPrevisione: View {
    let previsione: Previsione?

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "clock").foregroundStyle(.secondary)
            Text(testo).fixedSize(horizontal: false, vertical: true)
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .help(previsione?.come.map { "Estimate \($0). It is what usually happens, not a promise." } ?? "")
    }

    private var testo: String {
        guard let p = previsione else { return "The forecast arrives once the run has written its first steps." }
        if let fine = p.fine_prevista {
            return "Usually finishes around \(Quando.frase(fine).replacingOccurrences(of: "alle", with: "le")), in about \(Quando.durata(p.restano_s))."
                + perFase(p)
        }

        if let frase = p.frase, !frase.isEmpty { return frase }
        var pezzi: [String] = []
        if let mancano = p.senza_stima, !mancano.isEmpty {
            pezzi.append("End not predictable, \(mancano.joined(separator: " and ")) does not yet have a measured duration.")
        }
        if let s = p.scarico_s { pezzi.append("The download has about \(Quando.durata(s)) left.") }
        if let r = p.rilettura_s { pezzi.append("The re-read usually takes \(Quando.durata(r)).") }
        return pezzi.joined(separator: " ") + perFase(p)
    }


    private func perFase(_ p: Previsione) -> String {
        let fasi = (p.fasi ?? []).compactMap { f -> String? in
            guard let s = f.restano_s, s >= 60 else { return nil }
            return "\(f.fase) \(Quando.durata(s))"
        }
        guard !fasi.isEmpty else { return "" }
        let elenco = fasi.count > 1 ? fasi.dropLast().joined(separator: ", ") + " and " + (fasi.last ?? "") : fasi[0]
        return " \(elenco) left."
    }
}


struct PercorsoRun: View {
    let av: Avanzamento

    var body: some View {
        let l = LetturaRun(av: av)
        let tappe = LetturaRun.Tappa.allCases.filter { l.stato($0) != "assente" }
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(tappe.enumerated()), id: \.element) { i, t in
                VStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .fill(colore(l.stato(t)).opacity(l.stato(t) == "da_fare" ? 0.12 : 0.9))
                            .frame(width: 40, height: 40)
                        if l.stato(t) == "in_corso" {
                            Circle().stroke(colore("in_corso").opacity(0.35), lineWidth: 6).frame(width: 52, height: 52)
                        }
                        Image(systemName: l.stato(t) == "fatto" ? "checkmark" : t.simbolo)
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(l.stato(t) == "da_fare" ? AnyShapeStyle(.secondary) : AnyShapeStyle(.white))
                    }
                    .frame(height: 54)
                    .help("\(t.nome), \(parola(l.stato(t))). A full run goes through these stages in a row.")
                    Text(t.nome).font(.callout.weight(.semibold)).multilineTextAlignment(.center)
                    Text(parola(l.stato(t))).font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .overlay(alignment: .top) {
                    if l.stato(t) == "in_corso" {
                        Text("you are here")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(colore("in_corso"), in: Capsule())
                            .foregroundStyle(.white)
                            .offset(y: -16)
                    }
                }
                if i < tappe.count - 1 {
                    Rectangle()
                        .fill(l.stato(t) == "fatto" ? Salute.ok.colore.opacity(0.6) : Superficie.traccia)
                        .frame(height: 3)
                        .frame(maxWidth: 80)
                        .padding(.top, 25)
                }
            }
        }
        .padding(.top, 14)
        .accessibilityElement(children: .combine)
    }

    private func colore(_ stato: String) -> Color {
        switch stato {
        case "fatto": Salute.ok.colore
        case "in_corso": Salute.inCorso.colore
        case "con_problemi": Salute.attenzione.colore
        default: Color(nsColor: .systemGray)
        }
    }

    private func parola(_ stato: String) -> String {
        switch stato {
        case "fatto": "done"
        case "in_corso": "now"
        case "con_problemi": "with unclosed steps"
        default: "later"
        }
    }
}


struct SchedaCorsie: View {
    let av: Avanzamento

    var body: some View {
        if let corsie = av.corsie, !corsie.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Download lanes").font(.headline)
                    Text("\(corsie.count) together").font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    if let fuori = av.corsie_non_partite, !fuori.isEmpty {
                        Text("queued in the base: \(fuori.map(Self.nome).joined(separator: ", "))")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                ForEach(corsie) { c in
                    HStack(spacing: 12) {
                        TesseraIcona(simbolo: Self.simbolo(c.nome), colore: Self.colore(c.nome), lato: 26)
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(Self.nome(c.nome)).font(.callout.weight(.semibold))
                                Spacer()
                                Text("\(c.fatti) of \(c.totale)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            BarraProgresso(frazione: Double(c.fatti) / Double(max(1, c.totale)), colore: Self.colore(c.nome), altezza: 7)
                            Text(riga(c)).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
            }
            .scheda(interno: 16)
        }
    }

    private func riga(_ c: CorsiaRun) -> String {
        guard let id = c.corrente else { return c.fatti >= c.totale ? "finished" : "waiting" }
        let nome = av.passi.first { $0.id == id }?.nome ?? id
        let dalle = av.correnti?.first { $0.id == id }?.dalle
        return "now \(nome)" + (dalle.map { ", from \($0.suffix(8).prefix(5))" } ?? "")
    }

    static func nome(_ corsia: String) -> String {
        ["base": "Base", "slack": "Slack", "clickup": "ClickUp", "drive": "Google Drive"][corsia] ?? corsia.capitalized
    }

    static func simbolo(_ corsia: String) -> String {
        ["base": "square.stack.fill", "slack": "number", "clickup": "checklist", "drive": "folder.fill"][corsia] ?? "arrow.down"
    }

    static func colore(_ corsia: String) -> Color {
        ["base": Color.blue, "slack": Color.purple, "clickup": Color.indigo, "drive": Color.yellow][corsia] ?? .blue
    }
}
