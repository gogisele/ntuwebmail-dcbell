"""POP3 adapter for NTU WebMail; never deletes server mail."""
import email
from email import policy
from email.utils import parseaddr
from html.parser import HTMLParser
import poplib
import re
import ssl
import time
import logging

import notifier


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1
        elif not self.ignored and tag in ('br', 'p', 'div', 'li', 'tr'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in ('p', 'div', 'li', 'tr'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def _clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _body_text(message):
    plain = []
    html = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == 'attachment':
            continue
        kind = part.get_content_type()
        if kind not in ('text/plain', 'text/html'):
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b''
            value = payload.decode('utf-8', errors='replace')
        if kind == 'text/plain':
            plain.append(value)
        else:
            parser = _TextExtractor()
            parser.feed(value)
            html.append(''.join(parser.parts))
    text = _clean_text('\n'.join(plain) if plain else '\n'.join(html))
    return text or '(No readable text content)'


def _is_ntucool(message):
    addresses = ' '.join(str(message.get(name, '')) for name in
                         ('From', 'Sender', 'Reply-To', 'List-Id')).lower()
    sender = parseaddr(str(message.get('From', '')))[1].lower()
    domain = sender.rsplit('@', 1)[-1] if '@' in sender else ''
    subject = str(message.get('Subject', '')).lower()
    return (domain == 'cool.ntu.edu.tw' or domain.endswith('.cool.ntu.edu.tw')
            or 'cool.ntu.edu.tw' in addresses
            or 'ntu cool' in subject or 'ntucool' in subject)


def _notification(message):
    def field(name):
        return ' '.join(str(message.get(name, '(none)')).split())[:300]

    title = '= NTUcool 新郵件 =' if _is_ntucool(message) else '= NTUwebmail 新郵件 ='
    prefix = (f'{title}\n寄件者：{field("From")}\n'
              f'主旨：{field("Subject")}\n日期：{field("Date")}\n內文：\n')
    # Discord messages are limited to 2,000 characters.
    room = max(0, 1950 - len(prefix))
    body = _body_text(message)
    if len(body) > room:
        body = body[:max(0, room - 12)].rstrip() + '\n[內容已截短]'
    return prefix + body


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
            notifier.send(config['webhook'], 'NTU POP3 通知已啟動，將從現在開始通知新信。')
            with db:
                db.executemany('INSERT OR IGNORE INTO pop_seen VALUES (?, ?)',
                               [(account, uid) for _, uid in entries])
                db.execute('INSERT INTO pop_ready VALUES (?)', (account,))
            logging.info('POP3 baseline saved (%s existing messages)', len(entries))
            return
        for number, uid in entries:
            if db.execute('SELECT 1 FROM pop_seen WHERE account=? AND uid=?', (account, uid)).fetchone():
                continue
            # TOP keeps large attachments out while providing enough body text
            # for a useful Discord preview. It never deletes server mail.
            raw = b'\r\n'.join(mailbox.top(number, 200)[1])
            message = email.message_from_bytes(raw, policy=policy.default)
            notifier.send(config['webhook'], _notification(message))
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
