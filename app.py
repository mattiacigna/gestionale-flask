from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file
import pandas as pd
import json
import os
import csv
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from io import BytesIO
import zipfile

app = Flask(__name__)
app.secret_key = 'chiave-segreta-sicura'

utenti = {
    "admin": "240399",
    "emanuele": "180102",
    "marco": "1234",
    "dario": "280108"
}

prelievi_commesse = {}
FILE_MAGAZZINO_INTERNO = "MAGAZZINO_INTERNO.xlsx"
USERS_FILE = "utenti.json"
TIMBR_LOG = "timbrature.csv"
FILE_MAGAZZINO = "GESTIONALE_ORIGINALE.xlsm"

# Funzioni utili JSON
def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/')
def home():
    if "utente" in session:
        return render_template("home.html", utente=session["utente"])
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    errore = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username in utenti and utenti[username] == password:
            session["utente"] = username
            session["user"] = username
            return redirect(url_for("home"))
        else:
            errore = "Username o password errati."
    return render_template("login.html", errore=errore)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/gestione_utenti', methods=['GET', 'POST'])
def gestione_utenti():
    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    users = load_json(USERS_FILE, {})

    if request.method == 'POST':
        azione = request.form.get("azione")

        if azione == "aggiungi":
            nu = request.form['new_user'].strip()
            np = request.form['new_pwd'].strip()
            if nu and np and nu not in users:
                users[nu] = {'pwd': np}

        elif azione == "modifica":
            old_name = request.form['mod_user']
            new_name = request.form.get('new_name', '').strip()
            new_pwd = request.form.get('new_pwd', '').strip()

            if old_name in users:
                data = users.pop(old_name)
                if new_pwd:
                    data['pwd'] = new_pwd
                if not new_name:
                    new_name = old_name
                users[new_name] = data

        elif azione == "rimuovi":
            ru = request.form.get("remove_user", "").strip()
            if ru in users:
                users.pop(ru)

        save_json(USERS_FILE, users)
        return redirect(url_for('gestione_utenti'))

    return render_template('gestione_utenti.html', users=users)

@app.route("/stampa_commessa/<commessa>")
def stampa_commessa(commessa):
    if "utente" not in session:
        return redirect(url_for("login"))

    try:
        df_scan = pd.read_excel(FILE_MAGAZZINO, sheet_name="SCANSIONE")
        df_desc = pd.read_excel(FILE_MAGAZZINO, sheet_name="DB_Codici")
        df_scan.columns = df_scan.columns.str.strip()
        df_desc.columns = df_desc.columns.str.strip()

        df_scan = df_scan.astype({'ETICHETTA': str, 'COMMESSA': str, 'Nome Disegno': str})
        df_scan["ETICHETTA"] = df_scan["ETICHETTA"].str.replace(r"[\\*()\\s]", "", regex=True).str.upper()
        df_desc["NOME DISEGNO"] = df_desc["NOME DISEGNO"].astype(str)

        df = pd.merge(
            df_scan, df_desc[["NOME DISEGNO", "DESCRIZIONE"]],
            left_on="Nome Disegno", right_on="NOME DISEGNO", how="left"
        ).drop(columns=["NOME DISEGNO"])

        df = df.rename(columns={
            "COMMESSA": "commessa",
            "Cliente": "cliente",
            "Nome Disegno": "disegno",
            "Quantità Disponibile": "quantita",
            "ETICHETTA": "etichetta",
            "DESCRIZIONE": "descrizione"
        })

        df_commessa = df[df["commessa"] == commessa]

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        y = height - 50

        logo_path = os.path.join("static", "img", "logo.png")
        if os.path.exists(logo_path):
            logo_width = 140
            logo_height = 60
            c.drawImage(logo_path, (width - logo_width) / 2, y - logo_height, width=logo_width, height=logo_height)
            y -= (logo_height + 20)

        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(width / 2, y, f"Distinta Commessa: {commessa}")
        y -= 30

        c.setFont("Helvetica", 12)

        for _, row in df_commessa.iterrows():
            if y < 100:
                c.showPage()
                y = height - 50
                if os.path.exists(logo_path):
                    c.drawImage(logo_path, (width - logo_width) / 2, y - logo_height, width=logo_width, height=logo_height)
                    y -= (logo_height + 20)
                c.setFont("Helvetica-Bold", 16)
                c.drawCentredString(width / 2, y, f"Distinta Commessa: {commessa}")
                y -= 30
                c.setFont("Helvetica", 12)

            testo = f"{row['disegno']} | Q.tà: {row['quantita']} | {row['descrizione']}"
            c.drawString(50, y, testo)
            y -= 20

            barcode = code128.Code128(row["etichetta"], barHeight=20, barWidth=0.6)
            barcode.drawOn(c, 50, y)
            y -= 40

        c.save()
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f"{commessa}.pdf")

    except Exception as e:
        return f"Errore nella generazione PDF: {str(e)}"
    
@app.route("/visualizza_lavori", methods=["GET", "POST"])
def visualizza_lavori():
    if "utente" not in session:
        return redirect(url_for("login"))

    utente = session["utente"]
    try:
        df_scan = pd.read_excel("GESTIONALE_ORIGINALE.xlsm", sheet_name="SCANSIONE")
        df_desc = pd.read_excel("GESTIONALE_ORIGINALE.xlsm", sheet_name="DB_Codici")

        df_scan.columns = df_scan.columns.str.strip()
        df_desc.columns = df_desc.columns.str.strip()

        # Forzatura colonne a stringa per evitare errori su .strip()
        for col in ["ETICHETTA", "COMMESSA", "Cliente", "Nome Disegno"]:
            df_scan[col] = df_scan[col].astype(str)
        df_desc["NOME DISEGNO"] = df_desc["NOME DISEGNO"].astype(str)

        df = pd.merge(df_scan, df_desc[["NOME DISEGNO", "DESCRIZIONE"]],
                      left_on="Nome Disegno", right_on="NOME DISEGNO", how="left").drop(columns=["NOME DISEGNO"])

        df = df.rename(columns={
            "COMMESSA": "commessa",
            "Cliente": "cliente",
            "Nome Disegno": "disegno",
            "Quantità Disponibile": "quantita",
            "ETICHETTA": "etichetta",
            "DESCRIZIONE": "descrizione"
        })

        # GESTIONE PRELIEVO TRADIZIONALE E CON BARCODE
        if request.method == "POST" and utente != "admin":
            commessa = request.form.get("commessa")
            disegno = request.form.get("disegno")
            if commessa and disegno:
                key = (commessa, disegno)
                prelievi_commesse[key] = prelievi_commesse.get(key, 0) + 1

            barcode_value = request.form.get("barcode_input")
            if barcode_value:
                codice_letto = barcode_value.strip("*").upper()
                trovato = False
                for _, row in df.iterrows():
                    etichetta_db = str(row["etichetta"]).strip("*").upper()
                    if etichetta_db == codice_letto:
                        key = (row["commessa"], row["disegno"])
                        prelievi_commesse[key] = prelievi_commesse.get(key, 0) + 1
                        trovato = True
                        break
                if not trovato:
                    return "⚠️ Codice non trovato tra le commesse assegnate."

        dati_commesse = {}
        for commessa, gruppo in df.groupby("commessa"):
            righe = []
            for _, riga in gruppo.iterrows():
                key = (riga["commessa"], riga["disegno"])
                prelevati = prelievi_commesse.get(key, 0)
                residuo = max(0, riga["quantita"] - prelevati)
                riga_data = riga.to_dict()
                riga_data["quantita"] = residuo
                righe.append(riga_data)
            dati_commesse[commessa] = righe

        return render_template("visualizza_lavori.html", dati_commesse=dati_commesse, utente=utente)

    except Exception as e:
        return f"Errore durante il caricamento dei dati: {str(e)}"

@app.route("/magazzino_commesse")
def magazzino_commesse():
    if "utente" not in session:
        return redirect(url_for("login"))
    try:
        df_s = pd.read_excel("GESTIONALE_ORIGINALE.xlsm", sheet_name="SCANSIONE")
        df_d = pd.read_excel("GESTIONALE_ORIGINALE.xlsm", sheet_name="DB_Codici")
        df_s.columns = df_s.columns.str.strip()
        df_d.columns = df_d.columns.str.strip()

        df = pd.merge(df_s, df_d[["NOME DISEGNO", "DESCRIZIONE"]],
                      left_on="Nome Disegno", right_on="NOME DISEGNO", how="left").drop(columns=["NOME DISEGNO"])

        df = df.rename(columns={
            "COMMESSA": "commessa",
            "Cliente": "cliente",
            "Nome Disegno": "codice",
            "Quantità Disponibile": "quantita",
            "ETICHETTA": "etichetta",
            "DESCRIZIONE": "descrizione"
        })

        righe = df.to_dict(orient="records")
        return render_template("magazzino_commesse.html", righe=righe)

    except Exception as e:
        return f"Errore nel caricamento del magazzino commesse: {str(e)}"

@app.route("/stato_commesse")
def stato_commesse():
    if "utente" not in session:
        return redirect(url_for("login"))

    try:
        df_scan = pd.read_excel("GESTIONALE_ORIGINALE.xlsm", sheet_name="SCANSIONE")
        df_scan.columns = df_scan.columns.str.strip()
        df_scan["ETICHETTA"] = df_scan["ETICHETTA"].astype(str)
        df_scan["COMMESSA"] = df_scan["COMMESSA"].astype(str)
        df_scan["Nome Disegno"] = df_scan["Nome Disegno"].astype(str)

        stato_commesse = {}
        for commessa, gruppo in df_scan.groupby("COMMESSA"):
            totale = gruppo["Quantità Disponibile"].sum()
            prelevati = 0
            for _, riga in gruppo.iterrows():
                key = (riga["COMMESSA"], riga["Nome Disegno"])
                prelevati += prelievi_commesse.get(key, 0)
            percentuale = int((prelevati / totale) * 100) if totale > 0 else 0
            stato_commesse[commessa] = {
                "totale": int(totale),
                "prelevati": int(prelevati),
                "percentuale": percentuale
            }

        return render_template("stato_commesse.html", stato_commesse=stato_commesse)

    except Exception as e:
        return f"Errore nel calcolo dello stato commesse: {str(e)}"


@app.route("/materiali_consumo", methods=["GET", "POST"])
def materiali_consumo():
    if "utente" not in session:
        return redirect(url_for("login"))

    utente = session["utente"]
    file_xlsx = FILE_MAGAZZINO_INTERNO

    try:
        df_cons = pd.read_excel(file_xlsx, sheet_name="CONSUMABILI", engine="openpyxl")
        df_cons.columns = df_cons.columns.str.strip().str.lower()
        consumabili = df_cons.to_dict(orient="records")

        df_bull = pd.read_excel(file_xlsx, sheet_name="BULLONERIA", header=None, engine="openpyxl")
        intestazioni_col = df_bull.iloc[1, 1:].tolist()
        bulloneria = []

        for i in range(2, len(df_bull)):
            base = df_bull.iloc[i, 0]
            for j, tipo in enumerate(intestazioni_col, start=1):
                q = df_bull.iloc[i, j]
                if pd.notna(q):
                    bulloneria.append({
                        "nome": f"{base}_{tipo}",
                        "quantita": int(q),
                        "index_riga": i,
                        "index_col": j,
                        "alert": q < 5
                    })

        if request.method == "POST" and utente != "admin":
            if "consumabili_index" in request.form:
                idx = int(request.form["consumabili_index"])
                df_cons.at[idx, "quantità"] = max(0, df_cons.at[idx, "quantità"] - 1)
                with pd.ExcelWriter(file_xlsx, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                    df_cons.to_excel(writer, sheet_name="CONSUMABILI", index=False)
                return redirect(url_for("materiali_consumo") + "#consumabili")

            elif "bullone_riga" in request.form and "bullone_col" in request.form:
                r = int(request.form["bullone_riga"])
                c = int(request.form["bullone_col"])
                df_bull.iloc[r, c] = max(0, df_bull.iloc[r, c] - 1)
                with pd.ExcelWriter(file_xlsx, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                    df_bull.to_excel(writer, sheet_name="BULLONERIA", index=False, header=False)
                return redirect(url_for("materiali_consumo") + "#bulloneria")

        return render_template("materiali_consumo.html",
                               utente=utente,
                               consumabili=consumabili,
                               bulloneria=bulloneria)

    except Exception as e:
        return f"Errore nella lettura del magazzino interno: {str(e)}"

from datetime import datetime
import zipfile

@app.route('/genera_distinta')
def genera_distinta():
    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    try:
        # Carica dati
        df = pd.read_excel(FILE_MAGAZZINO, sheet_name='SCANSIONE')
        df.columns = df.columns.str.strip()

        df = df.rename(columns={
            'Nome Disegno': 'disegno',
            'Quantità Disponibile': 'quantita',
            'COMMESSA': 'commessa',
            'FORNITORE': 'fornitore'
        })

        df = df[['commessa', 'fornitore', 'disegno', 'quantita']]

        # Cartella output
        out_dir = 'static/distinte_ordini'
        os.makedirs(out_dir, exist_ok=True)

        # Svuota vecchi file
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))

        files = []
        data_str = datetime.now().strftime('%Y-%m-%d')

        # Genera file per ciascuna coppia COMMESSA + FORNITORE
        for (commessa, fornitore), gruppo in df.groupby(['commessa', 'fornitore']):
            nome_file = f"Distinta_{commessa}_{fornitore}_{data_str}.xlsx".replace(' ', '_')
            path_file = os.path.join(out_dir, nome_file)
            gruppo[['disegno', 'quantita']].sort_values(by='disegno').to_excel(path_file, index=False)
            files.append(nome_file)

        # Crea ZIP con tutte le distinte
        zip_path = os.path.join(out_dir, f"Distinte_Tutte_{data_str}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for f in files:
                zipf.write(os.path.join(out_dir, f), arcname=f)

        return render_template('genera_distinta.html', files=files, zipfile=os.path.basename(zip_path))

    except Exception as e:
        return f"❌ Errore durante la generazione: {str(e)}"

@app.route('/download_distinte_zip/<filename>')
def download_distinte_zip(filename):
    if session.get('user') != 'admin':
        return redirect(url_for('login'))
    return send_from_directory('static/distinte_ordini', filename, as_attachment=True)


@app.route('/download_distinta/<filename>')
def download_distinta(filename):
    if session.get('user') != 'admin':
        return redirect(url_for('login'))
    return send_from_directory('static/distinte_ordini', filename, as_attachment=True)


# --- TIMBRATURE (entrata/uscita) ---
@app.route('/timbrature', methods=['GET', 'POST'])
def timbrature():
    if 'user' not in session:
        return redirect(url_for('login'))

    u = session['user']
    now = datetime.now()

    # File log timbrature
    if not os.path.exists(TIMBR_LOG):
        with open(TIMBR_LOG, 'w', newline='') as f:
            csv.writer(f).writerow(['utente', 'data', 'ora', 'azione'])

    # Registrazione nuova timbratura
    if request.method == 'POST':
        az = request.form['azione']
        with open(TIMBR_LOG, 'a', newline='') as f:
            csv.writer(f).writerow([u, now.strftime('%Y-%m-%d'), now.strftime('%H:%M'), az])
        return redirect(url_for('timbrature'))

    # Lettura timbrature
    logs = []
    with open(TIMBR_LOG, newline='') as f:
        for r in csv.DictReader(f):
            logs.append(r)

    # Calcolo timbrature per admin o operatore
    if u == 'admin':
        utenti_logs = {}
        for r in logs:
            utenti_logs.setdefault(r['utente'], []).append(r)

        # Calcolo ore per ogni operatore
        ore_lavorate = {}
        for utente, timbr in utenti_logs.items():
            if utente == 'admin':
                continue
            timbr_sorted = sorted(timbr, key=lambda x: (x['data'], x['ora']))
            ore = len(timbr_sorted) // 2
            ore_lavorate[utente] = ore

        return render_template("timbrature.html",
                               timbrature=utenti_logs,
                               ore_lavorate=ore_lavorate,
                               user=u)
    else:
        # Solo visualizzazione personale
        user_logs = [r for r in logs if r['utente'] == u]
        ore = len(user_logs) // 2
        return render_template("timbrature.html",
                               timbrature={u: user_logs},
                               ore_lavorate={u: ore},
                               user=u)


if __name__=='__main__':
    app.run(debug=True)
