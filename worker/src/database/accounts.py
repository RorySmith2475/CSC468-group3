import os
import mongoengine as me

MONGO_URI = 'mongodb://' + os.environ['MONGODB_USERNAME'] + ':' + os.environ['MONGODB_PASSWORD'] + '@' + os.environ['MONGODB_HOSTNAME'] + ':27017/' + os.environ['MONGODB_DATABASE']
me.connect(host = MONGO_URI)

class Stocks(me.EmbeddedDocument):
    symbol = me.StringField(required=True, max_length=3)
    amount = me.IntField(required=True)

class AutoTransaction(me.EmbeddedDocument):
    user_id = me.StringField(required=True) # Should help to have this field here when querying.
    symbol = me.StringField(required=True, max_length=3)
    amount = me.IntField(required=True)
    trigger = me.DecimalField(default=0.00, precision=2)

class Accounts(me.Document):
    user_id = me.StringField(required=True, unique=True)
    account = me.DecimalField(default=0.00, precision=2)
    available = me.DecimalField(default=0.00, precision=2)
    stocks = me.EmbeddedDocumentListField(Stocks, default=[])
    auto_buy = me.EmbeddedDocumentListField(AutoTransaction, default=[])
    auto_sell = me.EmbeddedDocumentListField(AutoTransaction, default=[])

def get_users():
    print('Users:')
    for user in Accounts.objects:
        print(user.to_json())


