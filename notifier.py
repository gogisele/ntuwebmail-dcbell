import email
from email import policy
import imaplib
import json
import logging
import os
from pathlib import Path
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class RateLimited(Exception):
    def __init__(self, seconds):
        self.seconds = seconds


def send(webhook, content):
    parsed = urllib.parse.urlsplit(webhook)
    if parsed.scheme != 'https' or parsed.hostname != 'discord.com' or not parsed.path.startswith('/api/webhooks/'):
        raise ValueError('Invalid webhook URL')
    query = urllib.parse.parse_qsl(parsed.query)
    query = [(k, v) for k, v in query if k != 'wait'] + [('wait', 'true')]
    url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    body = json.dumps({'content': content, 'allowed_mentions': {'parse': []}}).encode()
    request = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json', 'User-Agent': 'NTUMailNotifier/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as error:
        if error.code == 429:
            try:
                seconds = float(json.loads(error.read()).get('retry_after', 60))
            except (ValueError, TypeError):
                seconds = 60
            raise RateLimited(max(1, seconds)) from None
        raise


def checked(result):
    status, data = result
    if status != 'OK':
        raise RuntimeError('IMAP command failed')
    return data


def scan(config, db):
    with imaplib.IMAP4_SSL(config['host'], 993, ssl_context=ssl.create_default_context(), timeout=30) as mailbox:
        mailbox.login(config['username'], config['password'])
        checked(mailbox.select('INBOX', readonly=True))
        validity = mailbox.response('UIDVALIDITY')[1]
        if not validity or not validity[0]:
            raise RuntimeError('Missing UIDVALIDITY')
        validity = int(validity[0])
        identity = config['host'] + '/' + config['username'] + '/INBOX'
        saved = db.execute('SELECT identity, validity, uid FROM progress WHERE id=1').fetchone()
        if saved is None or saved[:2] != (identity, validity):
            # UIDNEXT is a snapshot: messages arriving afterward remain eligible.
            next_uid = mailbox.response('UIDNEXT')[1]
            if not next_uid or not next_uid[0]:
                raise RuntimeError('Missing UIDNEXT')
            last = int(next_uid[0]) - 1
            message = ('NTU IMAP notifier started. New messages will be reported.' if saved is None
                       else 'Mailbox identity changed. Baseline reset; check missed mail manually.')
            send(config['webhook'], message)
            with db:
                db.execute('INSERT OR REPLACE INTO progress VALUES (1, ?, ?, ?)', (identity, validity, last))
            logging.info('Baseline saved; watching INBOX')
            return
        last = saved[2]
        data = checked(mailbox.uid('search', None, 'UID', f'{last + 1}:*'))
        # IMAP reversed ranges can return an older UID; explicitly filter it.
        uids = sorted(int(uid) for uid in (data[0] or b'').split() if int(uid) > last)
        for uid in uids:
            data = checked(mailbox.uid('fetch', str(uid), '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'))
            raw = next((part[1] for part in data if isinstance(part, tuple)), None)
            if raw is None:
                raise RuntimeError('Message disappeared; retry next poll')
            message = email.message_from_bytes(raw, policy=policy.default)
            def field(name):
                return ' '.join(str(message.get(name, '(none)')).split())[:300]
            content = f'New NTU email\nFrom: {field("From")}\nSubject: {field("Subject")}\nDate: {field("Date")}\nOpen NTU WebMail to read it.'
            send(config['webhook'], content)
            with db:
                db.execute('UPDATE progress SET uid=? WHERE id=1', (uid,))
            logging.info('Notification delivered')
            time.sleep(1)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    base = Path(__file__).resolve().parent
    with open(os.environ.get('NTU_CONFIG', str(base / 'config.json'))) as file:
        config = json.load(file)
    if '--test' in sys.argv:
        send(config['webhook'], 'NTU notifier test message. Check your mobile notification settings.')
        return
    state_dir = Path(os.environ.get('NTU_STATE_DIR', str(base / 'state')))
    state_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state_dir / 'state.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY, identity TEXT, validity INTEGER, uid INTEGER)')
    failures = 0
    while True:
        delay = max(60, int(config.get('interval', 60)))
        try:
            scan(config, db)
            failures = 0
        except RateLimited as error:
            delay = max(delay, error.seconds)
            logging.warning('Discord rate limit; waiting before retry')
        except Exception as error:
            failures += 1
            delay = max(delay, min(900, 60 * 2 ** min(failures - 1, 4)))
            # Do not log exception text: it may contain credentials or the webhook.
            code = f' HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else ''
            logging.error('Check failed (%s%s); retry in %ss', type(error).__name__, code, delay)
        time.sleep(delay)


if __name__ == '__main__':
    main()
