"""Mailversand per SMTP (Standard: Microsoft 365): Anmelde-Codes und Benachrichtigungen."""
import asyncio
import html
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "") or SMTP_USER
APP_URL = os.environ.get("APP_URL", "https://geschenke.nordhain-gmbh.de")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")   # bekommt eine Mail bei jeder Neuregistrierung


def _build(to: str, subject: str, text: str, html_body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Geschenke", MAIL_FROM))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=MAIL_FROM.split("@")[-1] or None)
    msg.set_content(f"{text}\n\n{APP_URL}\n")
    msg.add_alternative(
        f"""<div style="font-family:system-ui,sans-serif;max-width:420px;margin:auto;color:#2b2622">
{html_body}
<p style="color:#7a716a;font-size:13px">🎁 <a href="{APP_URL}" style="color:#b4432f">{APP_URL}</a></p>
</div>""",
        subtype="html",
    )
    return msg


def _send(msg: EmailMessage) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


async def _deliver(msg: EmailMessage) -> None:
    if os.environ.get("MAIL_DEBUG") == "1":   # nur für lokale Tests: Mail ins Log statt verschicken
        print(f"[MAIL_DEBUG] An {msg['To']}: {msg['Subject']}\n{msg.get_body(('plain',)).get_content()}", flush=True)
        return
    if not (SMTP_USER and SMTP_PASSWORD):
        raise RuntimeError("SMTP ist nicht konfiguriert (SMTP_USER/SMTP_PASSWORD in .env)")
    # smtplib blockiert – im Thread ausführen, damit der Server weiter antwortet
    await asyncio.to_thread(_send, msg)


async def send_code(to: str, name: str, code: str, minutes: int) -> None:
    text = (f"Hallo {name},\n\ndein Anmeldecode lautet:\n\n    {code}\n\n"
            f"Er ist {minutes} Minuten gültig.\n\n"
            f"Dein Name zum Anmelden: {name}\n\n"
            f"Falls du dich nicht angemeldet hast, kannst du diese Mail einfach ignorieren.")
    body = f"""<p>Hallo {html.escape(name)},</p>
<p>dein Anmeldecode lautet:</p>
<p style="font-size:32px;letter-spacing:6px;font-weight:600;margin:16px 0">{code}</p>
<p>Er ist {minutes} Minuten gültig.</p>
<p>Dein Name zum Anmelden: <strong>{html.escape(name)}</strong></p>
<p style="color:#7a716a">Falls du dich nicht angemeldet hast, kannst du diese Mail einfach ignorieren.</p>"""
    await _deliver(_build(to, f"{code} ist dein Anmeldecode für Geschenke", text, body))


async def send_wish_removed(n: dict) -> None:
    """Benachrichtigt die reservierende Person, dass ein Wunsch von der Liste genommen wurde."""
    wo = "von der eigenen Wunschliste" if n["fuer"] == n["entfernt_von"] else f"von der Wunschliste für {n['fuer']}"
    text = (f"Hallo {n['empfaenger']},\n\n"
            f"{n['entfernt_von']} hat „{n['titel']}“ {wo} genommen.\n"
            f"Du hattest dieses Geschenk reserviert.\n\n"
            f"Falls du es schon gekauft hast: Vielleicht lässt es sich zurückgeben "
            f"oder passt zu einem anderen Anlass.")
    e = {k: html.escape(str(v)) for k, v in n.items()}
    wo_html = html.escape(wo)
    body = f"""<p>Hallo {e['empfaenger']},</p>
<p><strong>{e['entfernt_von']}</strong> hat <strong>„{e['titel']}“</strong> {wo_html} genommen.
Du hattest dieses Geschenk reserviert.</p>
<p>Falls du es schon gekauft hast: Vielleicht lässt es sich zurückgeben
oder passt zu einem anderen Anlass.</p>"""
    await _deliver(_build(n["an"], f"„{n['titel']}“ wurde von der Wunschliste genommen", text, body))


async def send_invite(to: str, name: str, inviter: str, link: str, days: int) -> None:
    """Einladung mit Link – bewusst einfach formuliert."""
    text = (f"Hallo {name},\n\n"
            f"{inviter} hat dich zur Geschenke-Liste der Familie eingeladen.\n"
            f"Dort sammeln wir Geschenkwünsche – damit niemand etwas doppelt schenkt.\n\n"
            f"Tippe auf diesen Link, um die Einladung anzunehmen:\n{link}\n\n"
            f"Dein Name zum Anmelden: {name}\n"
            f"Die Einladung gilt {days} Tage.")
    e = {k: html.escape(v) for k, v in {"name": name, "inviter": inviter, "link": link}.items()}
    body = f"""<p style="font-size:18px">Hallo {e['name']},</p>
<p style="font-size:18px"><strong>{e['inviter']}</strong> hat dich zur <strong>Geschenke-Liste der Familie</strong> eingeladen.
Dort sammeln wir Geschenkwünsche – damit niemand etwas doppelt schenkt.</p>
<p style="margin:28px 0"><a href="{e['link']}" style="display:inline-block;background:#b4432f;color:#fff;
text-decoration:none;font-size:20px;font-weight:600;padding:14px 28px;border-radius:12px">Einladung annehmen</a></p>
<p style="font-size:16px">Dein Name zum Anmelden: <strong>{e['name']}</strong></p>
<p style="color:#7a716a;font-size:14px">Die Einladung gilt {days} Tage. Falls der Knopf nicht funktioniert,
kopiere diesen Link in den Browser:<br><a href="{e['link']}" style="color:#b4432f">{e['link']}</a></p>"""
    await _deliver(_build(to, f"{inviter} lädt dich zur Geschenke-Liste ein", text, body))


async def send_new_registration(n: dict) -> None:
    """Info an den Admin, dass sich jemand neu registriert hat."""
    if not ADMIN_EMAIL:
        return
    wie = f"eingeladen von {n['eingeladen_von']}" if n["eingeladen_von"] else "mit dem Familien-Code"
    text = (f"{n['name']} hat sich gerade registriert ({wie}).\n\n"
            f"Falls du die Person nicht kennst, kannst du den Zugang sperren:\n"
            f"  docker compose exec agent python -m app.cli email-setzen \"{n['name']}\" --entfernen\n"
            f"  docker compose exec agent python -m app.cli abmelden \"{n['name']}\"")
    body = f"""<p><strong>{html.escape(n['name'])}</strong> hat sich gerade registriert ({html.escape(wie)}).</p>
<p style="color:#7a716a;font-size:14px">Falls du die Person nicht kennst, kannst du den Zugang sperren:<br>
<code>app.cli email-setzen "{html.escape(n['name'])}" --entfernen</code><br>
<code>app.cli abmelden "{html.escape(n['name'])}"</code></p>"""
    await _deliver(_build(ADMIN_EMAIL, f"Neu dabei: {n['name']}", text, body))


async def send_notifications(outbox: list[dict], log) -> None:
    """Verschickt gesammelte Benachrichtigungen. Fehler werden nur protokolliert, nie an den Chat gemeldet."""
    for n in outbox:
        try:
            if n["type"] == "wunsch_entfernt":
                await send_wish_removed(n)
            elif n["type"] == "neu_registriert":
                await send_new_registration(n)
        except Exception:
            log.exception("Benachrichtigung (%s) konnte nicht verschickt werden", n["type"])
