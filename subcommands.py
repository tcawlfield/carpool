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

import logging
from collections import OrderedDict
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

import slack_api
from slack_api import post_to_log_channel
import aliases

declaratives = OrderedDict()

ddb = boto3.resource('dynamodb', region_name='us-west-2')
table_carpoolers = 'carpoolers'
table_settings = 'carpool-settings'
TOKENS = 'tokens'

settings_defaults = dict(
    log_channel_name='logbook',
    trip_cost=Decimal(12.),
    new_user_credit=Decimal(24.),
    bot_api_token='',
)

def nf(x):
    "My number formatting"
    return '{:.2f}'.format(x).rstrip('0').rstrip('.')

# Imperatives are first: "introduce me"
# (formerly subcommands)
imperatives = OrderedDict()
def imperative(fcn):
    name = fcn.__name__
    if '_' in name:
        name = name[:name.index('_')]
    imperatives[name] = fcn
    return fcn

# Declaratives are <subject> <declarative> <object>
def declarative(fcn):
    name = fcn.__name__
    if '_' in name:
        name = name[:name.index('_')]
    declaratives[name] = fcn
    return fcn

class Request(object):
    def __init__(self, slashcmd, args, user, team_id, channel):
        self.slashcmd = slashcmd
        self.args = args
        self.user_name = user
        self.team_id = team_id
        self.channel = channel

    def handle(self):
        if not self.args:
            return imperatives['help'](self)
        elif self.args[0] in imperatives:
            self.verb = self.args[0]
            self.objs = self.args[1:]
            return imperatives[self.verb](self)
        elif len(self.args) >= 2 and self.args[1] in declaratives:
            self.subj = self.args[0]
            self.verb = self.args[1]
            self.objs = self.args[2:]
            return declaratives[self.verb](self)
        else:
            return imperatives['help'](self)

settings = None
def get_settings(req):
    global settings
    settings_tbl = ddb.Table(table_settings)
    response = settings_tbl.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    if len(response['Items']) > 0:
        settings = response['Items'][0]
        if 'log_channel_name' in settings:
            slack_api.channel = settings['log_channel_name']
        if 'bot_api_token' in settings:
            slack_api.bot_api_token = settings['bot_api_token']

@imperative
def help_subcmd(req):
    return ("{} is a carpool assistant.".format(req.slashcmd) +
            "actions are: " + ", ".join(
                [cmd for cmd in imperatives.keys()] +
                [cmd for cmd in declaratives.keys()]))

@imperative
def status(req):
    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    fields = []
    for pooler in sorted(response['Items'], key=lambda p: p[TOKENS]):
        user = '*'+pooler['user_name']+'*'
        aliases = pooler.get('aliases')
        if aliases:
            user += " aka " + ", ".join(aliases)
        fields.append('{} has {} tokens'.format(user, nf(pooler[TOKENS])))
    return dict(
        #response_type='in_channel',
        text='Current carpooler tokens',
        attachments=[
            dict(
                text='\n'.join(fields),
                mrkdwn_in=['text']
            )
        ]
    )

def what_to_return(req, rslt):
    if rslt.get('ok'):
        if req.channel == slack_api.channel:
            return 'ok' # Cannot seem to return an empty response with AWS Lambda
        else:
            return 'ok'
    else:
        return repr(rslt)

@imperative
def settings_subcmd(req):
    if len(req.objs) == 0:
        s = settings
        if s is None:
            s = settings_defaults
            s['team_id'] = req.team_id
            stbl = ddb.Table(table_settings)
            stbl.put_item(Item=s)
        attachments = []
        for k, v in s.items():
            if k != 'team_id':
                if k == 'bot_api_token':
                    attachments.append(dict(text="{}: {}".format(k, stars(v))))
                else:
                    attachments.append(dict(text="{}: {}".format(k, v)))
        return dict(
            text='Current carpool settings',
            attachments=attachments
        )
    elif len(req.objs) == 3 and req.objs[0] == 'set':
        (key, value) = req.objs[1:]
        if key not in settings_defaults:
            return "Unknown setting " + key
        try:
            if isinstance(settings_defaults[key], float):
                value = Decimal(value)
            else:
                value = type(settings_defaults[key])(value)
        except ValueError:
            return "Cannot convert {} to proper type".format(value)
        stbl = ddb.Table(table_settings)
        stbl.update_item(
            Key={'team_id': req.team_id},
            AttributeUpdates={key: dict(Value=value, Action='PUT')}
        )
        text = "Settings: changed {} to {}".format(key, value)
        if key != 'bot_api_token':
            rslt = post_to_log_channel(text=text)
        else:
            rslt = text
        if key == 'log_channel_name' and value != slack_api.channel:
            slack_api.channel = value
            rslt = post_to_log_channel(text=text)
        return what_to_return(req, rslt)
    else:
        return "usage: {0.slashcmd} settings set <param> <value>, or {0.slashcmd} settings".format(req)

def stars(token):
    return token[0] + '*'*(len(token)-2) + token[-1]

@imperative
def introduce(req):
    if len(req.objs) != 1:
        return "{0.slashcmd} introduce <user>|me".format(req)
    user = req.objs[0]
    if user == 'me':
        user = req.user_name
    carpoolers = ddb.Table(table_carpoolers)

    # check if user exists
    response = carpoolers.get_item(
        Key=dict(team_id=req.team_id, user_name=user)
    )
    if 'Item' in response and response['Item']:
        return "User {} already exists".format(user)

    # Add user
    carpoolers.put_item(Item=dict(
        team_id=req.team_id,
        user_name=user,
        tokens=settings['new_user_credit']
    ))
    rslt = post_to_log_channel(text='Added member '+user)
    return what_to_return(req, rslt)

@imperative
def echo(req):
    return "{} {} {}".format(req.slashcmd, req.verb, " ".join(req.objs))

@imperative
def give(req):
    if len(req.objs) != 2:
        return "usage: give <user> <tokens>"

    (user, add_tokens) = req.objs
    user = aliases.resolve_alias(req, user, is_object=True)
    if not user:
        return "User {} not found".format(req.objs[0])

    try:
        add_tokens = float(add_tokens)
    except ValueError:
        return "{} is not a number".format(add_tokens)

    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.get_item(
        Key=dict(team_id=req.team_id, user_name=user)
    )
    if 'Item' not in response:
        return "User {} not found".format(user)
    u = response['Item']

    new_tokens = u[TOKENS] + Decimal(add_tokens)
    carpoolers.update_item(
        Key=dict(team_id=req.team_id, user_name=user),
        AttributeUpdates={TOKENS: dict(Value=new_tokens, Action='PUT')}
    )
    if add_tokens >= 0:
        text = 'Gave {:.2f} tokens to {}, who now has {:.2f}'.format(add_tokens, user, new_tokens)
    else:
        text = 'Took {:.2f} tokens from {}, who now has {:.2f}'.format(-add_tokens, user, new_tokens)
    rslt = post_to_log_channel(text=text)
    return what_to_return(req, rslt)

@imperative
def take(req):
    if len(req.objs) != 2:
        return "usage: take <user> <tokens>"

    tokens = req.objs[1]
    try:
        tokens = float(tokens)
    except ValueError:
        return "{} is not a number".format(tokens)

    req.objs[1] = -tokens
    return give(req)

@declarative
def drove(req):
    # This one's special because 'drove' syntax is different:
    # <user> drove <user> <user> ...
    passengers = list_to_poolers(req, req.objs)
    if len(passengers) < 1:
        # need some objects
        return "{0.slashcmd} <user>|I drove <user> <user> ...".format(req)

    driver = aliases.resolve_alias(req, req.subj)
    if driver.lower() == 'i':
        driver = req.user_name

    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    poolers = {}
    pooler_list = []
    for pooler in response['Items']:
        poolers[pooler['user_name']] = pooler
        pooler_list.append(pooler['user_name'])

    if driver not in poolers:
        return "Driver {} is not a member".format(driver)
    involved = {driver} # a set
    for p in passengers:
        if p not in poolers:
            return "Passenger {} is not a member".format(p)
        elif p in involved:
            return "Member {} is mentioned twice".format(p)
        involved.add(p)

    trip_cost = settings['trip_cost'] / Decimal(len(involved))

    # Accounting calculation
    add_tokens = {driver: trip_cost * len(passengers)}
    for p in passengers:
        add_tokens[p] = -trip_cost
    new_tokens = {}
    for p in involved:
        new_tokens[p] = poolers[p][TOKENS] + add_tokens[p]

    for p in involved:
        new_tkns = carpoolers.update_item(
            Key=dict(team_id=req.team_id, user_name=p),
            UpdateExpression="Add {} :amt".format(TOKENS),
            ExpressionAttributeValues={':amt': add_tokens[p]},
            ReturnValues="UPDATED_NEW",
        )
        poolers[p][TOKENS] = new_tkns['Attributes'][TOKENS]

    #text='{} reported a trip:\n'.format(req.user_name)
    #text += '{} drove {}\n'.format(driver, ', '.join(passengers))
    #text += '<table><tr>'
    #for p in pooler_list:
    #    text += '<th>{}</th>'.format(p)
    #text += '</tr><tr>'
    #for p in pooler_list:
    #    text += '<td>{:+.2f}</td>'.format(add_tokens.get(p, 0))
    #text += '</tr><tr>'
    #for p in pooler_list:
    #    text += '<td>{:.2f}</td>'.format(new_tokens.get(p, poolers[p][TOKENS]))
    #text += '</tr></table>'

    fields = []
    pooler_list.sort(key=lambda p: poolers[p][TOKENS])
    for p in pooler_list:
        added = add_tokens.get(p, 0)
        orig = poolers[p][TOKENS] - added # since addition/subtraction was atomic, infer original value
        line = p + ':\t'
        if added == 0:
            line += '`{}`'.format(nf(poolers[p][TOKENS]))
        else:
            line += '`{} {} {} = {}`'.format(
                nf(orig), ('+' if added > 0. else '-'), nf(abs(added)), nf(poolers[p][TOKENS]))
        fields.append(line)

    rslt = post_to_log_channel(
        text='{} reported a trip:'.format(req.user_name),
        attachments=[
            dict(
                title='{} drove {}'.format(driver, ', '.join(passengers)),
                text='\n'.join(fields),
                mrkdwn_in=['text']
            )
        ]
    )
    return what_to_return(req, rslt)

@declarative
def aka(req):
    "{0.slashcmd} <user> aka <alias>"
    if len(req.objs) != 1:
        return aka.__doc__
    user = aliases.resolve_alias(req, req.subj)
    if user is None:
        return "Unknown member {}".format(req.subj)
    return aliases.register_alias(req, user, req.objs[0],
        declaratives.keys() + imperatives.keys())

def list_to_poolers(req, words):
    return aliases.resolve_aliases(req, words, is_object=True)
