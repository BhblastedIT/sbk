import AppKit
import SwiftUI
import WebKit











struct PaginaPagine: View {
    let stato: Stato
    @Environment(Store.self) private var store

    var body: some View {
        VStack(spacing: 0) {
            if store.haFasce {
                Fasce(stato: stato)
                    .padding(.horizontal, Spazio.margine)
                    .padding(.vertical, Spazio.interno)
                Divider()
            }
            if let p = store.pagine {
                HStack(spacing: 0) {
                    ColonnaPagine(pagine: p)
                        .frame(width: 340)
                    Divider()
                    LettoreAccanto(pagine: p)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if let e = store.errorePagine {
                Text(e).foregroundStyle(.secondary).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }

        .task { await store.apriPagine() }
    }
}



struct Pagine: Codable, Hashable {
    let ok: Bool
    let verdetto: String
    let spiegazione: String
    let letto: String
    let pagine: [PaginaArtifact]
    let account: [AccountPagine]
    let errori: [String]
    let testi: [String: String]

    let cartella: String?
    let registro: String?


    func t(_ chiave: String, _ valori: [String: String] = [:]) -> String {
        var testo = testi[chiave] ?? chiave
        for (k, v) in valori { testo = testo.replacingOccurrences(of: "{\(k)}", with: v) }
        return testo
    }
}

struct PaginaArtifact: Codable, Hashable, Identifiable {
    let id: String
    let url: String
    let titolo: String
    let contesto: String
    let descrizione: String
    let quando: String
    let gruppo_data: String
    let ordine_data: Int
    let account: String
    let email: String
    let frase_account: String
    let principale: Bool
    let certezza: String
    let frase_certezza: String
    let come: String
    let copia: String?
    let frase_copia: String
    let versioni: Int

    let raccolta: String?
    let giusta: Bool?

    let progetto: String?
    let prova: Bool?

    let dove: String?

    let riga: String?
    let testa: String?
    let copia_vecchia: Bool?
    let solo_online: String?

    let famiglia: String?
    let capofamiglia: Bool?
    let versioni_famiglia: [VersioneFamiglia]?
}


struct VersioneFamiglia: Codable, Hashable, Identifiable {
    let id: String
    let url: String
    let titolo: String
    let quando: String
    let account: String
    let principale: Bool
    let copia: String?
    let frase: String
}

struct AccountPagine: Codable, Hashable, Identifiable {
    let id: String
    let titolo: String
    let email: String
    let pagine: Int
}

enum VistaPagine: String, CaseIterable, Identifiable {
    case data, progetto, account
    var id: String { rawValue }
}



struct ColonnaPagine: View {
    let pagine: Pagine
    @Environment(Store.self) private var store
    @FocusState private var elencoAttivo: Bool

    var body: some View {
        @Bindable var store = store
        let righe = Self.righe(pagine, store: store)
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(pagine.t("titolo")).font(.system(size: 22, weight: .bold))
                    Text("\(righe.count)").font(.title3).foregroundStyle(.secondary).monospacedDigit()
                    Spacer(minLength: 0)
                    if store.pagineInLettura {
                        ProgressView().controlSize(.small)
                    }
                    Button {
                        Task { await store.caricaPagine(rileggi: true) }
                    } label: {
                        Image(systemName: Simbolo.aggiorna)
                    }
                    .buttonStyle(.borderless)
                    .disabled(store.pagineInLettura || store.modoIstantanea)
                    .help(pagine.t("aiuto_rileggi"))
                }
                TextField(pagine.t("cerca"), text: $store.cercaPagine)
                    .textFieldStyle(.roundedBorder)
                HStack(spacing: Spazio.fratelli) {
                    Picker(pagine.t("raggruppa"), selection: $store.vistaPagine) {
                        Text(pagine.t("per_data")).tag(VistaPagine.data)
                        Text(pagine.t("per_progetto")).tag(VistaPagine.progetto)
                        Text(pagine.t("per_account")).tag(VistaPagine.account)
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .fixedSize()
                    .help(pagine.t("aiuto_vista"))
                    Spacer(minLength: 0)
                    Toggle(pagine.t("nascondi_prove"), isOn: $store.nascondiProve)
                        .toggleStyle(.checkbox)
                        .help(pagine.t("aiuto_prove"))
                }
                .font(Testo.secondario)
            }
            .padding(.horizontal, 14)
            .padding(.top, 14)
            .padding(.bottom, 10)
            if store.pagineNonRilette {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: Simbolo.attenzione).foregroundStyle(Salute.attenzione.colore)
                    Text(store.oraPagine.map { pagine.t("errore_rilettura", ["ora": $0]) }
                         ?? pagine.t("errore_rilettura_senza_ora"))
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    Button(pagine.t("riprova")) { Task { await store.caricaPagine() } }
                        .buttonStyle(.link)
                }
                .font(Testo.secondario)
                .padding(.horizontal, 14)
                .padding(.bottom, 8)
            }
            Divider()
            if pagine.pagine.isEmpty {
                Text(pagine.t("nessuna_qui"))
                    .font(Testo.secondario).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(24)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if righe.isEmpty {
                VStack(spacing: 10) {
                    Text(pagine.t("nessuna_trovata")).font(Testo.secondario).foregroundStyle(.secondary)
                    if store.filtroPagine != nil || store.nascondiProve {
                        Button(pagine.t("tutte")) {
                            store.filtroPagine = nil
                            store.nascondiProve = false
                        }
                        .buttonStyle(.link)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(selection: $store.paginaScelta) {
                    ForEach(Self.gruppi(righe, pagine: pagine, vista: store.vistaPagine), id: \.0) { titolo, voci in
                        Section(titolo) {
                            ForEach(voci) { p in
                                RigaBiblioteca(pagine: pagine, pagina: p)
                                    .tag(p.id)
                            }
                        }
                    }
                }
                .listStyle(.inset)
                .focused($elencoAttivo)

                .onCopyCommand {
                    guard let p = store.paginaAperta, let u = URL(string: p.url) else { return [] }
                    return [NSItemProvider(object: u.absoluteString as NSString)]
                }
            }
            Divider()
            PiedeBiblioteca(pagine: pagine, righe: Self.righe(pagine, store: store, senzaFiltro: true))
        }
        .onAppear {

            if store.paginaScelta == nil || !righe.contains(where: { $0.id == store.paginaScelta }) {
                store.paginaScelta = store.paginaAperta.map { $0.famiglia?.isEmpty == false ? $0.famiglia! : $0.id }
                    ?? righe.first?.id
            }
            store.apriScelta(store.paginaScelta)
            elencoAttivo = true
        }
        .onChange(of: store.paginaScelta) { _, nuova in store.apriScelta(nuova) }
    }




    static func righe(_ p: Pagine, store: Store, senzaFiltro: Bool = false) -> [PaginaArtifact] {
        let q = store.cercaPagine.trimmingCharacters(in: .whitespaces)
        return p.pagine.filter { r in
            guard r.capofamiglia != false else { return false }
            if store.nascondiProve && r.prova == true && q.isEmpty { return false }
            if !senzaFiltro {
                switch store.filtroPagine {
                case "altri": if r.account.isEmpty || r.principale { return false }
                case "ignoti": if !r.account.isEmpty { return false }
                default: break
                }
            }
            guard !q.isEmpty else { return true }
            let testi = [r.titolo, r.contesto, r.email, r.descrizione, r.account, r.riga ?? ""]
                + (r.versioni_famiglia ?? []).map(\.titolo)
            return testi.contains { $0.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil }
        }
    }

    static func gruppi(_ voci: [PaginaArtifact], pagine: Pagine, vista: VistaPagine) -> [(String, [PaginaArtifact])] {
        switch vista {
        case .data:
            let ordine = Set(voci.map(\.ordine_data)).sorted()
            return ordine.map { o in
                let g = voci.filter { $0.ordine_data == o }
                return (g.first?.gruppo_data ?? "", g)
            }
        case .progetto:

            var gruppi: [String: [PaginaArtifact]] = [:]
            for v in voci { gruppi[v.progetto ?? "", default: []].append(v) }
            return gruppi.sorted { a, b in
                if a.key.isEmpty != b.key.isEmpty { return !a.key.isEmpty }
                return (a.value.map(\.quando).max() ?? "") > (b.value.map(\.quando).max() ?? "")
            }
            .map { ($0.key.isEmpty ? pagine.t("senza_progetto") : $0.key, $0.value) }
        case .account:
            return pagine.account.compactMap { a in
                let g = voci.filter { $0.account == a.id }
                return g.isEmpty ? nil : (a.titolo, g)
            }
        }
    }
}



struct RigaBiblioteca: View {
    let pagine: Pagine
    let pagina: PaginaArtifact
    @Environment(Store.self) private var store
    @State private var sopra = false
    @State private var copiato = false

    var body: some View {
        HStack(spacing: 10) {
            Anteprima(pagina: pagina)
                .frame(width: 64, height: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(pagina.titolo).font(Testo.nome).lineLimit(1)
                Text(pagina.riga ?? pagina.contesto)
                    .font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            if sopra || copiato {
                Button {
                    copiaLink(pagina)
                    copiato = true
                    Task {
                        try? await Task.sleep(nanoseconds: 1_800_000_000)
                        copiato = false
                    }
                } label: {
                    Image(systemName: copiato ? "checkmark" : "link")
                }
                .buttonStyle(.borderless)
                .help(copiato ? pagine.t("copiato") : pagine.t("aiuto_copia_link"))
            }
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .onHover { sopra = $0 }
        .help([pagina.frase_account, pagina.frase_certezza].filter { !$0.isEmpty }.joined(separator: ". "))
        .contextMenu { MenuPagina(pagine: pagine, pagina: pagina) }
    }
}


struct MenuPagina: View {
    let pagine: Pagine
    let pagina: PaginaArtifact
    @Environment(Store.self) private var store

    var body: some View {
        Button(pagine.t("apri_online")) { apriOnline(pagina) }
        Button(pagine.t("copia_link")) { copiaLink(pagina) }
        if let c = pagina.copia {
            Button(pagine.t("mostra_finder")) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: c)])
            }
        }
        if let vers = pagina.versioni_famiglia, vers.count > 1 {
            Menu(pagine.t("versioni")) {
                ForEach(vers) { v in
                    Button(v.frase) {
                        store.paginaScelta = pagina.id
                        store.apriVersione(v.id)
                    }
                }
            }
        }
    }
}


struct Anteprima: View {
    let pagina: PaginaArtifact
    @Environment(Store.self) private var store

    var body: some View {
        let forma = RoundedRectangle(cornerRadius: Raggio.piccolo, style: .continuous)

        forma.fill(Superficie.riquadro)
            .overlay {
                if let img = store.anteprima(pagina) {
                    Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                } else {
                    Image(systemName: pagina.copia == nil ? "globe" : "doc.richtext")
                        .foregroundStyle(.secondary)
                }
            }
            .clipShape(forma)
        .overlay(forma.strokeBorder(Superficie.separatore, lineWidth: 0.5))
        .accessibilityHidden(true)
    }
}



struct PiedeBiblioteca: View {
    let pagine: Pagine
    let righe: [PaginaArtifact]
    @Environment(Store.self) private var store

    var body: some View {
        let altri = righe.filter { !$0.account.isEmpty && !$0.principale }.count
        let ignoti = righe.filter { $0.account.isEmpty }.count
        HStack(spacing: 6) {
            if altri > 0 {
                pezzo("altri", pagine.t("su_altri", ["n": "\(altri)"]), aiuto: pagine.t("aiuto_su_altri"))
            }
            if altri > 0 && ignoti > 0 {
                Text("·").foregroundStyle(.tertiary)
            }
            if ignoti > 0 {
                pezzo("ignoti", pagine.t("senza_account", ["n": "\(ignoti)"]), aiuto: pagine.t("aiuto_senza_account"))
            }
            Spacer(minLength: 0)
        }
        .font(Testo.minimo)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private func pezzo(_ id: String, _ testo: String, aiuto: String) -> some View {
        let acceso = store.filtroPagine == id
        return Button(testo) { store.filtroPagine = acceso ? nil : id }
            .buttonStyle(.plain)
            .foregroundStyle(acceso ? Color.accentColor : Color.secondary)
            .fontWeight(acceso ? .semibold : .regular)
            .help(aiuto)
    }
}





struct LettoreAccanto: View {
    let pagine: Pagine
    @Environment(Store.self) private var store

    var body: some View {
        if let p = store.paginaAperta {
            VStack(spacing: 0) {
                TestaLettore(pagine: pagine, pagina: p)
                Divider()
                if p.copia != nil, p.copia_vecchia == true, !p.frase_copia.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "clock.arrow.circlepath").foregroundStyle(.secondary)
                        Text(p.frase_copia)
                        Spacer(minLength: 0)
                    }
                    .font(Testo.secondario)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 6)
                    .background(Superficie.riquadro)
                    Divider()
                }
                if let c = p.copia {
                    if store.modoIstantanea {

                        Color(nsColor: .textBackgroundColor)
                    } else {
                        VistaWeb(file: URL(fileURLWithPath: c))
                    }
                } else {
                    VStack(spacing: 14) {
                        Image(systemName: "globe").font(.system(size: 34)).foregroundStyle(.secondary)
                        Text(p.solo_online ?? p.frase_copia)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: 360)
                        Button(pagine.t("apri_online")) { apriOnline(p) }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.large)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        } else {
            Text(pagine.t("scegli")).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

struct TestaLettore: View {
    let pagine: Pagine
    let pagina: PaginaArtifact
    @Environment(Store.self) private var store
    @State private var copiato = false

    var body: some View {

        let capo = pagina.capofamiglia == false
            ? pagine.pagine.first { $0.id == pagina.famiglia } : pagina
        let versioni = capo?.versioni_famiglia ?? []
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(pagina.titolo).font(Testo.nome).lineLimit(1)
                HStack(spacing: 6) {
                    Text(pagina.testa ?? pagina.frase_account)
                        .font(Testo.secondario).foregroundStyle(.secondary).lineLimit(1)
                    if versioni.count > 1, let k = versioni.firstIndex(where: { $0.id == pagina.id }) {
                        Menu {
                            ForEach(versioni) { v in
                                Button {
                                    store.apriVersione(v.id)
                                } label: {
                                    if v.id == pagina.id {
                                        Label(v.frase, systemImage: "checkmark")
                                    } else {
                                        Text(v.frase)
                                    }
                                }
                            }
                        } label: {
                            Text(pagine.t("versione_di", ["k": "\(versioni.count - k)", "n": "\(versioni.count)"]))
                                .font(Testo.secondario)
                        }
                        .menuStyle(.borderlessButton)
                        .fixedSize()
                        .help(pagine.t("aiuto_versioni"))
                    }
                }
            }
            Spacer(minLength: Spazio.fratelli)
            Button(pagine.t("apri_online")) { apriOnline(pagina) }
                .keyboardShortcut("o", modifiers: .command)
                .help("\(pagine.t("aiuto_apri_online")) \(pagina.frase_account). (⌘O)")
            Button {
                copiaLink(pagina)
                copiato = true
                Task {
                    try? await Task.sleep(nanoseconds: 1_800_000_000)
                    copiato = false
                }
            } label: {
                Image(systemName: copiato ? "checkmark" : "link")
            }
            .help(copiato ? pagine.t("copiato") : pagine.t("aiuto_copia_link"))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Superficie.pagina)
    }
}



func apriOnline(_ p: PaginaArtifact) {
    if let u = URL(string: p.url) { NSWorkspace.shared.open(u) }
}

func copiaLink(_ p: PaginaArtifact) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(p.url, forType: .string)
}



struct VistaWeb: NSViewRepresentable {
    let file: URL



    @MainActor static let archivio = WKWebsiteDataStore.nonPersistent()

    func makeCoordinator() -> Coordinatore { Coordinatore() }

    func makeNSView(context: Context) -> WKWebView {
        let conf = WKWebViewConfiguration()
        conf.websiteDataStore = Self.archivio
        let web = WKWebView(frame: .zero, configuration: conf)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        carica(web, context.coordinator)
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        if context.coordinator.caricato != file { carica(web, context.coordinator) }
    }

    private func carica(_ web: WKWebView, _ c: Coordinatore) {
        c.caricato = file
        web.loadFileURL(file, allowingReadAccessTo: file.deletingLastPathComponent())
    }

    @MainActor
    final class Coordinatore: NSObject, WKNavigationDelegate, WKUIDelegate {
        var caricato: URL?

        func webView(_ webView: WKWebView, decidePolicyFor azione: WKNavigationAction) async -> WKNavigationActionPolicy {
            if azione.navigationType == .linkActivated, let u = azione.request.url, Coordinatore.fuori(u) {
                NSWorkspace.shared.open(u)
                return .cancel
            }
            return .allow
        }


        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for azione: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let u = azione.request.url, Coordinatore.fuori(u) { NSWorkspace.shared.open(u) }
            return nil
        }

        private static func fuori(_ u: URL) -> Bool {
            ["http", "https", "mailto"].contains(u.scheme?.lowercased() ?? "")
        }
    }
}






@MainActor
final class Anteprime: NSObject, WKNavigationDelegate {
    private var coda: [URL] = []
    private var inCorso: URL?
    private var finestra: NSWindow?
    private var web: WKWebView?
    private var scadenza: DispatchWorkItem?

    private var fallite: Set<URL> = []

    var cartella: URL?

    var dopo: (URL, Bool) -> Void = { _, _ in }

    static func file(per copia: URL, in cartella: URL?) -> URL {
        if let cartella {
            return cartella.appendingPathComponent(copia.deletingLastPathComponent().lastPathComponent + ".png")
        }
        return copia.deletingLastPathComponent().appendingPathComponent("_anteprima.png")
    }

    func chiedi(_ copia: URL) {
        guard inCorso != copia, !coda.contains(copia), !fallite.contains(copia) else { return }
        coda.append(copia)
    }


    func prossima(permesso: Bool) {
        guard inCorso == nil else { return }
        guard permesso, !coda.isEmpty else {
            if coda.isEmpty { chiudi() }
            return
        }
        let copia = coda.removeFirst()
        inCorso = copia
        let w = web ?? apri()
        let lavoro = DispatchWorkItem { [weak self] in self?.finita(copia, immagine: nil) }
        scadenza = lavoro
        DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: lavoro)
        w.loadFileURL(copia, allowingReadAccessTo: copia.deletingLastPathComponent())
    }

    private func apri() -> WKWebView {
        let rett = NSRect(x: 0, y: 0, width: 1280, height: 800)
        let f = NSWindow(contentRect: rett, styleMask: [.borderless], backing: .buffered, defer: false)
        f.isReleasedWhenClosed = false
        let conf = WKWebViewConfiguration()
        conf.websiteDataStore = VistaWeb.archivio
        let w = WKWebView(frame: rett, configuration: conf)
        w.navigationDelegate = self
        f.contentView = w
        finestra = f
        web = w
        return w
    }

    private func chiudi() {
        web?.navigationDelegate = nil
        web = nil
        finestra?.close()
        finestra = nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        Task { @MainActor in

            try? await Task.sleep(nanoseconds: 700_000_000)
            guard let copia = self.inCorso, let w = self.web else { return }
            let conf = WKSnapshotConfiguration()
            conf.snapshotWidth = 256
            w.takeSnapshot(with: conf) { [weak self] img, _ in
                Task { @MainActor in self?.finita(copia, immagine: img) }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if let c = inCorso { finita(c, immagine: nil) }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if let c = inCorso { finita(c, immagine: nil) }
    }

    private func finita(_ copia: URL, immagine: NSImage?) {
        guard inCorso == copia else { return }
        scadenza?.cancel()
        scadenza = nil
        inCorso = nil
        var riuscita = false
        if let immagine, let tiff = immagine.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
           let png = rep.representation(using: .png, properties: [:]) {
            let dest = Self.file(per: copia, in: cartella)
            try? FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            riuscita = (try? png.write(to: dest, options: .atomic)) != nil
        }
        if !riuscita { fallite.insert(copia) }
        dopo(copia, riuscita)
    }
}
