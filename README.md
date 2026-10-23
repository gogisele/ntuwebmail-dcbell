# NTU WebMail Discord Notifier

Send new NTU WebMail notifications to a private Discord channel. The default mode uses the student-ID POP3 service at `msa.ntu.edu.tw:995`. It checks once per minute, includes sender, subject, date, and a shortened plain-text body preview, and never deletes server mail. Messages from `cool.ntu.edu.tw` are labeled as NTU COOL mail; all other messages are labeled as NTU WebMail. On the first run, it skips existing messages. Later runs use POP3 UIDL to avoid duplicate notifications. The program uses only the Python standard library and does not need a GPU.

NTU Exchange Mail and NTU WebMail are different services. These instructions are for student-ID WebMail accounts. `notifier.py` also contains an IMAP mode for Exchange Mail, which has different server settings; confirm those settings in NTU's official documentation before using it.

## Setup

Requires Python 3.10 or later. Create an Incoming Webhook in a private Discord text channel and copy its full URL. Treat that URL as a secret.

```sh
cp config.example.json config.json
nano config.json
chmod 600 config.json
```

Set `username` to your student ID without `@ntu.edu.tw`. Enter your current mailbox password and the complete Discord Webhook URL. `config.json` is ignored by Git, but check `git status` before publishing. If a password or Webhook URL has been exposed, rotate it.

```sh
python3 pop_notifier.py --test
python3 -u pop_notifier.py
```

The first command tests Discord only. The second starts polling. After you see `NTU POP3 notifier started` in Discord, send a new test email. Ctrl+C stops the foreground process. To receive phone alerts, enable Discord mobile push notifications, set server and channel notifications to All Messages, and make sure they are not muted. Discord accepting a message does not guarantee that the phone shows a banner every time.

## Run continuously on Linux

After testing, you can use a systemd user service. Run `pwd` to find your installation path, then replace both `/ABSOLUTE/PATH/TO/ntu-discord` placeholders below. Use your machine's Python path if it is not `/usr/bin/python3`.

```ini
[Unit]
Description=NTU WebMail Discord notifier
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/ABSOLUTE/PATH/TO/ntu-discord
ExecStart=/usr/bin/python3 -u /ABSOLUTE/PATH/TO/ntu-discord/pop_notifier.py
Restart=on-failure
RestartSec=60
Nice=10

[Install]
WantedBy=default.target
```

Save the service as `~/.config/systemd/user/ntu-discord.service`, then run:

```sh
systemctl --user daemon-reload
systemctl --user enable --now ntu-discord.service
systemctl --user status ntu-discord.service
journalctl --user -u ntu-discord.service -n 30
```

Stop it with `systemctl --user stop ntu-discord.service`. Running after logout or reboot may require the host administrator to enable systemd linger for your account. Follow the host's service rules. Stop any existing `nohup` or foreground instance before starting this service.

If Docker Compose is available, you can instead run `docker compose build`, `docker compose up -d`, and `docker compose logs -f`. `compose.yaml` limits the service to 0.1 CPU core and 128 MB of RAM, does not configure a GPU, and does not expose an inbound port. Host administrators with Docker access can still read mounted secrets.

## Behavior and limits

- POP3 sees only mail available through that service. Mailbox rules or folder settings may change what it sees.
- After downtime, it reports new messages still present in the POP3 mailbox.
- A successful Discord send followed by a crash before UIDL state is saved can result in a duplicate notification.
- Never publish `config.json`, `state/`, logs, or PID files. Sender, subject, date, and a body preview are sent to Discord, so use a private channel.
- A host administrator with root access can obtain credentials used by the running process. Use a device you control if that trust boundary is unacceptable.

Official references: [NTU Mail services and WebMail POP3 settings](https://ntumail.cc.ntu.edu.tw/ntumailfaq/) and [Discord Incoming Webhooks](https://docs.discord.com/developers/resources/webhook).
