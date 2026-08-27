from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Decoupled Email Service for transactional emails (Password Reset OTP, Notifications).
    Uses SMTP configuration from application settings.
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        use_tls: Optional[bool] = None,
    ):
        self.smtp_host = smtp_host if smtp_host is not None else settings.SMTP_HOST
        self.smtp_port = smtp_port if smtp_port is not None else settings.SMTP_PORT
        self.smtp_username = smtp_username if smtp_username is not None else settings.SMTP_USERNAME
        self.smtp_password = smtp_password if smtp_password is not None else settings.SMTP_PASSWORD
        self.from_email = from_email if from_email is not None else settings.SMTP_FROM_EMAIL
        self.from_name = from_name if from_name is not None else settings.SMTP_FROM_NAME
        self.use_tls = use_tls if use_tls is not None else settings.SMTP_USE_TLS

    def send_password_reset_otp(
        self,
        recipient_email: str,
        otp: str,
        expires_in_minutes: int = 10,
    ) -> bool:
        """
        Send Password Reset OTP to recipient email address.
        Returns True if sent successfully or handled in dev/test mode.
        """
        subject = "Password Reset OTP - AI Paper Generator"

        plain_content = (
            f"Your Password Reset OTP is: {otp}\n\n"
            f"This OTP is valid for {expires_in_minutes} minutes.\n"
            f"Use this OTP to verify your identity and reset your password.\n\n"
            f"SECURITY WARNING: Do not share this OTP with anyone.\n"
            f"If you did not request a password reset, please ignore this email."
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f4f6f8; margin: 0; padding: 20px; }}
                .container {{ max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                .header {{ font-size: 20px; font-weight: bold; color: #1e293b; margin-bottom: 20px; text-align: center; }}
                .otp-box {{ background-color: #f1f5f9; border: 1px dashed #64748b; font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #0f172a; text-align: center; padding: 15px; margin: 20px 0; border-radius: 6px; }}
                .info {{ font-size: 14px; color: #475569; line-height: 1.6; margin-bottom: 15px; }}
                .warning {{ font-size: 12px; color: #ef4444; font-weight: bold; margin-top: 20px; border-top: 1px solid #e2e8f0; padding-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">Password Reset Request</div>
                <div class="info">You requested to reset your password for AI Paper Generator. Use the OTP below to complete the verification:</div>
                <div class="otp-box">{otp}</div>
                <div class="info">This OTP will expire in <strong>{expires_in_minutes} minutes</strong>.</div>
                <div class="warning">SECURITY NOTICE: Never share this OTP with anyone. If you did not request a password reset, please ignore this email.</div>
            </div>
        </body>
        </html>
        """

        if not self.smtp_host:
            logger.info(f"SMTP_HOST not configured. Email to {recipient_email} simulated successfully.")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
            msg["To"] = recipient_email

            msg.attach(MIMEText(plain_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Password reset OTP email sent successfully to {recipient_email}.")
            return True
        except Exception as exc:
            logger.error(f"Failed to send password reset OTP email to {recipient_email}: {exc}")
            raise RuntimeError(f"Failed to deliver email: {exc}")
