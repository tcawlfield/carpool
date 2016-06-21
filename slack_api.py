import urllib2
import urllib
import json

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
