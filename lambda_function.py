# Copyright 2016 Topher Cawlfield
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from base64 import b64decode
from urlparse import parse_qs
import logging
import re

import boto3

import subcommands
import slack_api

ENCRYPTED_EXPECTED_TOKENS = (
    "CiAjW2060plYw/tcOvgOuLzzLRp0x36LHpHls3VAppclyBKfA"
        "QEBAgB4I1ttOtKZWMP7XDr4Dri88y0adMd+ix6R5bN1QKaXJc"
        "gAAAB2MHQGCSqGSIb3DQEHBqBnMGUCAQAwYAYJKoZIhvcNAQc"
        "BMB4GCWCGSAFlAwQBLjARBAxDIMgp1TZZSokdCKUCARCAM74+"
        "+c0SaA6aBRjmiLkF75kkoRcq51H0P0UIBVMncwhAlYHCYUR9I"
        "EU+ntfRXqXIEEuaxg==",
    "CiAjW2060plYw/tcOvgOuLzzLRp0x36LHpHls3VAppclyBKfAQEBAgB4I1ttOtKZWMP7XDr4Dri88y0adMd+ix6R5bN1QKaXJcgAAAB2MHQGCSqGSIb3DQEHBqBnMGUCAQAwYAYJKoZIhvcNAQcBMB4GCWCGSAFlAwQBLjARBAwuS7UxA/0TTPo5CBcCARCAM3GDMiAX4LV90Ntrj1i/g0eoYCy9Ynyf3dc07KFYnyFxAheDAsuaddwzf0s+zbeqEKywwQ==",
    )

kms = boto3.client('kms')

logging.getLogger().setLevel(logging.INFO)

def lambda_handler(event, context):
    req_body = event['body']
    params = parse_qs(req_body)
    if 'token' not in params:
        return "No token"
    token = params['token'][0]
    for encrypted_token in ENCRYPTED_EXPECTED_TOKENS:
        expected_token = kms.decrypt(CiphertextBlob=b64decode(encrypted_token))['Plaintext']
        if token == expected_token:
            break
    else:
        logging.error("Request token (%s) does not match exptected", token)
        raise Exception("Invalid request token")

    if params.get('ssl_check', ['0'])[0] == '1':
        return ""

    user = params['user_name'][0]
    team_id = params['team_id'][0]
    channel = params['channel_name'][0]

    command = params['command'][0]
    command_text = params.get('text', ('help',))[0]
    command_text_list = re.split(r'[\s,]+', command_text.strip())
    req = subcommands.Request(command, command_text_list, user, team_id, channel)

    subcommands.get_settings(req)

    return req.handle()
