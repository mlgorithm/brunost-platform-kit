"""Notification adapters with a safe in-memory default."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage


@dataclass
class MemoryNotificationAdapter:
    messages: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        self.messages.append({"recipient": recipient, "subject": subject, "body": body})


@dataclass
class SmtpNotificationAdapter:
    host: str
    port: int = 587
    sender: str = "noreply@localhost"
    username: str | None = None
    password: str | None = None
    starttls: bool = True

    def send(self, *, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as server:
            if self.starttls:
                server.starttls()
            if self.username:
                server.login(self.username, self.password or "")
            server.send_message(message)
