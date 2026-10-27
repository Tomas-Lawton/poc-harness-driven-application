import email
import smtplib
import ssl
import sys
from email import policy
from email.utils import formataddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))  # engine/

from checks.send import check_send
from core.config import read_setting
from core.runs import open_latest_run
from core.runs import profile_key_from_command_line


def main() -> None:
    settings, run_info = open_latest_run(profile_key_from_command_line())
    errors = check_send(settings, run_info)
    if errors:
        sys.exit("BLOCKED: checks failed:\n  " + "\n  ".join(errors))
    print("gate: recipient in the user scope, every check passed")

    host = read_setting("SMTP_HOST")
    port = int(read_setting("SMTP_PORT") or 587)
    user, password = read_setting("SMTP_USER"), read_setting("SMTP_PASSWORD")
    if not (host and user and password):
        sys.exit("NOT SET UP: email settings are missing. Setup asks for them (setup/SKILL.md, Email).")

    message = email.message_from_bytes(Path("out/email.eml").read_bytes(), policy=policy.default)
    del message["From"], message["To"]
    message["From"] = formataddr((settings.profile.title, read_setting("SMTP_FROM") or user))
    message["To"] = settings.recipient

    context = ssl.create_default_context()
    try:
        if port == 465:  # SSL from the start; other ports upgrade with STARTTLS
            server = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server:
            if port != 465:
                server.starttls(context=context)
            server.login(user, password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        sys.exit(
            f"BLOCKED: the email server refused: {error}. Check the email settings in .env (setup/SKILL.md, Email)."
        )
    print(f'SENT "{message["Subject"]}" to {settings.recipient}')


if __name__ == "__main__":
    main()
