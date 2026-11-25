import AppKit
import SwiftUI









enum Salute: Sendable, CaseIterable {
    case ok
    case attenzione
    case errore
    case inCorso
    case neutra

    init(motore: String) {
        switch motore {
        case "ok": self = .ok
        case "attenzione": self = .attenzione
        case "errore": self = .errore
        case "in_corso": self = .inCorso
        default: self = .neutra
        }
    }

    var colore: Color {
        switch self {
        case .ok: .green
        case .attenzione: .orange
        case .errore: .red

        case .inCorso: .blue
        case .neutra: Color(nsColor: .secondaryLabelColor)
        }
    }


    var simbolo: String {
        switch self {
        case .ok: Simbolo.ok
        case .attenzione: Simbolo.attenzione
        case .errore: Simbolo.errore
        case .inCorso: Simbolo.inCorso
        case .neutra: Simbolo.mai
        }
    }


    var gravita: Int {
        switch self {
        case .errore: 4
        case .attenzione: 3
        case .inCorso: 2
        case .neutra: 1
        case .ok: 0
        }
    }
}



struct Segnale: Equatable, Sendable {
    let salute: Salute
    let simbolo: String
    let parola: String


    let aiuto: String?

    init(salute: Salute, simbolo: String? = nil, parola: String, aiuto: String? = nil) {
        self.salute = salute
        self.simbolo = simbolo ?? salute.simbolo
        self.parola = parola
        self.aiuto = aiuto?.isEmpty == true ? nil : aiuto
    }


    static func fonte(_ f: Fonte) -> Segnale {
        let salute = Salute(motore: f.salute)
        let aiuto = f.aiuto
        switch (f.gruppo, salute) {
        case ("chiuse", _): return Segnale(salute: .neutra, simbolo: Simbolo.chiusa, parola: f.parola, aiuto: aiuto)
        case ("da_collegare", _): return Segnale(salute: .neutra, simbolo: Simbolo.daCostruire, parola: f.parola, aiuto: aiuto)
        case ("a_mano", .neutra): return Segnale(salute: .neutra, simbolo: Simbolo.manuale, parola: f.parola, aiuto: aiuto)

        case (_, .neutra) where f.vuota == true:
            return Segnale(salute: .neutra, simbolo: "checkmark.circle", parola: f.parola, aiuto: aiuto)
        default: return Segnale(salute: salute, parola: f.parola, aiuto: aiuto)
        }
    }


    static func stadio(_ s: Stadio, breve: Bool = false) -> Segnale {
        let salute = Salute(motore: s.salute)
        let parola = breve ? (s.parola_breve ?? s.parola) : s.parola
        if s.pagato && salute == .neutra {
            return Segnale(salute: .neutra, simbolo: Simbolo.aPagamento, parola: parola, aiuto: s.aiuto)
        }


        if ["aspetta", "da_rileggere"].contains(s.stato ?? "") && salute == .neutra {
            return Segnale(salute: .neutra, simbolo: Simbolo.nonGira, parola: parola, aiuto: s.aiuto)
        }
        if s.ultimo.quando == nil && salute == .neutra {
            return Segnale(salute: .neutra, simbolo: Simbolo.mai, parola: parola, aiuto: s.aiuto)
        }
        return Segnale(salute: salute, parola: parola, aiuto: s.aiuto)
    }

    static func fase(_ f: Fase) -> Segnale {
        if f.pagata && f.salute != "in_corso" {
            return Segnale(salute: .neutra, simbolo: Simbolo.aPagamento, parola: f.frase, aiuto: f.aiuto)
        }
        let salute = Salute(motore: f.salute)
        if ["aspetta", "da_rileggere"].contains(f.stato ?? "") && salute == .neutra {
            return Segnale(salute: .neutra, simbolo: Simbolo.nonGira, parola: f.frase, aiuto: f.aiuto)
        }
        return Segnale(salute: salute, parola: f.frase, aiuto: f.aiuto)
    }



    static func run(_ r: Run) -> Segnale {

        if let s = Vocabolario.segnale("run", r.vivo ? "in_corso" : (r.esito ?? "sconosciuto")) { return s }
        if r.vivo { return Segnale(salute: .inCorso, parola: "running", aiuto: "Running now.") }
        switch r.esito {
        case "ok": return Segnale(salute: .ok, parola: "finished", aiuto: "Closed all its steps.")
        case "incompleto":
            return Segnale(salute: .attenzione, parola: "incomplete", aiuto: "Reached the end, but at least one step did not close.")
        case "fallito":
            return Segnale(salute: .errore, parola: "not finished", aiuto: "Stopped on an error, the later steps did not run.")
        case "fermato":
            return Segnale(salute: .neutra, simbolo: Simbolo.fermato, parola: "stopped by you", aiuto: "Stopped before the end with Stop.")
        case "interrotto":
            return Segnale(salute: .attenzione, parola: "interrupted", aiuto: "It was interrupted without saying how it ended, for example by a Mac restart. It must be redone.")
        case "non_partito":
            return Segnale(salute: .neutra, simbolo: Simbolo.fermato, parola: "did not start", aiuto: "It did not start, another run was already going.")
        default: return Segnale(salute: .neutra, simbolo: Simbolo.nonMisurata, parola: "unknown outcome")
        }
    }

    static func passo(_ stato: String) -> Segnale {
        if let s = Vocabolario.segnale("passo", stato) ?? (["fatto", "in_corso", "ritento", "fallito", "saltato", "interrotto"]
            .contains(stato) ? nil : Vocabolario.segnale("passo", "da_fare")) { return s }
        return switch stato {
        case "fatto": Segnale(salute: .ok, parola: "done", aiuto: "The step closed cleanly.")
        case "in_corso": Segnale(salute: .inCorso, parola: "running", aiuto: "Running now.")
        case "ritento": Segnale(salute: .attenzione, parola: "retrying", aiuto: "It did not close, and retries on its own. There are three attempts.")
        case "fallito": Segnale(salute: .errore, parola: "not closed", aiuto: "It did not close even on the last attempt. The run continues with the others.")
        case "saltato":
            Segnale(salute: .neutra, simbolo: Simbolo.saltato, parola: "outside this run",
                    aiuto: "It did not run in this run, because nothing had changed or because it is not part of it.")
        case "interrotto": Segnale(salute: .attenzione, parola: "interrupted", aiuto: "It stopped halfway, it must be redone.")
        default: Segnale(salute: .neutra, simbolo: Simbolo.mai, parola: "to do", aiuto: "It has not started yet.")
        }
    }
}




struct SegnaleView: View {
    let segnale: Segnale

    var compatto = false

    @Environment(\.backgroundProminence) private var prominenza
    @Environment(\.accessibilityDifferentiateWithoutColor) private var senzaColore

    var body: some View {
        HStack(spacing: Spazio.simboloTesto) {
            simbolo
            if !compatto || senzaColore {
                Text(segnale.parola)
            }
        }
        .help(segnale.aiuto ?? segnale.parola)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(segnale.parola)
    }

    @ViewBuilder private var simbolo: some View {
        if segnale.salute == .inCorso {

            ProgressView().controlSize(.small).frame(width: Spazio.colonnaSimbolo)
        } else {
            Image(systemName: segnale.simbolo)
                .symbolRenderingMode(.monochrome)

                .foregroundStyle(prominenza == .increased ? AnyShapeStyle(.primary) : AnyShapeStyle(segnale.salute.colore))

                .frame(width: Spazio.colonnaSimbolo)
        }
    }
}


struct Distintivo: View {
    let testo: String
    let simbolo: String
    var tinta: Color = Color(nsColor: .secondaryLabelColor)

    var body: some View {
        HStack(spacing: Spazio.simboloTesto) {
            Image(systemName: simbolo).foregroundStyle(tinta)
            Text(testo).foregroundStyle(.primary)
        }
        .font(Testo.distintivo)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(tinta.opacity(0.12), in: Capsule())
        .accessibilityElement(children: .combine)
    }

    static let aPagamento = Distintivo(testo: "paid", simbolo: Simbolo.aPagamento, tinta: .purple)
    static let aMano = Distintivo(testo: "manual", simbolo: Simbolo.manuale)
}


struct Etichetta: View {
    let testo: String


    static let aiuto = "The technical name of the phase. L0 is the download, L1 the reading, L2 the merge and the knowledge, L3 the texts, the graph and the indices, RQ the relationships."

    var body: some View {
        Text(testo)
            .font(Testo.minimo.monospaced())
            .foregroundStyle(.secondary)
            .padding(.horizontal, 4)
            .padding(.vertical, 1)
            .overlay(RoundedRectangle(cornerRadius: 3).stroke(Superficie.separatore))
    }
}


struct RigaLog: View {
    let testo: String

    private var salute: Salute? {
        if testo.contains("ERROR") || testo.contains("⛔") || testo.contains("FAILED") { return .errore }
        if testo.contains("WARNING") || testo.contains("⚠️") { return .attenzione }
        return nil
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spazio.fratelli) {
            Image(systemName: "circle.fill")
                .imageScale(.small)
                .foregroundStyle(salute?.colore ?? .clear)
                .accessibilityHidden(salute == nil)
            Text(testo.isEmpty ? " " : testo)
                .font(Testo.log)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 1)
        .background(salute == .errore ? Salute.errore.colore.opacity(0.12) : .clear)
    }
}

extension View {

    func riquadro() -> some View {
        padding(Spazio.interno)
            .background(Superficie.riquadro, in: Forma.riquadro)
    }
}



enum Testo {

    static let verdetto = Font.title2.weight(.semibold)

    static let titoloSezione = Font.title3.weight(.semibold)

    static let titoloGruppo = Font.headline
    static let corpo = Font.body

    static let nome = Font.body.weight(.semibold)

    static let secondario = Font.subheadline

    static let cifreInColonna = Font.body.monospacedDigit()
    static let distintivo = Font.subheadline.weight(.medium)

    static let log = Font.system(.callout, design: .monospaced)

    static let minimo = Font.caption
}

enum Spazio {
    static let colonnaSimbolo: CGFloat = 18
    static let simboloTesto: CGFloat = 4
    static let righeTesto: CGFloat = 2
    static let fratelli: CGFloat = 8
    static let interno: CGFloat = 12
    static let griglia: CGFloat = 16

    static let margine: CGFloat = 20
    static let sezioni: CGFloat = 24
}

enum Raggio {
    static let riquadro: CGFloat = 12
    static let piccolo: CGFloat = 6
}

enum Forma {

    static var riquadro: ConcentricRectangle {
        ConcentricRectangle(corners: .concentric(minimum: .fixed(Raggio.riquadro)), isUniform: true)
    }
}

enum Superficie {
    static let riquadro = Color(nsColor: .quaternarySystemFill)
    static let riquadroPremuto = Color(nsColor: .tertiarySystemFill)
    static let separatore = Color(nsColor: .separatorColor)
    static let selezione = Color.accentColor.opacity(0.18)
}



enum Movimento {
    static func cambio(_ ridotto: Bool) -> Animation { ridotto ? .easeInOut(duration: 0.15) : .smooth(duration: 0.2) }
    static func ingresso(_ ridotto: Bool) -> Animation { ridotto ? .easeInOut(duration: 0.15) : .smooth(duration: 0.3) }
    static let avanzamento = Animation.linear(duration: 0.5)
}




enum Vocabolario {
    nonisolated(unsafe) static var voci: [String: [String: VoceStato]] = [:]

    static func segnale(_ gruppo: String, _ stato: String) -> Segnale? {
        guard let v = voci[gruppo]?[stato] else { return nil }
        let salute = Salute(motore: v.salute ?? "neutra")
        return Segnale(salute: salute, simbolo: Simbolo.da(v.simbolo), parola: v.parola, aiuto: v.aiuto)
    }

    static func parola(_ gruppo: String, _ stato: String) -> String? { voci[gruppo]?[stato]?.parola }
}

enum Simbolo {


    static func da(_ nome: String?) -> String? {
        switch nome {
        case "fatto", "spunta": "checkmark.circle.fill"
        case "fermato": fermato
        case "saltato": saltato
        case "mai": mai
        case "non_misurata": nonMisurata
        case "non_gira": nonGira
        case "a_pagamento": aPagamento
        case "manuale": manuale
        case "in_parte": "circle.lefthalf.filled"
        case "no": "xmark.circle.fill"

        case "pallino": nonGira
        case "attenzione": attenzione
        case "in_corso": inCorso
        default: nil
        }
    }

    static let ok = "circle.fill"
    static let attenzione = "exclamationmark.triangle.fill"
    static let datoVecchio = "clock.badge.exclamationmark.fill"


    static let nonGira = "circle.fill"
    static let errore = "xmark.octagon.fill"
    static let inCorso = "progress.indicator"
    static let fermato = "stop.circle"
    static let mai = "circle.dashed"
    static let saltato = "minus.circle"
    static let nonMisurata = "questionmark.circle.dashed"
    static let chiusa = "archivebox"
    static let daCostruire = "hammer"
    static let manuale = "hand.point.up.left"
    static let aPagamento = "creditcard"
    static let terminale = "apple.terminal"
    static let fullRun = "play.fill"

    static let completa = "sparkles"
    static let ferma = "stop.fill"
    static let scarica = "arrow.down.circle"
    static let aggiorna = "arrow.clockwise"
    static let log = "text.alignleft"
    static let mostraNelFinder = "folder"
    static let copia = "document.on.document"
    static let ispettore = "sidebar.right"
    static let pannello = "rectangle.bottomthird.inset.filled"
    static let memoria = "memorychip"
    static let coperchio = "laptopcomputer"
    static let batteria = "battery.50percent"
}
