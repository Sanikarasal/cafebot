"""
email_sender.py
Sends emails via Gmail SMTP using an App Password.

Required environment variables:
    MAIL_USERNAME  — your Gmail address  (e.g. cozicafe.app@gmail.com)
    MAIL_PASSWORD  — Gmail App Password  (16-char, spaces optional)
    MAIL_FROM_NAME — display name shown in "From" field (default: CoziCafe)
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587          # TLS (STARTTLS)


def _get_credentials() -> tuple[str, str] | tuple[None, None]:
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip().replace(" ", "")
    if not username or not password:
        return None, None
    return username, password


def send_email(to_address: str, subject: str, html_body: str, text_body: str = "") -> tuple[bool, str]:
    """
    Send an email via Gmail SMTP.
    Returns (True, "") on success, (False, error_reason) on failure.
    """
    username, password = _get_credentials()
    if not username:
        return False, "Email not configured. Set MAIL_USERNAME and MAIL_PASSWORD env vars."

    from_name = os.getenv("MAIL_FROM_NAME", "CoziCafe")
    from_address = f"{from_name} <{username}>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_address
    msg["To"]      = to_address

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(username, password)
            server.sendmail(username, to_address, msg.as_string())
        print(f"📧 Email sent to {to_address} | Subject: {subject}")
        return True, ""
    except smtplib.SMTPAuthenticationError:
        msg_err = (
            "Gmail authentication failed. "
            "Make sure MAIL_PASSWORD is a Gmail App Password (not your regular password). "
            "See: https://myaccount.google.com/apppasswords"
        )
        print(f"❌ {msg_err}")
        return False, msg_err
    except Exception as exc:
        print(f"❌ Email send failed to {to_address}: {exc}")
        return False, str(exc)


def send_otp_email(to_address: str, otp: str, username: str, expiry_minutes: int = 10) -> tuple[bool, str]:
    """Send a formatted OTP email for password reset."""
    subject = "🔐 CoziCafe — Your Password Reset OTP"

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F0E8;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F0E8;padding:40px 0;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header strip -->
        <tr><td style="background:linear-gradient(90deg,#9A6818,#D4A040,#9A6818);height:5px;"></td></tr>

        <!-- Logo area -->
        <tr><td align="center" style="padding:32px 40px 16px;">
          <div style="display:inline-block;background:#2C1810;border-radius:14px;
                      padding:12px 18px;margin-bottom:12px;">
            <span style="font-size:28px;">☕</span>
          </div>
          <h1 style="margin:8px 0 4px;font-size:22px;color:#1a1a1a;font-weight:800;">
            Password Reset
          </h1>
          <p style="margin:0;color:#888;font-size:13px;">CoziCafe Admin Panel</p>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:8px 40px 32px;">
          <p style="color:#444;font-size:15px;line-height:1.6;">
            Hi <strong>{username}</strong>,<br>
            We received a request to reset your password.
            Use the OTP below to proceed:
          </p>

          <!-- OTP box -->
          <div style="background:#F5F0E8;border:2px dashed #D4A040;border-radius:12px;
                      text-align:center;padding:28px 20px;margin:20px 0;">
            <p style="margin:0 0 6px;font-size:12px;color:#9A6818;
                      font-weight:700;letter-spacing:2px;text-transform:uppercase;">
              One-Time Password
            </p>
            <div style="font-size:42px;font-weight:900;letter-spacing:12px;
                        color:#2C1810;font-family:'Courier New',monospace;">
              {otp}
            </div>
          </div>

          <p style="color:#888;font-size:13px;text-align:center;margin:0 0 20px;">
            ⏰ This OTP expires in <strong>{expiry_minutes} minutes</strong>.
          </p>

          <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">

          <p style="color:#aaa;font-size:12px;text-align:center;margin:0;">
            If you didn't request this, ignore this email — your password won't change.<br>
            <strong>CoziCafe Admin Panel</strong>
          </p>
        </td></tr>

        <!-- Footer strip -->
        <tr><td style="background:linear-gradient(90deg,#9A6818,#D4A040,#9A6818);height:3px;"></td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text_body = (
        f"CoziCafe Password Reset\n\n"
        f"Hi {username},\n\n"
        f"Your OTP is: {otp}\n\n"
        f"This OTP expires in {expiry_minutes} minutes.\n\n"
        f"If you didn't request this, ignore this email."
    )

    return send_email(to_address, subject, html_body, text_body)
