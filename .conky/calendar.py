import subprocess
import dbus
import datetime
import re
import socket

# Global timeout to protect Conky from hanging during network issues
socket.setdefaulttimeout(10)

def get_goa_accounts():
    accounts = []
    try:
        bus = dbus.SessionBus()
        manager_obj = bus.get_object('org.gnome.OnlineAccounts', '/org/gnome/OnlineAccounts')
        manager = dbus.Interface(manager_obj, 'org.freedesktop.DBus.ObjectManager')
        objects = manager.GetManagedObjects(timeout=5)
        for path, interfaces in objects.items():
            if 'org.gnome.OnlineAccounts.Account' in interfaces:
                acc = interfaces['org.gnome.OnlineAccounts.Account']
                email = str(acc['PresentationIdentity'])
                # Filters for Gmail accounts, can be extended for other providers
                if "gmail.com" in email:
                    accounts.append({'id': path.split('/')[-1], 'user': email})
    except: 
        pass
    return accounts

def get_goa_token(acc_id):
    try:
        cmd = ["gdbus", "call", "--session", "--dest", "org.gnome.OnlineAccounts",
               "--object-path", f"/org/gnome/OnlineAccounts/Accounts/{acc_id}",
               "--method", "org.gnome.OnlineAccounts.OAuth2Based.GetAccessToken"]
        output = subprocess.check_output(cmd, text=True, timeout=5)
        # Robust token parsing using regex
        return re.search(r"'(.*?)'", output).group(1)
    except: 
        return None

def fetch_via_caldav(user, token):
    # ⚙️ SETTINGS: Show events for the next 14 days
    DAYS_TO_SHOW = 14 

    url = f"https://apidata.googleusercontent.com/caldav/v2/{user}/events"
    now = datetime.datetime.now(datetime.timezone.utc)
    today_date = now.date()

    start_str = now.strftime("%Y%m%dT000000Z")
    end_str = (now + datetime.timedelta(days=DAYS_TO_SHOW)).strftime("%Y%m%dT235959Z")

    xml_query = f"""
    <C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
      <D:prop><C:calendar-data /></D:prop>
      <C:filter>
        <C:comp-filter name="VCALENDAR">
          <C:comp-filter name="VEVENT">
            <C:time-range start="{start_str}" end="{end_str}"/>
          </C:comp-filter>
        </C:comp-filter>
      </C:filter>
    </C:calendar-query>
    """

    cmd = ["curl", "-s", "--max-time", "10", "-X", "REPORT", url, 
           "-H", f"Authorization: Bearer {token}",
           "-H", "Content-Type: application/xml", "--data", xml_query]

    try:
        response = subprocess.check_output(cmd, text=True, timeout=12)
        if not response or "<D:error" in response:
            # Fallback to primary calendar if user-specific URL fails
            cmd[4] = "https://apidata.googleusercontent.com/caldav/v2/primary/events"
            response = subprocess.check_output(cmd, text=True, timeout=12)

        titles = re.findall(r"SUMMARY:(.*)", response)
        starts = re.findall(r"DTSTART[:;](?:VALUE=DATE:)?(\d+T?\d*)", response)

        if not titles: return

        events = sorted(zip(starts, titles))
        # English abbreviated months for compact Conky display
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        seen = set()
        for start, title in events:
            clean_title = title.strip()
            # Unique key prevents duplicate entries in the display
            unique_key = f"{start}_{clean_title}"
            if unique_key in seen: continue
            seen.add(unique_key)

            try:
                event_year = int(start[0:4])
                event_month = int(start[4:6])
                event_day = int(start[6:8])
                event_date = datetime.date(event_year, event_month, event_day)
                delta_days = (event_date - today_date).days

                # User-friendly labels for immediate events
                if delta_days == 0:
                    date_label = "📅 TODAY"
                elif delta_days == 1:
                    date_label = "📅 TOMORROW"
                else:
                    month_str = months[event_month]
                    date_label = f"{event_day} {month_str}"

                # Show time only for non-all-day events
                time_str = f"[{start[9:11]}:{start[11:13]}] " if "T" in start else ""
                
                print(f"{date_label} — {time_str}{clean_title}")
            except: 
                continue
            
    except: 
        pass

if __name__ == "__main__":
    accounts = get_goa_accounts()
    for acc in accounts:
        token = get_goa_token(acc['id'])
        if token:
            fetch_via_caldav(acc['user'], token)
