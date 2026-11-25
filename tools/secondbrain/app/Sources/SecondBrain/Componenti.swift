import AppKit
import SwiftUI













enum TintaPriorita {
    private static func c(_ esa: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((esa >> 16) & 0xff) / 255, green: CGFloat((esa >> 8) & 0xff) / 255, blue: CGFloat(esa & 0xff) / 255, alpha: 1)
    }

    private static let fondi: [(UInt32, UInt32)] = [(0xFDE0DC, 0x5C2B27), (0xFCE5D2, 0x59391D), (0xFAEFC9, 0x4F4420), (0xECECEA, 0x3D3D3C)]
    private static let testi: [(UInt32, UInt32, UInt32, UInt32)] = [
        (0xA8231B, 0xFFB3AA, 0x7E1610, 0xFFD3CD), (0x94450C, 0xFFC285, 0x6E3208, 0xFFDAB3),
        (0x735400, 0xF0CF73, 0x553E00, 0xFBE3A6), (0x5C5B57, 0xC9C8C4, 0x3E3D3A, 0xE6E5E2),
    ]
    private static func i(_ p: Int) -> Int { min(max(p, 0), 3) }

    static func fondo(_ p: Int) -> Color {
        let f = fondi[i(p)]
        return Color.dinamico(chiaro: c(f.0), scuro: c(f.1))
    }

    static func testo(_ p: Int) -> Color {
        let t = testi[i(p)]
        return Color.dinamico(chiaro: c(t.0), scuro: c(t.1), chiaroForte: c(t.2), scuroForte: c(t.3))
    }
}

extension Color {

    static func dinamico(chiaro: NSColor, scuro: NSColor, chiaroForte: NSColor? = nil,
                         scuroForte: NSColor? = nil) -> Color {
        Color(nsColor: NSColor(name: nil) { aspetto in
            switch aspetto.bestMatch(from: [.aqua, .darkAqua, .accessibilityHighContrastAqua,
                                            .accessibilityHighContrastDarkAqua]) {
            case .darkAqua: scuro
            case .accessibilityHighContrastDarkAqua: scuroForte ?? scuro
            case .accessibilityHighContrastAqua: chiaroForte ?? chiaro
            default: chiaro
            }
        })
    }
}

extension Superficie {

    static let pagina = Color.dinamico(chiaro: NSColor(white: 0.962, alpha: 1), scuro: NSColor(white: 0.112, alpha: 1))
    static let scheda = Color.dinamico(chiaro: .white, scuro: NSColor(white: 0.168, alpha: 1))

    static let incasso = Color.dinamico(chiaro: NSColor(white: 0.955, alpha: 1), scuro: NSColor(white: 0.135, alpha: 1))
    static let bordo = Color.dinamico(chiaro: NSColor(white: 0, alpha: 0.07), scuro: NSColor(white: 1, alpha: 0.08),
                                      chiaroForte: NSColor(white: 0, alpha: 0.35), scuroForte: NSColor(white: 1, alpha: 0.4))
    static let traccia = Color.dinamico(chiaro: NSColor(white: 0, alpha: 0.07), scuro: NSColor(white: 1, alpha: 0.1))
}

extension Raggio {
    static let scheda: CGFloat = 14
}



struct Scheda: ViewModifier {
    var interno: CGFloat = 16

    var tinta: Color?
    @Environment(\.colorScheme) private var schema

    func body(content: Content) -> some View {
        content
            .padding(interno)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                let forma = RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous)
                forma.fill(Superficie.scheda)
                    .overlay {
                        if let tinta {
                            forma.fill(LinearGradient(colors: [tinta.opacity(schema == .dark ? 0.22 : 0.13), tinta.opacity(0)],
                                                      startPoint: .topLeading, endPoint: .bottomTrailing))
                        }
                    }
                    .overlay(forma.strokeBorder(Superficie.bordo, lineWidth: 1))
                    .shadow(color: .black.opacity(schema == .dark ? 0 : 0.05), radius: 10, y: 3)
            }
    }
}

extension View {
    func scheda(interno: CGFloat = 16, tinta: Color? = nil) -> some View {
        modifier(Scheda(interno: interno, tinta: tinta))
    }
}




struct TesseraIcona: View {
    let simbolo: String
    let colore: Color
    var lato: CGFloat = 28

    var body: some View {
        Image(systemName: simbolo)
            .font(.system(size: lato * 0.48, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: lato, height: lato)
            .background(colore.gradient, in: RoundedRectangle(cornerRadius: lato * 0.27, style: .continuous))
            .accessibilityHidden(true)
    }
}


struct Anello<Centro: View>: View {
    let frazione: Double
    let colore: Color
    var lato: CGFloat = 52
    var spessore: CGFloat = 6
    @ViewBuilder var centro: () -> Centro

    var body: some View {
        ZStack {
            Circle().stroke(colore.opacity(0.22), lineWidth: spessore)

            if frazione > 0.001 {
                Circle()
                    .trim(from: 0, to: min(1, frazione))
                    .stroke(colore.gradient, style: StrokeStyle(lineWidth: spessore, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            centro()
        }
        .frame(width: lato, height: lato)
    }
}


struct Pillola: View {
    let segnale: Segnale

    var body: some View {
        HStack(spacing: 4) {
            if segnale.salute == .inCorso {
                ProgressView().controlSize(.mini)
            } else {
                Image(systemName: segnale.simbolo)
                    .foregroundStyle(segnale.salute.colore)
            }
            Text(segnale.parola).lineLimit(1)
        }
        .font(.subheadline.weight(.medium))
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(segnale.salute.colore.opacity(segnale.salute == .neutra ? 0.10 : 0.14), in: Capsule())
        .help(segnale.aiuto ?? segnale.parola)
        .accessibilityElement(children: .combine)
    }
}




struct SecondaConferma: ViewModifier {
    @Binding var mostra: Bool
    let titolo: String
    let messaggio: String
    let pulsante: String
    let azione: () -> Void

    func body(content: Content) -> some View {
        content.alert(titolo, isPresented: $mostra) {
            Button("Annulla", role: .cancel) {}
                .keyboardShortcut(.defaultAction)
            Button(pulsante) { azione() }
        } message: {
            Text(messaggio)
        }
    }
}

extension View {
    func secondaConferma(_ mostra: Binding<Bool>, titolo: String, messaggio: String, pulsante: String,
                         azione: @escaping () -> Void) -> some View {
        modifier(SecondaConferma(mostra: mostra, titolo: titolo, messaggio: messaggio, pulsante: pulsante, azione: azione))
    }
}


struct BarraEta: View {
    let frazione: Double
    let colore: Color

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Superficie.traccia)
                Capsule().fill(colore.gradient)
                    .frame(width: max(5, g.size.width * min(1, max(0, frazione))))
            }
        }
        .frame(height: 5)
        .accessibilityHidden(true)
    }
}


struct TitoloPagina: View {
    let titolo: String
    let sottotitolo: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(titolo).font(.system(size: 26, weight: .bold))
            if !sottotitolo.isEmpty {
                Text(sottotitolo).font(.callout).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityAddTraits(.isHeader)
    }
}


struct TitoloGruppo<Coda: View>: View {
    let titolo: String
    var conteggio: String = ""
    @ViewBuilder var coda: () -> Coda

    var body: some View {

        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                testa
                Spacer(minLength: Spazio.fratelli)
                coda()
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 6) { testa }
                HStack(spacing: Spazio.fratelli) { coda() }
            }
        }
        .accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder private var testa: some View {
        Text(titolo).font(.title3.weight(.semibold))
        if !conteggio.isEmpty {
            Text(conteggio).font(.callout).foregroundStyle(.secondary).monospacedDigit()
        }
    }
}

extension TitoloGruppo where Coda == EmptyView {
    init(titolo: String, conteggio: String = "") {
        self.init(titolo: titolo, conteggio: conteggio) { EmptyView() }
    }
}


struct Cifra: View {
    let testo: String
    var dimensione: CGFloat = 26

    var body: some View {
        Text(testo)
            .font(.system(size: dimensione, weight: .semibold, design: .rounded).monospacedDigit())
            .contentTransition(.numericText())
            .lineLimit(1)
            .minimumScaleFactor(0.6)
    }
}



extension IconaFonte {
    static func simbolo(_ fonte: Fonte) -> String {
        switch fonte.id {
        case "email": "envelope.fill"
        case "calendar": "calendar"
        case "slack": "number"
        case "whatsapp": "bubble.left.fill"
        case "attio": "person.text.rectangle"
        case "gdrive": "folder.fill"
        case "plaud": "waveform"
        case "tactiq": "captions.bubble"
        case "notion": "doc.text"
        case "whoop": "heart.fill"
        case "voicememos": "mic.fill"
        case "linkedin": "person.2.fill"
        case "clickup": "checklist"
        case "personio": "person.crop.circle"
        case "docusign": "signature"
        case "github": "chevron.left.forwardslash.chevron.right"
        case "gsc": "magnifyingglass"
        case "analytics": "chart.bar.fill"
        default: fonte.gruppo == "da_collegare" ? Simbolo.daCostruire : Simbolo.chiusa
        }
    }


    static func colore(_ fonte: Fonte) -> Color {
        if ["chiuse", "da_collegare"].contains(fonte.gruppo) { return Color(nsColor: .systemGray) }
        switch fonte.id {
        case "email": return .blue
        case "calendar": return .red
        case "slack": return .purple
        case "whatsapp": return .green
        case "attio", "clickup": return .indigo
        case "gdrive", "docusign": return .yellow
        case "plaud", "tactiq", "voicememos": return .orange
        case "notion", "github": return Color(nsColor: .darkGray)
        case "whoop": return .pink
        case "linkedin": return .cyan
        case "personio": return .teal
        case "gsc", "analytics": return .mint
        default: return fonte.gruppo == "a_mano" ? .teal : .blue
        }
    }
}

enum IconaFase {
    static func simbolo(_ id: String) -> String {
        switch id {
        case "scarico": "arrow.down.circle.fill"
        case "lettura": "doc.text.magnifyingglass"
        case "unione": "person.2.circle.fill"
        case "estrazione": "sparkles"
        case "conoscenza": "brain.head.profile"
        case "relazioni": "point.3.connected.trianglepath.dotted"
        case "grafo": "square.stack.3d.up.fill"
        default: "circle.fill"
        }
    }
}
