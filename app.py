import os
import re
import smtplib
import sqlite3
from datetime import datetime
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "ganti-dengan-kunci-rahasia-kamu"

DB = "seleksi.db"
POSISI = ["IT Support", "Network Engineer", "Programmer", "Staff Admin", "Marketing"]
STATUS = ["Baru", "Lolos Seleksi Berkas", "Wawancara", "Diterima", "Ditolak"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def kirim_email_hr(pelamar):
    hr_email = os.environ.get("HR_EMAIL", "").strip()
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not hr_email or not smtp_user or not smtp_pass:
        print("[email] Lewati: HR_EMAIL / SMTP_USER / SMTP_PASS belum disetting.")
        return False
    try:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        port = int(os.environ.get("SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["Subject"] = f"Pelamar Baru: {pelamar['nama']} - {pelamar['posisi']}"
        msg["From"] = os.environ.get("FROM_EMAIL", smtp_user)
        msg["To"] = hr_email
        msg.set_content(
            f"""Ada pelamar baru yang masuk seleksi karyawan.

Nama       : {pelamar['nama']}
Email      : {pelamar['email']}
HP         : {pelamar['hp']}
Posisi     : {pelamar['posisi']}
Pendidikan : {pelamar['pendidikan']}
Pengalaman : {pelamar['pengalaman']} tahun
Keahlian   : {pelamar['keahlian'] or '-'}
Motivasi   : {pelamar['motivasi'] or '-'}
Tanggal    : {pelamar['tanggal']}

Lihat di dashboard: http://127.0.0.1:5000/admin
"""
        )
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                if port == 587:
                    server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        print(f"[email] Terkirim ke {hr_email}")
        return True
    except Exception as e:
        print(f"[email] Gagal kirim: {e}")
        return False


def catat_ke_google_sheet(pelamar):
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    creds_file = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")
    if not sheet_id or not os.path.exists(creds_file):
        print("[sheet] Lewati: GOOGLE_SHEET_ID / credentials.json belum disetting.")
        return False
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        sheet.append_row([
            pelamar["tanggal"], pelamar["nama"], pelamar["email"], pelamar["hp"],
            pelamar["posisi"], pelamar["pendidikan"], pelamar["pengalaman"],
            pelamar["keahlian"] or "", pelamar["motivasi"] or "", "Baru",
        ])
        print("[sheet] Baris ditambahkan ke Google Sheet.")
        return True
    except Exception as e:
        print(f"[sheet] Gagal catat: {e}")
        return False


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pelamar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nama TEXT NOT NULL,
                email TEXT NOT NULL,
                hp TEXT NOT NULL,
                posisi TEXT NOT NULL,
                pendidikan TEXT NOT NULL,
                pengalaman INTEGER NOT NULL DEFAULT 0,
                keahlian TEXT,
                motivasi TEXT,
                status TEXT NOT NULL DEFAULT 'Baru',
                tanggal TEXT NOT NULL
            )
        """)


@app.route("/")
def form():
    return render_template("form.html", posisi_list=POSISI)


@app.route("/daftar", methods=["POST"])
def daftar():
    nama = request.form.get("nama", "").strip()
    email = request.form.get("email", "").strip()
    hp = request.form.get("hp", "").strip()
    posisi = request.form.get("posisi", "")
    pendidikan = request.form.get("pendidikan", "")
    pengalaman = request.form.get("pengalaman", "0")
    keahlian = request.form.get("keahlian", "").strip()
    motivasi = request.form.get("motivasi", "").strip()

    if not nama or not email or not hp or posisi not in POSISI or not pendidikan:
        flash("Lengkapi semua field yang wajib diisi.", "error")
        return redirect(url_for("form"))
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Format email tidak valid.", "error")
        return redirect(url_for("form"))
    try:
        pengalaman = int(pengalaman)
        if pengalaman < 0:
            raise ValueError
    except ValueError:
        flash("Pengalaman harus angka 0 atau lebih.", "error")
        return redirect(url_for("form"))

    tanggal = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pelamar
               (nama, email, hp, posisi, pendidikan, pengalaman, keahlian, motivasi, status, tanggal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Baru', ?)""",
            (nama, email, hp, posisi, pendidikan, pengalaman, keahlian, motivasi, tanggal),
        )

    pelamar = {
        "nama": nama, "email": email, "hp": hp, "posisi": posisi,
        "pendidikan": pendidikan, "pengalaman": pengalaman,
        "keahlian": keahlian, "motivasi": motivasi, "tanggal": tanggal,
    }
    kirim_email_hr(pelamar)
    catat_ke_google_sheet(pelamar)
    return render_template("sukses.html", nama=nama, posisi=posisi)


@app.route("/admin")
def admin():
    status_filter = request.args.get("status", "Semua")
    posisi_filter = request.args.get("posisi", "Semua")
    query = "SELECT * FROM pelamar WHERE 1=1"
    params = []
    if status_filter in STATUS:
        query += " AND status = ?"
        params.append(status_filter)
    if posisi_filter in POSISI:
        query += " AND posisi = ?"
        params.append(posisi_filter)
    query += " ORDER BY id DESC"
    with get_db() as conn:
        pelamar = conn.execute(query, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM pelamar").fetchone()[0]
    return render_template(
        "admin.html", pelamar=pelamar, status_list=STATUS, posisi_list=POSISI,
        status_filter=status_filter, posisi_filter=posisi_filter, total=total,
    )


@app.route("/admin/status/<int:pelamar_id>", methods=["POST"])
def ubah_status(pelamar_id):
    status_baru = request.form.get("status", "")
    if status_baru not in STATUS:
        flash("Status tidak valid.", "error")
    else:
        with get_db() as conn:
            conn.execute("UPDATE pelamar SET status = ? WHERE id = ?", (status_baru, pelamar_id))
        flash("Status berhasil diperbarui.", "ok")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
