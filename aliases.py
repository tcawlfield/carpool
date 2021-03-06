import boto3
from boto3.dynamodb.conditions import Key

_aka = dict()

ALIASES = 'aliases'
ddb = boto3.resource('dynamodb', region_name='us-west-2')
table_carpoolers = 'carpoolers'

def _load_aliases(req):
    global _aka
    if _aka:
        return

    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.query(
        KeyConditionExpression=Key('team_id').eq(req.team_id)
    )
    for pooler in response['Items']:
        name = pooler['user_name']
        _aka[name.lower()] = name
        aliases = pooler.get(ALIASES, [])
        for alias in aliases:
            _aka[alias.lower()] = name

def resolve_aliases(req, aliases, is_object = False):
    global _aka
    _load_aliases(req)
    results = []
    for alias in aliases:
        alias = alias.lower().lstrip('@')
        if alias in _aka:
            results.append(_aka[alias])
        elif (is_object and alias == 'me') or (
            not is_object and alias == 'i'):
            results.append(req.user_name)
        elif alias == 'and' and len(aliases) > 2:
            pass
        else:
            results.append(alias) # not a member
    return results

def resolve_alias(req, alias, is_object = False):
    return resolve_aliases(req, (alias,), is_object)[0]

def register_alias(req, user, alias, illegals):
    # user should already be looked-up through resolve_aliases
    global _aka
    lalias = alias.lower()
    if lalias in _aka:
        return "Alias {} already exists for {}".format(repr(alias), _aka[lalias])
    if lalias in illegals or alias == 'and':
        return "Alias {} is a reserved word".format(repr(alias))
    _aka[lalias] = user

    carpoolers = ddb.Table(table_carpoolers)
    response = carpoolers.get_item(
        Key=dict(team_id=req.team_id, user_name=user)
    )
    if 'Item' not in response:
        return "User {} not found".format(user)
    a = response['Item'].get(ALIASES, [])
    a.append(alias)

    carpoolers.update_item(
        Key=dict(team_id=req.team_id, user_name=user),
        AttributeUpdates={ALIASES: dict(Value=a, Action='PUT')}
    )
    return "ok"
