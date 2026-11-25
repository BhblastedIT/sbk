import AppKit
import SwiftUI


struct PaginaPipeline: View {
    let stato: Stato

    var body: some View {
        PaginaScorrevole(stato: stato, titolo: "Pipeline",
                         sottotitolo: "\(stato.stadi.count) steps in \(stato.fasi.count) phases, in the order they run") {
            ForEach(Array(stato.fasi.enumerated()), id: \.element.id) { i, fase in
                SchedaFase(fase: fase, numero: i + 1, stato: stato)
            }
        }
    }
}

struct SchedaFase: View {
    let fase: Fase
    let numero: Int
    let stato: Stato
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var ridotto

    private var aperta: Bool { !store.fasiChiuse.contains(fase.id) }
    private var scelta: Bool { store.selezione == .fase(fase.id) }

    var body: some View {
        VStack(spacing: 0) {
            Button {
                withAnimation(Movimento.cambio(ridotto)) {
                    if aperta { store.fasiChiuse.insert(fase.id) } else { store.fasiChiuse.remove(fase.id) }
                }
            } label: {
                HStack(spacing: 14) {
                    Anello(frazione: NodoFase.frazione(fase, stato: stato), colore: NodoFase.colore(fase), lato: 40, spessore: 4) {
                        Text("\(numero)").font(.headline.monospacedDigit())
                    }
                    .help("Phase \(numero) of \(stato.fasi.count). The ring fills with the steps that are up to date with the data.")
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {


                            Text(fase.nome).font(.headline).lineLimit(1).minimumScaleFactor(0.85)
                            Etichetta(testo: fase.etichetta)
                                .help(Etichetta.aiuto)
                        }
                        Text(fase.descrizione).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    }


                    .layoutPriority(-1)
                    Spacer(minLength: Spazio.fratelli)
                    Pillola(segnale: .fase(fase))
                        .fixedSize()
                    Text(fase.data)
                        .font(.callout.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .frame(minWidth: 36, idealWidth: 56, maxWidth: 56, alignment: .trailing)
                        .help("The phase's last run, that is the oldest date among its steps.")
                    Image(systemName: "chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(aperta ? 0 : -90))
                        .help(aperta ? "Close the phase" : "Open the phase")
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .contextMenu {
                Button("Show the phase detail") {
                    store.selezione = .fase(fase.id)
                    store.ispettore = true
                }
            }
            if aperta {
                Separatore()
                contenuto
                    .padding(.vertical, 6)
                    .transition(.opacity)
            }
        }
        .scheda(interno: 0)
        .overlay {
            RoundedRectangle(cornerRadius: Raggio.scheda, style: .continuous)
                .strokeBorder(Color.accentColor, lineWidth: scelta ? 2 : 0)
        }
    }

    @ViewBuilder private var contenuto: some View {
        VStack(spacing: 0) {
            if fase.id == "scarico" {
                let vive = stato.fonti.filter { ["a_mano", "da_sole", "inventari"].contains($0.gruppo) }
                let ok = vive.filter { ["ok", "in_corso"].contains($0.salute) }.count
                RigaNota(simbolo: "tray.and.arrow.down.fill", tinta: .blue,
                         testo: "\(ok) of \(vive.count) sources up to date. Each has its own card in Sources.") {
                    Button("Open the sources") { store.sezione = .fonti }
                }
            }
            if fase.pagata {
                RigaNota(simbolo: "creditcard.fill", tinta: .purple,
                         testo: "They start with the complete Full run, after the estimate, your step-by-step choice and two confirmations.") {
                    Button("Complete full run…") { store.apriSpesa() }
                        .disabled(store.occupato)
                }
            }


            if let perche = fase.perche, !perche.isEmpty, let azione = fase.azione {
                let tinta = Salute(motore: fase.salute) == .attenzione ? Color.orange : Color(nsColor: .systemGray)
                RigaNota(simbolo: "info.circle.fill", tinta: tinta, testo: perche) {
                    if let fermo = store.fermo(azione) {
                        Text(fermo).font(Testo.secondario).foregroundStyle(.secondary).lineLimit(2)
                    } else {
                        Button(azione.etichetta) { store.esegui(azione) }
                    }
                }
            }
            ForEach(stato.stadi.filter { fase.stadi.contains($0.id) }) { s in
                RigaStadio(stadio: s)
            }
        }
    }
}


struct RigaNota<Azione: View>: View {
    let simbolo: String
    let tinta: Color
    let testo: String
    @ViewBuilder var azione: () -> Azione

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: simbolo).foregroundStyle(tinta)
            Text(testo).font(Testo.secondario).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Spazio.fratelli)
            azione().buttonStyle(.bordered)
        }
        .padding(10)
        .background(tinta.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .padding(.horizontal, 12)
        .padding(.vertical, 4)
    }
}

struct RigaStadio: View {
    let stadio: Stadio
    @Environment(Store.self) private var store
    @State private var sopra = false

    private var scelta: Bool { store.selezione == .stadio(stadio.id) }

    var body: some View {
        Button {
            store.selezione = .stadio(stadio.id)
            store.ispettore = true
        } label: {
            HStack(spacing: 12) {
                Text("\(stadio.numero)")
                    .font(Testo.secondario.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: 22, alignment: .trailing)
                SegnaleView(segnale: .stadio(stadio, breve: true), compatto: true)




                Text(stadio.nome)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .layoutPriority(-1)
                Text(stadio.parola_breve ?? stadio.parola)
                    .font(Testo.secondario)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .fixedSize()
                Text(stadio.data ?? Quando.breve(stadio.ultimo.quando))
                    .font(Testo.secondario.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .frame(width: 56, alignment: .trailing)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(scelta ? Superficie.selezione : (sopra ? Superficie.incasso : .clear))
                    .padding(.horizontal, 6)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)

        .help(stadio.aiuto ?? stadio.parola)
        .onHover { sopra = $0 }
        .accessibilityLabel("Step \(stadio.numero), \(stadio.nome), \(stadio.parola_breve ?? stadio.parola), \(stadio.data ?? "")")
    }
}
