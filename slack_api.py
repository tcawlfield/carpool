import urllib2
import urllib
import json

ENCRYPTED_BOT_API_TOKEN = "CiAjW2060plYw/tcOvgOuLzzLRp0x36LHpHls3VAppclyBKxAQEBAgB4I1ttOtKZWMP7XDr4Dri88y0adMd+ix6R5bN1QKaXJcgAAACIMIGFBgkqhkiG9w0BBwageDB2AgEAMHEGCSqGSIb3DQEHATAeBglghkgBZQMEAS4wEQQM1qlDQ2uvRp23sFRMAgEQgEQ7q+Y+TVKMweBjEkTtKTqMI+r/ackK9UTAG/+Ehfk+WE4gvH2sGFgE5FtIA0bw3g7pBfIhayPKGslVM1dU2PoWApnrsQ=="
bot_api_token = ""
channel = ""

def post_to_log_channel(**msg):
    global bot_api_token, channel
    for k,v in msg.items():
        if not isinstance(v, str):
            msg[k] = json.dumps(v)
    data = urllib.urlencode(dict(
        token=bot_api_token,
        channel="#"+channel,
        as_user='true',
        **msg
    ))

    conn = urllib2.urlopen('https://slack.com/api/chat.postMessage', data)
    if conn.getcode() == 200:
        return json.load(conn)
    else:
        return None
