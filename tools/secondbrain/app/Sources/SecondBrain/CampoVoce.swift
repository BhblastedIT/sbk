import AppKit
import SwiftUI












struct CampoVoce: View {
    @Binding var testo: String
    let segnaposto: String

    let voce: String
    let chiave: String

    let cosa: String
    let cartella: String
    let cartellaRegistro: String
    let testi: (String) -> String

    let mandaTesto: (String) async -> Bool
    let mandaAudio: (Registrazione) async -> Void
    var spento = false

    var fintoSecondi: Int?

    var fuocoSubito = false
    var righe = 1...5

    @State private var invio = false
    @State private var tenuto = false
    @State private var premuto = false
    @State private var attesa: Task<Void, Never>?
    @FocusState private var attivo: Bool
    @Environment(\.accessibilityReduceMotion) private var ridotto
    private var reg: Registratore { Registratore.condiviso }

    private var mia: Bool { reg.e(voce, chiave) }
    private var ascolta: Bool { fintoSecondi != nil || (mia && reg.stato == .registra) }
    private var altrove: Bool { reg.occupato && !mia }

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            microfono
            if ascolta {
                ascolto
            } else if mia && reg.stato == .chiedo {
                riga(testi("chiedo_microfono"), rotella: true)
            } else if mia && reg.stato == .invio {
                riga(testi("invio_dettato"), rotella: true)
            } else if mia, reg.stato == .annullata || reg.stato == .corta, let d = reg.daParte {
                daParte(d)
            } else {
                campo
            }
        }

        .onExitCommand {
            if ascolta, fintoSecondi == nil { reg.annulla() }
            else if StatoConversazione.condiviso.aperta { StatoConversazione.condiviso.aperta = false }
        }
        .animation(ridotto ? nil : .smooth(duration: 0.2), value: ascolta)
    }






    private var microfono: some View {
        let acceso = ascolta
        return Image(systemName: acceso ? "mic.fill" : "mic")
            .font(.system(size: 14, weight: .medium))

            .foregroundStyle(acceso ? Color.white : (altrove || spento ? Color.secondary : Color.primary))
            .symbolEffect(.pulse, options: .repeating, isActive: acceso && !ridotto)
            .frame(width: 30, height: 30)
            .background(acceso ? Color.red : (premuto ? Superficie.riquadroPremuto : Superficie.riquadro), in: Circle())
            .scaleEffect(premuto && !ridotto ? 0.92 : 1)
            .animation(ridotto ? nil : .smooth(duration: 0.15), value: premuto)
            .contentShape(Circle())


            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !premuto else { return }
                    premuto = true
                    attesa?.cancel()
                    attesa = Task { @MainActor in
                        try? await Task.sleep(nanoseconds: 350_000_000)
                        guard !Task.isCancelled, premuto, !ascolta, !altrove, !spento, fintoSecondi == nil else { return }
                        tenuto = true
                        await comincia(tenendo: true)
                    }
                }
                .onEnded { _ in
                    premuto = false
                    attesa?.cancel()
                    attesa = nil
                    if tenuto {
                        tenuto = false
                        fermaEManda()
                    } else {
                        clic()
                    }
                })
            .help(altrove ? testi("microfono_occupato") : (acceso ? testi("aiuto_ferma") : testi("aiuto_microfono")))
            .accessibilityElement()
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(acceso ? testi("ferma") : testi("aiuto_microfono"))
            .accessibilityAction { clic() }
    }

    private func clic() {
        guard fintoSecondi == nil else { return }
        if ascolta { fermaEManda(); return }
        guard !altrove, !spento else { return }
        Task { await comincia(tenendo: false) }
    }

    private func comincia(tenendo: Bool) async {
        await reg.comincia(voce: voce, chiave: chiave, cosa: cosa, esito: "", cartella: cartella,
                           cartellaRegistro: cartellaRegistro, testi: testi)


        if tenendo && !premuto && reg.e(voce, chiave) && reg.stato == .registra { fermaEManda() }
    }

    private func fermaEManda() {
        guard fintoSecondi == nil, let r = reg.ferma() else { return }
        Task { await mandaAudio(r) }
    }



    private var ascolto: some View {
        let secondi = fintoSecondi ?? reg.secondi
        let bassa = fintoSecondi == nil && reg.bassa
        return HStack(spacing: 10) {
            Text(testi("ti_ascolto").replacingOccurrences(of: "{tempo}", with: Registratore.durata(secondi)))
                .font(.system(size: 13, weight: .medium)).monospacedDigit()
                .fixedSize()
            OndaLivello(livello: fintoSecondi != nil ? 0.6 : reg.livello, bassa: bassa, finta: fintoSecondi != nil)
                .frame(minWidth: 60, maxWidth: 220, minHeight: 22, maxHeight: 22)
                .help(testi("aiuto_livello"))
            if bassa {
                Label(testi("livello_basso"), systemImage: "mic.badge.xmark")
                    .font(.system(size: 11)).foregroundStyle(Salute.attenzione.colore)
                    .lineLimit(1)
            }
            Spacer(minLength: 4)
            Button(testi("annulla_dettato")) { if fintoSecondi == nil { reg.annulla() } }
                .help(testi("aiuto_annulla_dettato"))
            Button(testi("ferma")) { fermaEManda() }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.return, modifiers: .command)
                .help(testi("aiuto_ferma"))
        }
        .controlSize(.small)
        .transition(.opacity)
    }

    private func riga(_ frase: String, rotella: Bool) -> some View {
        HStack(spacing: 8) {
            if rotella { ProgressView().controlSize(.small) }
            Text(frase).font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 0)
        }
    }

    private func daParte(_ d: Registratore.DaParte) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "waveform").foregroundStyle(.secondary)
            Text(d.corta ? testi("dettato_corto")
                 : testi("dettato_da_parte").replacingOccurrences(of: "{durata}", with: Registratore.durata(d.registrazione.secondi)))
                .font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 8)
            if !d.corta {
                Button(testi("manda_lo_stesso")) {
                    if let r = reg.riprendiDaParte() { Task { await mandaAudio(r) } }
                }
            }
            Button(testi("chiudi_richiesta")) { reg.lasciaDaParte() }
        }
        .controlSize(.small)
    }



    private var campo: some View {
        HStack(alignment: .center, spacing: 6) {
            TextField(segnaposto, text: $testo, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .lineLimit(righe)
                .focused($attivo)
                .disabled(spento || invio)
                .foregroundStyle(invio ? .secondary : .primary)
                .onSubmit { manda() }
                .onKeyPress(.return, phases: .down) { k in

                    guard k.modifiers.contains(.shift) else { return .ignored }
                    testo += "\n"
                    return .handled
                }
                .onAppear { if fuocoSubito { attivo = true } }
            if invio {
                ProgressView().controlSize(.small)
            } else if !testo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Button { manda() } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 20))
                        .symbolRenderingMode(.hierarchical)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.accentColor)
                .help(testi("manda_comando"))
                .transition(.scale.combined(with: .opacity))
            }
        }
    }

    private func manda() {
        let t = testo.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, !invio else { return }
        invio = true
        Task {
            if await mandaTesto(t) { testo = "" }
            invio = false
            attivo = true
        }
    }
}



struct OndaLivello: View {
    let livello: Double
    let bassa: Bool
    var finta = false
    @State private var campioni: [Double] = Array(repeating: 0.05, count: 28)
    @Environment(\.accessibilityReduceMotion) private var ridotto

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: ridotto || finta)) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate

            GeometryReader { geo in
                let n = campioni.count
                let passo = geo.size.width / CGFloat(n)
                let colore: Color = bassa ? Salute.attenzione.colore : Color.accentColor
                HStack(spacing: 0) {
                    ForEach(Array(campioni.enumerated()), id: \.offset) { i, c in
                        let vivo = ridotto || finta ? 1.0 : 0.82 + 0.18 * sin(t * 7 + Double(i) * 0.9)
                        let h = max(3, CGFloat(c * vivo) * geo.size.height)
                        RoundedRectangle(cornerRadius: passo * 0.3)
                            .fill(colore.opacity(0.35 + 0.65 * Double(i) / Double(n)))
                            .frame(width: passo * 0.6, height: h)
                            .frame(width: passo, height: geo.size.height)
                    }
                }
            }
        }
        .onAppear {
            if finta {
                campioni = (0..<28).map(Self.campioneFinto)
            }
        }
        .onChange(of: livello) { _, nuovo in
            guard !finta else { return }
            campioni.removeFirst()
            campioni.append(max(0.05, min(1, nuovo)))
        }
    }


    static func campioneFinto(_ i: Int) -> Double {
        let x = Double(i)
        let a: Double = abs(sin(x * 0.55))
        let b: Double = 0.5 + 0.5 * abs(cos(x * 0.23))
        return 0.15 + 0.75 * a * b
    }
}
