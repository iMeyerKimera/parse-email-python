import sys, os, StringIO, re
import email, mimetypes
from email.utils import parseaddr
from email.header import decode_header

# email address REGEX matching the RFC 2822 spec ..
# my $atom       = qr{[a-zA-Z0-9_!#\$\%&'*+/=?\^`{}~|\-]+};
# my $dot_atom   = qr{$atom(?:\.$atom)*};
# my $quoted     = qr{"(?:\\[^\r\n]|[^\\"])*"};
# my $local      = qr{(?:$dot_atom|$quoted)};
# my $domain_lit = qr{\[(?:\\\S|[\x21-\x5a\x5e-\x7e])*\]};
# my $domain     = qr{(?:$dot_atom|$domain_lit)};
# my $addr_spec  = qr{$local\@$domain};
#
# Python translation

atom_rfc2822 = r"[a-zA-Z0-9_!#\$\%&'*+/=?\^`{}~|\-]+"
atom_posfix_restricted = r"[a-zA-Z0-9_#\$&'*+/=?\^`{}~|\-]+"  # without '!' and '%'
atom = atom_rfc2822
dot_atom = atom + r"(?:\." + atom + ")*"
quoted = r'"(?:\\[^\r\n]|[^\\"])*"'
local = "(?:" + dot_atom + "|" + quoted + ")"
domain_lit = r"\[(?:\\\S|[\x21-\x5a\x5e-\x7e])*\]"
domain = "(?:" + dot_atom + "|" + domain_lit + ")"
addr_spec = local + "\@" + domain

email_address_re = re.compile('^' + addr_spec + '$')

raw = """Delivered-To: aremik82@gmail.com
Received: by 10.114.29.131 with SMTP id k3csp469759ldh;
        Fri, 19 Sep 2014 22:32:31 -0700 (PDT)
Return-Path: <3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com>
Received-SPF: pass (google.com: domain of 3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com designates 10.66.252.6 as permitted sender) client-ip=10.66.252.6
Authentication-Results: mr.google.com;
       spf=pass (google.com: domain of 3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com designates 10.66.252.6 as permitted sender) smtp.mail=3bhEdVAwJCKsVSLY-LNLOPXjRXLTW.NZXLcPXTVtnRXLTW.NZX@7SJ3MYH53AKEO4JRJXH7WZWH.apphosting.bounces.google.com;
       dkim=pass header.i=@khanacademy.org
X-Received: from mr.google.com ([10.66.252.6])
        by 10.66.252.6 with SMTP id zo6mr19579994pac.40.1411191151359 (num_hops = 1);
        Fri, 19 Sep 2014 22:32:31 -0700 (PDT)
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
        d=khanacademy.org; s=google;
        h=mime-version:message-id:date:subject:from:to:content-type;
        bh=HtWv9koaEpH5PWwPN+HkJIfWgZHCCN/dk8sqL7Arz6s=;
        b=WIKcgJ9BToxOiPHsfHslEQv5+oq9iqfQNtcmVROk0O7M+H7vhvscFN/JA2AV+NSHXG
         fBFuXqQmrjneZKJg5RY+EnDOGuuM/x8fMNzwGmgb5kdqxmYvWgnGbWFCpLSND9+JRs0k
         jtRIY8nxY/2xKRC050aWecFM/EPJ4/K6Go+k4=
MIME-Version: 1.0
X-Received: by 10.66.252.6 with SMTP id zo6mr13763216pac.40.1411191150169;
 Fri, 19 Sep 2014 22:32:30 -0700 (PDT)
X-Google-Appengine-App-Id: s~khan-academy
X-Google-Appengine-App-Id-Alias: khan-academy
Message-ID: <047d7b15ac0f374f4f0503788bb5@google.com>
Date: Sat, 20 Sep 2014 05:32:30 +0000
Subject: Your weekly progress summary on Khan Academy
From: Khan Academy <no-reply@khanacademy.org>
To: aremik82@gmail.com
Content-Type: multipart/alternative; boundary=047d7b15ac0f374f220503788bb2

--047d7b15ac0f374f220503788bb2
Content-Type: text/plain; charset=ISO-8859-1; format=flowed; delsp=yes

Meyer Kimera,
Here's a look at what you achieved this week. Check it out, and keep
learning!

Recent Accomplishments
==================================
Points: 992
Badges earned:
Minutes on Khan Academy: 4
Mastered exercises: 0





Learn more today:

http://www.khanacademy.org/linkt?c=https%3A%2F%2Fwww.khanacademy.org%2F&bp=d2Vla2x5X3VzZXJfc3VtbWFyeV9lbWFpbF9vcGVu&bi=X2dhZV9iaW5nb19yYW5kb206Z3h6cjVGQk9OalFuLUFjQUlhUWVkaGt1TFEwcC15aVYweDZFa29kcg%3D%3D

If clicking doesn't seem to work, you can copy and paste the link into your
browser's address bar.


Onward!
Sal and the Khan Academy Team

P.S. You can unsubscribe from these emails at any time by following this
link:
https://www.khanacademy.org/settings/email?t1c=ag5zfmtoYW4tYWNhZGVteXJtCxIVVXNlckVtYWlsU3Vic2NyaXB0aW9uIlJlbWFpbF9zdWI6d2Vla2x5X3N1bW1hcnk6aWQ6aHR0cDovL2dvb2dsZWlkLmtoYW5hY2FkZW15Lm9yZy8xMDA4MjY4ODA4Mzk2OTIxMzI5NzI6DA

https://www.khanacademy.org/about/privacy-policy

--047d7b15ac0f374f220503788bb2
Content-Type: text/html; charset=UTF-8
Content-Transfer-Encoding: quoted-printable
"""


def getmailheader(header_text, default="ascii"):
    """Decode header_text if needed"""
    try:
        headers = decode_header(header_text)
    except email.Errors.HeaderParseError:
        # This already appended in email.base64mime.decode()
        # instead return a sanitized ascii string
        return header_text.encode('ascii', 'replace').decode('ascii')
    else:
        for k, (text, charset) in enumerate(headers):
            try:
                headers[k] = unicode(text, charset or default, errors='replace')
            except LookupError:
                # if the charset is unknown, force default
                headers[k] = unicode(text, default, errors='replace')
        return u"".join(headers)


def getmailaddresses(msg, name):
    """retrieve From:, To:, Cc: addresses"""
    addrs = email.utils.getaddresses(msg.get_all(name, []))
    for k, (name, addr) in enumerate(addrs):
        if not name and addr:
            # only one string! Is it the address or is it the name ?
            # use the same for both and see later
            name = addr
        try:
            # address must be ascii only
            addr = addr.encode('ascii')
        except UnicodeError:
            addr = ''
        else:
            # address must match address regex
            if not email_address_re.match(addr):
                addr = ''
        addrs[k] = (getmailheader(name), addr)
    return addrs


msg = email.message_from_string(raw)
subject = getmailheader(msg.get('Subject', ''))
from_ = getmailaddresses(msg, 'from')
from_ = ('', '') if not from_ else from_[0]
tos = getmailaddresses(msg, 'to')

print 'Subject: %r' % subject
print 'From: %r' % (from_, )
print 'To: %r' % (tos, )
