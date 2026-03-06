import subprocess
import imaplib
import email
import dbus
import socket
import re  # Added for robust token parsing
from email.header import decode_header
from email.utils import parsedate_to_datetime

# NETWORK PROTECTION:
# Sets a global timeout of 10 seconds for all network operations.
# This prevents "zombie" processes and keeps the Conky interface responsive.
socket.setdefaulttimeout(10)

def get_online_accounts():
    """Fetches Google/Outlook accounts from GNOME Online Accounts via DBus."""
    accounts = []
    try:
        bus = dbus.SessionBus()
        manager_obj = bus.get_object('org.gnome.OnlineAccounts', '/org/gnome/OnlineAccounts')
        manager = dbus.Interface(manager_obj, 'org.freedesktop.DBus.ObjectManager')
        # Timeout for DBus communication to avoid hanging
        managed_objects = manager.GetManagedObjects(timeout=5)
        
        for path, interfaces in managed_objects.items():
            if 'org.gnome.OnlineAccounts.Account' in interfaces:
                acc_props = interfaces['org.gnome.OnlineAccounts.Account']
                acc_id = path.split('/')[-1]
                email_addr = str(acc_props['PresentationIdentity'])
                
                server = None
                if "gmail.com" in email_addr:
                    server = "imap.gmail.com"
                elif "hotmail.com" in email_addr or "outlook.com" in email_addr:
                    server = "imap-mail.outlook.com"
                
                if server:
                    accounts.append({'id': acc_id, 'user': email_addr, 'server': server})
    except Exception:
        pass
    return accounts

def get_goa_token(acc_id):
    """Retrieves the OAuth2 access token for a specific account ID."""
    try:
        cmd = ["gdbus", "call", "--session", "--dest", "org.gnome.OnlineAccounts",
               "--object-path", f"/org/gnome/OnlineAccounts/Accounts/{acc_id}",
               "--method", "org.gnome.OnlineAccounts.OAuth2Based.GetAccessToken"]
        
        output = subprocess.check_output(cmd, text=True, timeout=5)
        # ROBUST PARSING: Uses Regex to find the token between single quotes.
        # This is more stable than .split() if the output format changes slightly.
        token_match = re.search(r"'(.*?)'", output)
        return token_match.group(1) if token_match else None
    except Exception:
        return None

def process_mail_engine(server, user, token, count=2):
    """Connects to IMAP server using OAuth2 and prints the latest emails."""
    mail = None
    try:
        # Establish secure IMAP connection with timeout
        mail = imaplib.IMAP4_SSL(server, timeout=10)
        auth_string = f"user={user}\x01auth=Bearer {token}\x01\x01"
        mail.authenticate('XOAUTH2', lambda x: auth_string)
        mail.select("INBOX", readonly=True)
        
        status, messages = mail.search(None, 'ALL') 
        mail_ids = messages[0].split()
        
        if not mail_ids:
            return

        # UI HEADER
        print(f"--- {user.upper()} ---")

        # Fetch the last 'count' emails
        for mail_id in reversed(mail_ids[-count:]):
            res, msg_data = mail.fetch(mail_id, "(RFC822)")
            for response in msg_data:
                if isinstance(response, tuple):
                    msg = email.message_from_bytes(response[1])
                    
                    # 1. FROM (Decoded for international characters)
                    from_header = decode_header(msg.get("From", "Unknown"))[0]
                    sender = from_header[0]
                    if isinstance(sender, bytes):
                        sender = sender.decode(from_header[1] or "utf-8", errors='ignore')
                    
                    # 2. SUBJECT
                    subject_header = decode_header(msg.get("Subject", "No Subject"))[0]
                    subject = subject_header[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(subject_header[1] or "utf-8", errors='ignore')

                    # 3. TIME (Formatted for Conky)
                    date_str = msg.get("Date")
                    try:
                        dt = parsedate_to_datetime(date_str).astimezone()
                        formatted_date = dt.strftime("%d %b %H:%M")
                    except Exception:
                        formatted_date = date_str

                    # 4. BODY (Extracting plain text, ignoring HTML)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    payload = part.get_payload(decode=True)
                                    body = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
                                    break
                                except Exception:
                                    pass
                    else:
                        payload = msg.get_payload(decode=True)
                        body = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')

                    # Clean up body text (remove newlines and excess spaces)
                    clean_body = " ".join(body.replace("\n", " ").split())
                    short_body = (clean_body[:80] + "...") if len(clean_body) > 80 else clean_body

                    # OUTPUT: Standardized for English Conky widgets
                    print(f"TIME: {formatted_date}")
                    print(f"FROM: {sender}")
                    print(f"SUBJ: {subject}")
                    print(f"BODY: {short_body}")
                    print("-" * 40)
        
        mail.logout()
    except Exception:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

if __name__ == "__main__":
    accounts = get_online_accounts()
    for acc in accounts:
        token = get_goa_token(acc['id'])
        if token:
            process_mail_engine(acc['server'], acc['user'], token)
