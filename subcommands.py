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

subcommand_table = OrderedDict()

ddb = boto3.resource('dynamodb', region_name='us-west-2')
table_carpoolers = 'carpoolers'
table_settings = 'carpool-settings'
TOKENS = 'tokens'

settings_defaults = dict(
    log_channel_name='logbook',
    trip_cost=12.,
    new_user_credit=24.,
)

def subcommand(fcn):
    name = fcn.__name__
    if '_' in name:
        name = name[:name.index('_')]
    subcommand_table[name] = fcn
    return fcn

class Request(object):
    def __init__(self, slashcmd, subcmd, args, user, team_id, channel):
        self.slashcmd = slashcmd
        self.subcmd = subcmd
        self.args = args
        self.user_name = user
        self.team_id = team_id
        self.channel = channel

@subcommand
def help_subcmd(req):
    return ("{} is a carpool assistant.".format(req.slashcmd) +
            "subcommands are: " + ", ".join(
                [cmd for cmd in subcommand_table.keys()]))

@subcommand
def status(req):
    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    fields = []
    for pooler in response['Items']:
        fields.append(dict(
            title=pooler['user_name'],
            value="{:.2f} tokens".format(pooler[TOKENS]),
            short=True
            ))
    return dict(
        #response_type='in_channel',
        text='Current carpooler tokens',
        attachments=[
            dict(
                text='',
                fields=fields
            )
        ]
    )

@subcommand
def settings_subcmd(req):
    if len(req.args) == 0:
        s = get_settings(req)
        if s is None:
            s = settings_defaults
            s['team_id'] = req.team_id
            stbl = ddb.Table(table_settings)
            stbl.put_item(Item=s)
        attachments = []
        for k, v in s.items():
            if k != 'team_id':
                attachments.append(dict(text="{}: {}".format(k, v)))
        return dict(
            text='Current carpool settings',
            attachments=attachments
        )
    elif len(req.args) == 3 and req.args[0] == 'set':
        s = get_settings(req)
        if req.channel != s['log_channel_name']:
            return "Can only change settings in channel {}".format(s['log_channel_name'])
        (key, value) = req.args[1:]
        if key not in settings_defaults:
            return "Unknown setting " + key
        try:
            value = type(settings_defaults[key])(value)
        except ValueError:
            return "Cannot convert {} to proper type".format(value)
        stbl = ddb.Table(table_settings)
        action = 'PUT' # if key in s else 'ADD'
        stbl.update_item(
            Key={'team_id': req.team_id},
            AttributeUpdates={key: dict(Value=value, Action=action)}
        )
        return 'ok'
    else:
        return "usage: {slashcmd} settings set <param> <value>, or {slashcmd} settings".format(**req)

def get_settings(req):
    settings = ddb.Table(table_settings)
    response = settings.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    if len(response['Items']) == 0:
        return None
    return response['Items'][0]

@subcommand
def introduce(req):
    if len(req.args) != 1:
        return "usage: {slashcmd} introduce <user>|me".format(**req)
    user = req.args[0]
    if user == 'me':
        user = req.user_name
    s = get_settings(req)
    if req.channel != s['log_channel_name']:
        return "Can only introduce users in channel {}".format(s['log_channel_name'])
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
        tokens=s['new_user_credit']
    ))
    return 'ok'

@subcommand
def echo(req):
    return "{} {} {}".format(req.slashcmd, req.subcmd, " ".join(req.args))

@subcommand
def give(req):
    if len(req.args) != 2:
        return "usage: give <user> <tokens>"
    s = get_settings(req)
    if req.channel != s['log_channel_name']:
        return "Can only give tokens to users in channel {}".format(s['log_channel_name'])

    (user, add_tokens) = req.args
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
    return dict(
        response_type='in_channel',
        text=text
    )

@subcommand
def take(req):
    if len(req.args) != 2:
        return "usage: take <user> <tokens>"

    tokens = req.args[1]
    try:
        tokens = float(tokens)
    except ValueError:
        return "{} is not a number".format(tokens)

    req.args[1] = -tokens
    return give(req)

@subcommand
def drove(req):
    # This one's special because 'drove' syntax is different:
    # <user> drove <user> <user> ...
    if len(req.args) < 2 or req.args[0] != 'drove':
        return "usage: {slashcmd} <user>|I drove <user> <user> ...".format(**req)

    driver = req.subcmd
    passengers = req.args[1:]
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

    settings = get_settings(req)
    if req.channel != settings['log_channel_name']:
        return "Can only add users in channel {}".format(settings['log_channel_name'])

    trip_cost = settings['trip_cost'] / Decimal(len(involved))

    # Accounting calculation
    add_tokens = {driver: trip_cost * len(passengers)}
    for p in passengers:
        add_tokens[p] = -trip_cost
    new_tokens = {}
    for p in involved:
        new_tokens[p] = poolers[p][TOKENS] + add_tokens[p]

    #TODO: make this atomic
    for p in involved:
        carpoolers.update_item(
            Key=dict(team_id=req.team_id, user_name=p),
            AttributeUpdates={TOKENS: dict(Value=new_tokens[p], Action='PUT')}
        )

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
    for p in pooler_list:
        fields.append(dict(
            title=p,
            value='{:+.2f}\n{:.2f}'.format(
                add_tokens.get(p, 0), new_tokens.get(p, poolers[p][TOKENS])),
            short=True
        ))

    return dict(
        response_type='in_channel',
        text='{} reported a trip:'.format(req.user_name),
        attachments=[
            dict(
                text='{} drove {}'.format(driver, ', '.join(passengers)),
                fields=fields
            )
        ]
    )
