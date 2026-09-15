"""POP3 adapter for notifier.py; never issues DELE or RETR."""
import email
from email import policy
import poplib
import ssl
import time
import logging

import notifier


def scan(config, db):
    host = 'msa.ntu.edu.tw'
    account = host + '/' + config['username']
    db.execute('CREATE TABLE IF NOT EXISTS pop_seen (account TEXT, uid TEXT, PRIMARY KEY (account, uid))')
    db.execute('CREATE TABLE IF NOT EXISTS pop_ready (account TEXT PRIMARY KEY)')
    mailbox = poplib.POP3_SSL(host, 995, context=ssl.create_default_context(), timeout=30)
    try:
        mailbox.user(config['username'])
        mailbox.pass_(config['password'])
        entries = []
        for line in mailbox.uidl()[1]:
            number, uid = line.split()
            entries.append((int(number), uid.decode('ascii')))
        if db.execute('SELECT 1 FROM pop_ready WHERE account=?', (account,)).fetchone() is None:
            notifier.send(config['webhook'], 'NTU POP3 notifier started. New messages will be reported.')
            with db:
                db.executemany('INSERT OR IGNORE INTO pop_seen VALUES (?, ?)',
                               [(account, uid) for _, uid in entries])
                db.execute('INSERT INTO pop_ready VALUES (?)', (account,))
            logging.info('POP3 baseline saved (%s existing messages)', len(entries))
            return
        for number, uid in entries:
            if db.execute('SELECT 1 FROM pop_seen WHERE account=? AND uid=?', (account, uid)).fetchone():
                continue
            # TOP 0 requests only headers and never requests deletion.
            raw = b'\r\n'.join(mailbox.top(number, 0)[1])
            message = email.message_from_bytes(raw, policy=policy.default)
            def field(name):
                return ' '.join(str(message.get(name, '(none)')).split())[:300]
            content = (f'New NTU email\nFrom: {field("From")}\n'
                       f'Subject: {field("Subject")}\nDate: {field("Date")}\n'
                       'Open NTU WebMail to read it.')
            notifier.send(config['webhook'], content)
            with db:
                db.execute('INSERT OR IGNORE INTO pop_seen VALUES (?, ?)', (account, uid))
            logging.info('POP3 notification delivered')
            time.sleep(1)
    finally:
        try:
            mailbox.quit()
        except Exception:
            mailbox.close()


if __name__ == '__main__':
    notifier.scan = scan
    notifier.main()
